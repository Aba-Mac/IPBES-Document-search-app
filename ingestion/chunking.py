"""
chunking.py

Paragraph mapping: one storable element becomes one database paragraph.
paragraph_number counts within its section (restarts at 1 under each heading).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from ingestion.extractor import ExtractedElement

STORABLE_CATEGORIES = {"paragraph", "list", "table"}


@dataclass(frozen=True)
class ParagraphChunk:
    document_id: int
    section_index: int
    section_title: str | None
    paragraph_number: int
    text: str
    is_searchable: bool


def chunk_document(
    *, document_id: int, elements: Sequence[ExtractedElement]
) -> list[ParagraphChunk]:
    counters: dict[int, int] = {}
    output: list[ParagraphChunk] = []

    for element in elements:
        if element.category not in STORABLE_CATEGORIES:
            continue
        text = element.text.strip()
        if not text:
            continue

        number = counters.get(element.section_index, 0) + 1
        counters[element.section_index] = number

        output.append(
            ParagraphChunk(
                document_id=document_id,
                section_index=element.section_index,
                section_title=element.section_title,
                paragraph_number=number,
                text=text,
                is_searchable=element.is_searchable,
            )
        )
    return output