"""
ingestion/pipeline.py

Document ingestion orchestration.

This module coordinates the complete ingestion workflow for a document.
It deliberately contains no document-processing logic itself; instead it
calls the specialised ingestion modules in sequence and persists the
result through database.repository.

Pipeline
--------
OCR (if required)
    ↓
Text extraction
    ↓
Cleaning
    ↓
Chunking
    ↓
Metadata extraction
    ↓
Glossary matching
    ↓
Repository persistence

Topic tagging and embeddings are intentionally NOT invoked here.
Those are executed later as an independent batch process.

Features
--------
- Incremental indexing
- Duplicate prevention
- Transactional persistence
- Bulk paragraph insertion
- Bulk glossary match insertion
- Repository-only database access
- Structured logging
"""

from __future__ import annotations

import hashlib
import logging

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from database import repository

from ingestion import cleaning
from ingestion import chunking
from ingestion import extractor
from ingestion import glossary
from ingestion import metadata
from ingestion import ocr

LOGGER = logging.getLogger(__name__)


###############################################################################
# Data models
###############################################################################


@dataclass(slots=True)
class IngestionResult:
    """
    Summary of one completed ingestion.

    Attributes
    ----------
    document_id
        Database identifier.

    paragraphs
        Number of stored paragraphs.

    glossary_matches
        Number of paragraph-term relationships stored.

    updated
        True if an existing document was re-indexed.

    skipped
        True if ingestion was skipped because the
        existing indexed document is already current.
    """

    document_id: int

    paragraphs: int

    glossary_matches: int

    updated: bool = False

    skipped: bool = False


###############################################################################
# Hashing
###############################################################################


def calculate_file_hash(path: Path) -> str:
    """
    Calculate a SHA-256 hash for a document.

    The hash is used to determine whether an existing
    indexed document has changed since the previous
    ingestion.

    Parameters
    ----------
    path
        PDF path.

    Returns
    -------
    str
        Hex digest.
    """

    digest = hashlib.sha256()

    with path.open("rb") as stream:

        for block in iter(lambda: stream.read(1024 * 1024), b""):

            digest.update(block)

    return digest.hexdigest()


###############################################################################
# Incremental indexing
###############################################################################


def needs_reindex(
    pdf_path: Path,
) -> tuple[bool, int | None]:
    """
    Determine whether a document requires re-indexing.

    Returns
    -------
    (needs_reindex, existing_document_id)

    Notes
    -----
    If the repository stores a source hash this is used.

    Otherwise we conservatively compare filename only.

    The repository owns all database access.
    """

    filename = pdf_path.name

    existing = repository.get_document_by_filename(filename)

    if existing is None:

        return True, None

    #
    # Future-proof:
    #
    # If source_hash exists in the schema use it.
    #

    if "source_hash" not in existing.keys():

        LOGGER.info(
            "Document '%s' already indexed.",
            filename,
        )

        return False, int(existing["id"])

    current_hash = calculate_file_hash(pdf_path)

    if existing["source_hash"] == current_hash:

        LOGGER.info(
            "Skipping unchanged document: %s",
            filename,
        )

        return False, int(existing["id"])

    LOGGER.info(
        "Detected updated document: %s",
        filename,
    )

    return True, int(existing["id"])


###############################################################################
# Glossary initialisation
###############################################################################

def initialise_glossary(
    terms_txt: str | Path,
) -> None:
    """
    Load glossary terms into the database.

    Safe to call multiple times because bulk_insert_terms()
    uses ON CONFLICT to ignore duplicates.
    """

    terms_txt = Path(terms_txt)

    LOGGER.info("Loading glossary terms...")

    glossary_terms = glossary.load_terms_txt(terms_txt)

    with repository.transaction() as connection:
        repository.bulk_insert_terms(
            ((term.term,) for term in glossary_terms),
            connection=connection,
        )

    LOGGER.info(
        "Inserted %d glossary terms.",
        len(glossary_terms),
    )

