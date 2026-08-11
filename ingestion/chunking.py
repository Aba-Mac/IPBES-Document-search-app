"""
Paragraph mapping.

Each source paragraph-like extracted element becomes one database
paragraph. This module deliberately does not perform arbitrary
character-based chunking.

The `paragraphs` table is the canonical representation of extracted
document structure. Larger RAG chunks should be generated separately.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from ingestion.cleaning import CleanedElement


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

    paragraph_number = 1

    for element in elements:

        if element.category not in STORABLE_CATEGORIES:
            continue

        text = element.text.strip()

        if not text:
            continue

        output.append(
            ParagraphChunk(
                document_id=document_id,
                page_number=element.page_number,
                paragraph_number=paragraph_number,
                text=text,
                chunk_method="extracted_element",
            )
        )

        paragraph_number += 1

    return output