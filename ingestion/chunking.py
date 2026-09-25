"""
chunking.py

Paragraph mapping.

Each source paragraph-like extracted element becomes one database paragraph,
except that consecutive small elements within the same section are merged
until they reach MIN_CHUNK_CHARACTERS. This avoids single, easily confused
sentences appearing back-to-back as separate search results.

The `paragraphs` table is the canonical representation of extracted
document structure. Larger RAG chunks should be generated separately.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Sequence

from ingestion.extractor import ExtractedElement

STORABLE_CATEGORIES = {"paragraph", "list", "table"}

MIN_CHUNK_CHARACTERS = 300


@dataclass(frozen=True)
class ParagraphChunk:
    """
    Database-compatible paragraph representation.
    """

    document_id: int
    section_index: int
    section_title: str | None
    paragraph_number: int
    text: str
    is_searchable: bool


def chunk_document(
    *,
    document_id: int,
    elements: Sequence[ExtractedElement],
    min_characters: int = MIN_CHUNK_CHARACTERS,
) -> list[ParagraphChunk]:
    """
    Convert extracted elements into database paragraphs, merging consecutive
    small paragraph/list elements within the same section until each stored
    row reaches min_characters. Tables are always stored on their own.
    """

    output: list[ParagraphChunk] = []
    counters: dict[int, int] = {}

    buffer_texts: list[str] = []
    buffer_section_index: int | None = None
    buffer_section_title: str | None = None
    buffer_is_searchable: bool | None = None

    def buffer_length() -> int:
        return sum(len(t) for t in buffer_texts)

    def store(section_index: int, section_title: str | None, text: str, is_searchable: bool) -> None:
        number = counters.get(section_index, 0) + 1
        counters[section_index] = number
        output.append(
            ParagraphChunk(
                document_id=document_id,
                section_index=section_index,
                section_title=section_title,
                paragraph_number=number,
                text=text,
                is_searchable=is_searchable,
            )
        )

    def flush(*, allow_merge_back: bool) -> None:
        nonlocal buffer_texts, buffer_section_index, buffer_section_title, buffer_is_searchable

        if not buffer_texts:
            return

        text = " ".join(buffer_texts)

        if (
            allow_merge_back
            and output
            and output[-1].section_index == buffer_section_index
            and output[-1].is_searchable == buffer_is_searchable
        ):
            output[-1] = replace(output[-1], text=f"{output[-1].text} {text}")
        else:
            store(buffer_section_index, buffer_section_title, text, buffer_is_searchable)

        buffer_texts = []
        buffer_section_index = None
        buffer_section_title = None
        buffer_is_searchable = None

    for element in elements:
        if element.category not in STORABLE_CATEGORIES:
            continue

        text = element.text.strip()
        if not text:
            continue

        if element.category == "table":
            # Never merge tables with surrounding text or with each other.
            flush(allow_merge_back=True)
            store(element.section_index, element.section_title, text, element.is_searchable)
            continue

        boundary_changed = buffer_texts and (
            element.section_index != buffer_section_index
            or element.is_searchable != buffer_is_searchable
        )
        if boundary_changed:
            flush(allow_merge_back=True)

        buffer_texts.append(text)
        buffer_section_index = element.section_index
        buffer_section_title = element.section_title
        buffer_is_searchable = element.is_searchable

        if buffer_length() >= min_characters:
            # Reached the target size on its own merit -- store as a new
            # paragraph rather than folding it into the previous one.
            flush(allow_merge_back=False)

    flush(allow_merge_back=True)

    return output