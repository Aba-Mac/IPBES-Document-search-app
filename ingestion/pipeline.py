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

from database import repository

from ingestion import cleaning
from ingestion import chunking
from ingestion import extractor
from ingestion import glossary
from ingestion import metadata
from ingestion import ocr
from ingestion import doi_lookup

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
) -> tuple[bool, int | None, str]:
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

    current_hash = calculate_file_hash(pdf_path)

    existing = repository.get_document_by_filename(filename)

    if existing is None:

        return True, None, current_hash

    existing_hash = existing["source_hash"] if "source_hash" in existing.keys() else None

    if existing_hash is None:

        LOGGER.info(
            "No stored hash for '%s' — re-indexing to establish one.",
            filename,
        )
        return True, int(existing["id"]), current_hash

    if existing_hash == current_hash:
        LOGGER.info("Skipping unchanged document: %s", filename)
        return False, int(existing["id"]), current_hash

    LOGGER.info("Detected updated document: %s", filename)
    return True, int(existing["id"]), current_hash


###############################################################################
# Pipeline
###############################################################################


def ingest_document(
    pdf_path: str | Path,
    *,
    glossary_sources: dict[str, Path],
    doi_map: dict[str,str] | None = None,
) -> IngestionResult:
    """
    Run the complete ingestion pipeline.

    Parameters
    ----------
    pdf_path

        PDF document.

    glossary_sources

        2 glossary term lists.

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

    LOGGER.info(
        "Beginning ingestion: %s",
        pdf_path.name,
    )

    should_index, existing_document_id, current_hash = needs_reindex(
        pdf_path
    )

    if not should_index:

        return IngestionResult(
            document_id=existing_document_id,
            paragraphs=0,
            glossary_matches=0,
            skipped=True,
        )

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
            doi=(doi_map or {}).get(pdf_path.name),
            plenary_session=document_metadata.plenary_session.value,
            year=document_metadata.year.value,
            date=document_metadata.date.value,
            location=document_metadata.location.value,
            source=str(pdf_path),
            source_hash=current_hash,
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
        ################################################################

        LOGGER.info("Matching glossary...")

        glossary_match_count = glossary.index_paragraph_glossary_terms(
            connection,
            paragraphs_for_glossary,
            glossary_sources,
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
    glossary_sources: dict[str, Path], 
    doi_map: str | Path | None = None,
    recursive: bool = True,
) -> list[IngestionResult]:
    """
    Ingest every PDF within a directory.

    Parameters
    ----------
    directory
        Root directory.

    glossary_sources
        Path to 2 glossary txt files.

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

    doi_map = doi_lookup.load_doi_map(Path(doi_map)) if doi_map else {}

    pattern = "**/*.pdf" if recursive else "*.pdf"

    results: list[IngestionResult] = []

    for pdf in sorted(directory.glob(pattern)):

        try:

            results.append(
                ingest_document(
                    pdf,
                    glossary_sources=glossary_sources,
                    doi_map=doi_map,
                )
            )

        except Exception:

            LOGGER.exception(
                "Failed ingesting %s",
                pdf,
            )

            raise

    return results