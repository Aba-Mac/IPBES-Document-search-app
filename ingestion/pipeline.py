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
from typing import Sequence

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
# Pipeline
###############################################################################


def ingest_document(
    pdf_path: str | Path,
    *,
    terms_csv: str | Path,
) -> IngestionResult:
    """
    Run the complete ingestion pipeline.

    Parameters
    ----------
    pdf_path

        PDF document.

    terms_csv

        Path to glossary CSV.

    Returns
    -------
    IngestionResult

    Notes
    -----
    Tagging and embeddings are intentionally excluded.

    Repository transactions guarantee consistency.
    """

    pdf_path = Path(pdf_path)

    terms_csv = Path(terms_csv)

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
    # Stage 1
    ####################################################################

    LOGGER.info("Running OCR...")

    ocr_result = ocr.ensure_searchable_pdf(pdf_path)

    ####################################################################
    # Stage 2
    ####################################################################

    LOGGER.info("Extracting document...")

    extraction = extractor.extract(ocr_result)

    ####################################################################
    # Stage 3
    ####################################################################

    LOGGER.info("Cleaning extracted text...")

    cleaned_document = cleaning.clean_document(
        extraction
    )

    ####################################################################
    # Stage 4
    ####################################################################

    LOGGER.info("Chunking document...")

    paragraph_chunks = chunking.chunk_document(
        cleaned_document
    )

    if not paragraph_chunks:

        raise RuntimeError(
            f"No paragraphs produced for {pdf_path}"
        )

    ####################################################################
    # Stage 5
    ####################################################################

    LOGGER.info("Extracting metadata...")

    document_metadata = metadata.build_metadata(
        pdf_path=ocr_result.processed_pdf,
        extraction=extraction,
    )

    ####################################################################
    # Stage 6
    ####################################################################

    LOGGER.info("Loading glossary...")

    glossary_terms = glossary.load_terms_csv(
        terms_csv
    )

    LOGGER.info("Matching glossary...")

    glossary_matches = glossary.match_document(
        paragraphs=paragraph_chunks,
        glossary_terms=glossary_terms,
    )

    ####################################################################
    # Persistence
    ####################################################################

    LOGGER.info(
        "Persisting document..."
    )

    with repository.transaction() as connection:

        #
        # Load glossary once.
        #
        # ON CONFLICT inside repository prevents duplicates.
        #

        repository.bulk_insert_terms(
            (
                (
                    term.term,
                    term.category,
                )
                for term in glossary_terms
            ),
            connection=connection,
        )

        document_id = repository.create_document(
            filename=pdf_path.name,
            title=document_metadata.title.value,
            plenary_session=document_metadata.plenary_session.value,
            year=document_metadata.year.value,
            date=document_metadata.date.value,
            location=document_metadata.location.value,
            source=document_metadata.source.value,
            page_count=document_metadata.page_count.value,
            connection=connection,
        )

        #
        # Metadata provenance
        #

        if hasattr(
            document_metadata,
            "provenance",
        ):

            repository.insert_metadata_provenance(
                connection=connection,
                document_id=document_id,
                fields=metadata.metadata_provenance_fields(
                    document_metadata
                ),
            )

        ################################################################
        # Bulk paragraph insertion
        ################################################################

        paragraph_rows: list[
            tuple[
                int,
                int,
                int,
                str,
                str,
            ]
        ] = []

        for paragraph_number, chunk in enumerate(
            paragraph_chunks,
            start=1,
        ):

            paragraph_rows.append(
                (
                    document_id,
                    chunk.page_number,
                    paragraph_number,
                    chunk.text,
                    chunk.chunk_method,
                )
            )

        repository.bulk_insert_paragraphs(
            paragraph_rows,
            connection=connection,
        )

        ################################################################
        # Retrieve generated paragraph IDs.
        #
        # Paragraphs are returned ordered exactly as inserted.
        ################################################################

        stored_paragraphs = repository.get_document_paragraphs(
            document_id,
            connection=connection,
        )

        if len(stored_paragraphs) != len(paragraph_chunks):

            raise RuntimeError(
                "Paragraph persistence failed. "
                "Inserted paragraph count does not match "
                "chunk count."
            )

        #
        # Map chunk number -> paragraph id
        #

        paragraph_id_lookup: dict[int, int] = {
            row["paragraph_number"]: row["id"]
            for row in stored_paragraphs
        }

        ################################################################
        # Build glossary lookup
        ################################################################

        term_lookup = {
            row["term"]: row["id"]
            for row in repository.list_terms(
                connection=connection,
            )
        }

        ################################################################
        # Build paragraph_terms rows
        ################################################################

        paragraph_term_rows: list[
            tuple[
                int,
                int,
                int,
            ]
        ] = []

        for match in glossary_matches:

            paragraph_id = paragraph_id_lookup[
                match.paragraph_number
            ]

            term_id = term_lookup.get(
                match.term
            )

            if term_id is None:

                LOGGER.warning(
                    "Glossary term '%s' missing "
                    "from terms table.",
                    match.term,
                )

                continue

            paragraph_term_rows.append(
                (
                    paragraph_id,
                    term_id,
                    match.occurrence_count,
                )
            )

        if paragraph_term_rows:

            repository.bulk_insert_paragraph_terms(
                paragraph_term_rows,
                connection=connection,
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
        glossary_matches=len(
            paragraph_term_rows
        ),
        updated=existing_document_id is not None,
        skipped=False,
    )


###############################################################################
# Batch ingestion
###############################################################################


def ingest_directory(
    directory: str | Path,
    *,
    terms_csv: str | Path,
    recursive: bool = True,
) -> list[IngestionResult]:
    """
    Ingest every PDF within a directory.

    Parameters
    ----------
    directory
        Root directory.

    terms_csv
        Path to glossary CSV.

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
                    terms_csv=terms_csv,
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
    terms_csv: str | Path,
) -> list[IngestionResult]:
    """
    Ingest an iterable of PDF paths.

    Parameters
    ----------
    paths
        Collection of PDF files.

    terms_csv
        Glossary CSV.

    Returns
    -------
    list[IngestionResult]
    """

    results: list[IngestionResult] = []

    for path in paths:

        results.append(
            ingest_document(
                path,
                terms_csv=terms_csv,
            )
        )

    return results


def reindex_document(
    pdf_path: str | Path,
    *,
    terms_csv: str | Path,
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
        terms_csv=terms_csv,
    )


###############################################################################
# End of module
###############################################################################