###############################################################################
# Pipeline
###############################################################################


def ingest_document(
    pdf_path: str | Path,
    *,
    terms_txt: str | Path,
) -> IngestionResult:
    """
    Run the complete ingestion pipeline.

    Parameters
    ----------
    pdf_path

        PDF document.

    terms_txt

        Path to glossary txt file.

    Returns
    -------
    IngestionResult

    Notes
    -----
    Tagging and embeddings are intentionally excluded.

    All database writes for a single document happen inside ONE
    repository transaction, so a connection is never reused after
    it has already been committed/closed.
    """

    pdf_path = Path(pdf_path)

    terms_txt = Path(terms_txt)

    LOGGER.info(
        "Beginning ingestion: %s",
        pdf_path.name,
    )

    should_index, existing_document_id = needs_reindex(
        pdf_path
    )

    if not should_index:

        return IngestionResult(
            document_id=existing_document_id,
            paragraphs=0,
            glossary_matches=0,
            skipped=True,
        )

    #
    # Existing document
    #
    # Remove it completely before rebuilding.
    #
    # This keeps paragraph numbering,
    # glossary matches and the FTS index
    # perfectly synchronised.
    #

    if existing_document_id is not None:

        LOGGER.info(
            "Replacing existing document %s",
            existing_document_id,
        )

        repository.delete_document(
            existing_document_id
        )

    ####################################################################
    # Stage 1 - OCR
    ####################################################################

    LOGGER.info("Running OCR...")

    ocr_result = ocr.ensure_searchable_pdf(pdf_path)

    ####################################################################
    # Stage 2 - Extraction
    ####################################################################

    LOGGER.info("Extracting document...")

    extraction = extractor.extract(ocr_result)

    ####################################################################
    # Stage 3 - Metadata
    ####################################################################

    LOGGER.info("Extracting metadata...")

    document_metadata = metadata.build_metadata(
        pdf_path=ocr_result.processed_pdf,
    )

    ####################################################################
    # Stage 4 - Cleaning
    #
    # clean_elements() expects the whole ExtractedDocument (it reads
    # extraction.pages internally and flattens page.elements itself).
    ####################################################################

    LOGGER.info("Cleaning extracted text...")

    cleaned_document = cleaning.clean_elements(
        extraction
    )

    ####################################################################
    # Persistence
    #
    # Everything that touches the database for this document happens
    # inside a single transaction: document creation, paragraph
    # insertion, chunking's document_id assignment, glossary matching,
    # provenance, and FTS verification. This guarantees the connection
    # is always open for every call below, and that a failure at any
    # point rolls back the whole document rather than leaving partial
    # data behind.
    ####################################################################

    LOGGER.info("Persisting document...")

    with repository.transaction() as connection:

        document_id = repository.create_document(
            filename=pdf_path.name,
            title=document_metadata.title.value,
            plenary_session=document_metadata.plenary_session.value,
            year=document_metadata.year.value,
            date=document_metadata.date.value,
            location=document_metadata.location.value,
            source=str(pdf_path),
            page_count=extraction.page_count,
            connection=connection,
        )

        ################################################################
        # Stage 6 - Chunking
        ################################################################

        LOGGER.info("Chunking document...")

        paragraph_chunks = chunking.chunk_document(
            document_id=document_id,
            elements=cleaned_document,
        )

        if not paragraph_chunks:

            raise RuntimeError(
                f"No paragraphs produced for {pdf_path}"
            )

        ################################################################
        # Bulk paragraph insertion
        #
        # return_ids=True gives back (paragraph_id, text) pairs
        # generated by the database, so paragraph IDs used by the
        # glossary matcher are always real, persisted IDs -- no
        # separate paragraph_number -> paragraph_id remapping needed.
        ################################################################

        paragraph_rows = [
            (
                chunk.document_id,
                chunk.page_number,
                chunk.paragraph_number,
                chunk.text,
                chunk.chunk_method,
            )
            for chunk in paragraph_chunks
        ]

        paragraphs_for_glossary = repository.bulk_insert_paragraphs(
            paragraph_rows,
            return_ids=True,
            connection=connection,
        )

        ################################################################
        # Glossary matching
        #
        # index_paragraph_glossary_terms() loads terms.txt itself, so
        # it takes the Path directly (not a pre-loaded list). It also
        # inserts the resulting paragraph_terms rows itself and
        # returns the number of matches stored, not GlossaryMatch
        # objects -- so there is nothing further to insert here.
        ################################################################

        LOGGER.info("Matching glossary...")

        glossary_match_count = glossary.index_paragraph_glossary_terms(
            connection,
            paragraphs_for_glossary,
            terms_txt,
        )

        ################################################################
        # Metadata provenance
        ################################################################

        repository.insert_metadata_provenance(
            connection=connection,
            document_id=document_id,
            fields=metadata.metadata_provenance_fields(document_metadata),
        )

        ################################################################
        # Verify FTS index
        #
        # Normally SQLite triggers keep the index
        # synchronised automatically.
        #
        # If verification fails we rebuild before
        # committing the transaction.
        ################################################################

        if not repository.verify_fts_sync(
            connection=connection,
        ):

            LOGGER.warning(
                "FTS verification failed. "
                "Rebuilding index."
            )

            repository.rebuild_fts(
                connection=connection,
            )

            if not repository.verify_fts_sync(
                connection=connection,
            ):

                raise RuntimeError(
                    "Unable to rebuild FTS index."
                )

    LOGGER.info(
        "Finished ingesting '%s' (%d paragraphs)",
        pdf_path.name,
        len(paragraph_chunks),
    )

    return IngestionResult(
        document_id=document_id,
        paragraphs=len(paragraph_chunks),
        glossary_matches=glossary_match_count,
        updated=existing_document_id is not None,
        skipped=False,
    )


