"""
ingestion/pipeline.py

Document ingestion orchestration.

This module coordinates the complete ingestion workflow for a document.
It deliberately contains no document-processing logic itself; instead it
calls the specialised ingestion modules in sequence and persists the
result through database.repository.

Pipeline
--------
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


def calculate_file_hash(path: Path, salt: str = "") -> str:
    """
    Calculate a SHA-256 hash for a document.

    The hash is used to determine whether an existing
    indexed document has changed since the previous
    ingestion.

    Parameters
    ----------
    path
        DOCX path.

    Returns
    -------
    str
        Hex digest.
    """

    digest = hashlib.sha256(salt.encode())
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


###############################################################################
# Incremental indexing
###############################################################################


def needs_reindex(
    docx_path: Path,
    salt = "",
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

    filename = docx_path.name

    current_hash = calculate_file_hash(docx_path, salt)

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
    docx_path: str | Path,
    *,
    matcher: glossary.GlossaryMatcher,
    lookup: metadata.SectionLookup,
) -> IngestionResult:
    """
    Run the complete ingestion pipeline.

    Parameters
    ----------
    docx_path

        DOCX document.

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

    docx_path = Path(docx_path)
    name = docx_path.name

    LOGGER.info(
        "Beginning ingestion: %s",
        name,
    )

    meta = lookup.metadata_for(name)
    if meta is None:
        raise ValueError(f"{name} has no row in document_metadata.csv")

    salt = repr((
        sorted(lookup.headings.get(name, ())),
        name in lookup.include_all,
        lookup.doi_for(name),
        meta,
    ))
    should_index, existing_id, current_hash = needs_reindex(docx_path, salt)

    if not should_index:
        return IngestionResult(
            document_id=existing_id, paragraphs=0, glossary_matches=0, skipped=True
        )
    if existing_id is not None:
        repository.delete_document(existing_id)

    extraction = extractor.extract_docx(docx_path, lookup=lookup)
    elements = cleaning.clean_elements(extraction)

    with repository.transaction() as connection:
        document_id = repository.create_document(
            filename=name,
            title=meta["title"],
            doi=lookup.doi_for(name),
            year=meta["year"],
            date=meta["date"],
            location=meta["location"],
            source=str(docx_path),
            source_hash=current_hash,
            connection=connection,
        )

        chunks = chunking.chunk_document(document_id=document_id, elements=elements)
        if not chunks:
            raise RuntimeError(f"No paragraphs produced for {docx_path}")

        rows = [
            (c.document_id, c.section_index, c.section_title, c.paragraph_number,
            c.text, int(c.is_searchable))
            for c in chunks
        ]
        paragraphs_for_glossary = repository.bulk_insert_paragraphs(
            rows, connection=connection
        )
        glossary_match_count = glossary.index_paragraph_glossary_terms(
            connection, paragraphs_for_glossary, matcher
        )

    LOGGER.info("Finished ingesting '%s' (%d paragraphs)", name, len(chunks))
    return IngestionResult(
        document_id=document_id,
        paragraphs=len(chunks),
        glossary_matches=glossary_match_count,
        updated=existing_id is not None,
    )


###############################################################################
# Batch ingestion
###############################################################################


def ingest_directory(
    directory: str | Path,
    *,
    glossary_sources: dict[str, Path],
    lookup_path: str | Path,
    metadata_path: str | Path,
    recursive: bool = True,
) -> list[IngestionResult]:
    lookup = metadata.load_section_lookup(lookup_path, metadata_path)

    directory = Path(directory)
    if not directory.exists():
        raise FileNotFoundError(directory)

    with repository.transaction() as connection:
        matcher = glossary.build_matcher(connection, glossary_sources)

    pattern = "**/*.docx" if recursive else "*.docx"
    results: list[IngestionResult] = []

    for docx in sorted(directory.glob(pattern)):
        try:
            results.append(
                ingest_document(docx, matcher=matcher, lookup=lookup)
            )
        except Exception:
            LOGGER.exception("Failed ingesting %s", docx)
            raise

    return results