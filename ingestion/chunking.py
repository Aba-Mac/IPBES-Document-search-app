"""
Paragraph mapping.

Each source paragraph-like extracted element becomes one database
paragraph. This module deliberately does not perform arbitrary
character-based chunking.

The `paragraphs` table is the canonical representation of extracted
document structure. Larger RAG chunks should be generated separately.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Sequence

from ingestion.cleaning import CleanedElement

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ParagraphChunk:
    """
    Database-compatible paragraph representation.
    """

    document_id: int
    page_number: int
    paragraph_number: int
    text: str
    chunk_method: str


STORABLE_CATEGORIES = {
    "paragraph",
    "list",
    "table",
}


def chunk_document(
    *,
    document_id: int,
    elements: Sequence[CleanedElement],
) -> list[ParagraphChunk]:
    """
    Convert cleaned extracted elements into database paragraphs.

    One source element becomes one database paragraph.

    Titles and headings are retained as section metadata but are not
    stored as paragraphs unless their category is explicitly included
    in STORABLE_CATEGORIES.
    """

    output: list[ParagraphChunk] = []
    page_counters: dict[int, int] = {}

    for element in elements:

        if element.category not in STORABLE_CATEGORIES:
            continue

        text = element.text.strip()

        if not text:
            continue

        page = element.page_number
        page_counters[page] = page_counters.get(page, 0) + 1
        paragraph_number = page_counters[page]

        output.append(
            ParagraphChunk(
                document_id=document_id,
                page_number=page,
                paragraph_number=paragraph_number,
                text=text,
                chunk_method="extracted_element",
            )
        )

        # --- log if elements arrived out of page order -------------------
    if len(page_counters) > 1:
        pages_seen = [
            el.page_number
            for el in elements
            if el.category in STORABLE_CATEGORIES and el.text.strip()
        ]
        if pages_seen != sorted(pages_seen):
            logger.warning(
                "Non-monotonic page order detected during chunking for document_id=%s",
                document_id,
            )

    # --- return in reading order --------------------------------------
    return sorted(output, key=lambda p: (p.page_number, p.paragraph_number))