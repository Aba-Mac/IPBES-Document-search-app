"""
chunking.py

Paragraph mapping: one storable element becomes one database paragraph.
paragraph_number counts within its section (restarts at 1 under each heading).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from ingestion.extractor import ExtractedElement

from dataclasses import dataclass, replace

STORABLE_CATEGORIES = {"paragraph", "list", "table"}

MIN_CHUNK_CHARS = 60


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
    pending: list[ExtractedElement] = []

    def emit(section_index, section_title, text, is_searchable) -> None:
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

    def flush_pending() -> None:
        """Attach leftover short fragments to the previous chunk in the same section."""
        nonlocal pending
        if not pending:
            return
        first = pending[0]
        text = " | ".join(e.text.strip() for e in pending)
        if output and output[-1].section_index == first.section_index:
            prev = output[-1]
            output[-1] = replace(prev, text=prev.text + " | " + text)
        else:
            # Nothing earlier in this section to attach to: keep as its own chunk.
            emit(first.section_index, first.section_title, text, first.is_searchable)
        pending = []

    for element in elements:
        if element.category not in STORABLE_CATEGORIES:
            continue
        text = element.text.strip()
        if not text:
            continue

        # Section changed: leftover fragments belong to the old section.
        if pending and element.section_index != pending[0].section_index:
            flush_pending()

        if len(text) < MIN_CHUNK_CHARS:
            pending.append(element)
            continue

        if pending:
            text = " | ".join(e.text.strip() for e in pending) + " | " + text
            pending = []

        emit(
            element.section_index,
            element.section_title,
            text,
            element.is_searchable,
        )

    flush_pending()
    return output