###############################################################################
# Batch ingestion
###############################################################################


def ingest_directory(
    directory: str | Path,
    *,
    terms_txt: str | Path,
    recursive: bool = True,
) -> list[IngestionResult]:
    """
    Ingest every PDF within a directory.

    Parameters
    ----------
    directory
        Root directory.

    terms_txt
        Path to glossary txt file.

    recursive
        Search subdirectories recursively.

    Returns
    -------
    list[IngestionResult]
        One result per processed document.
    """

    directory = Path(directory)

    if not directory.exists():

        raise FileNotFoundError(directory)

    pattern = "**/*.pdf" if recursive else "*.pdf"

    results: list[IngestionResult] = []

    for pdf in sorted(directory.glob(pattern)):

        try:

            results.append(
                ingest_document(
                    pdf,
                    terms_txt=terms_txt,
                )
            )

        except Exception:

            LOGGER.exception(
                "Failed ingesting %s",
                pdf,
            )

            raise

    return results


###############################################################################
# Convenience helpers
###############################################################################


def ingest_paths(
    paths: Iterable[str | Path],
    *,
    terms_txt: str | Path,
) -> list[IngestionResult]:
    """
    Ingest an iterable of PDF paths.

    Parameters
    ----------
    paths
        Collection of PDF files.

    terms_txt
        Glossary txt file.

    Returns
    -------
    list[IngestionResult]
    """

    results: list[IngestionResult] = []

    for path in paths:

        results.append(
            ingest_document(
                path,
                terms_txt=terms_txt,
            )
        )

    return results


def reindex_document(
    pdf_path: str | Path,
    *,
    terms_txt: str | Path,
) -> IngestionResult:
    """
    Force re-indexing of a document.

    Existing indexed content is removed regardless
    of whether the source document has changed.
    """

    pdf_path = Path(pdf_path)

    existing = repository.get_document_by_filename(
        pdf_path.name
    )

    if existing is not None:

        repository.delete_document(
            int(existing["id"])
        )

    return ingest_document(
        pdf_path,
        terms_txt=terms_txt,
    )


###############################################################################
# End of module
###############################################################################