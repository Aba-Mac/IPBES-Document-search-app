"""
extractor.py

DOCX extraction. Returns a flat, ordered list of elements, each tagged with
the heading it sits under and an is_searchable flag from section_lookup.csv.
Everything is extracted; the flag is only applied at result retrieval.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from docx import Document
from docx.document import Document as DocumentType
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table, _Cell
from docx.text.paragraph import Paragraph

from ingestion.metadata import SectionLookup

logger = logging.getLogger(__name__)


class ExtractionError(Exception):
    """Base extraction exception."""


class DocxExtractionError(ExtractionError):
    """Raised when a DOCX cannot be opened or parsed."""


@dataclass(slots=True)
class ExtractedElement:
    category: str
    text: str
    section_title: str | None
    section_index: int
    is_searchable: bool

@dataclass(slots=True)
class ExtractedDocument:
    source_docx: Path
    elements: list[ExtractedElement]

    @property
    def element_count(self) -> int:
        return len(self.elements)


def _iter_block_items(parent: DocumentType | _Cell) -> Iterable[Paragraph | Table]:
    """Yield body blocks in document order, including tables."""
    parent_element = parent.element.body if isinstance(parent, DocumentType) else parent._tc
    for child in parent_element.iterchildren():
        if isinstance(child, CT_P):
            yield Paragraph(child, parent)
        elif isinstance(child, CT_Tbl):
            yield Table(child, parent)


def _normalise(text: str) -> str:
    return " ".join(text.split()).strip()


def _paragraph_category(paragraph: Paragraph) -> str:
    style = (paragraph.style.name if paragraph.style else "").lower()
    if "title" in style:
        return "title"
    if "heading" in style:
        return "heading"
    if "list" in style:
        return "list"
    return "paragraph"


def _heading_level(paragraph: Paragraph) -> int | None:
    style = (paragraph.style.name if paragraph.style else "").strip()
    match = re.fullmatch(r"Heading\s+(\d+)", style, flags=re.IGNORECASE)
    return int(match.group(1)) if match else None


def _table_text(table: Table) -> str:
    rows = []
    for row in table.rows:
        cells = [_normalise(cell.text) for cell in row.cells]
        if any(cells):
            rows.append(" | ".join(cells))
    return "\n".join(rows)


def extract_docx(docx_path: str | Path, lookup: SectionLookup) -> ExtractedDocument:
    path = Path(docx_path)

    try:
        document = Document(path)
    except Exception as exc:
        raise DocxExtractionError(f"Unable to open DOCX: {path}") from exc

    elements: list[ExtractedElement] = []
    current_section: str | None = None
    section_index = 0
    active_scope_levels: list[int] = []
    include_all = lookup.includes_all(path.name)

    for block in _iter_block_items(document):
        if isinstance(block, Paragraph):
            text = block.text.strip()
            category = _paragraph_category(block)
        else:
            text = _table_text(block).strip()
            category = "table"

        if not text:
            continue

        if category in {"title", "heading"}:
            current_section = text
            section_index += 1

        if category == "heading":
            level = _heading_level(block)
            if level is None:
                logger.warning(
                    "Ignoring unrecognised heading style %r in %s",
                    block.style.name, path.name,
                )
            else:
                active_scope_levels = [l for l in active_scope_levels if l < level]
                if lookup.matches_heading(path.name, text):
                    active_scope_levels.append(level)

        elements.append(
            ExtractedElement(
                category=category,
                text=text,
                section_title=current_section,
                section_index=section_index,
                is_searchable=include_all or bool(active_scope_levels)
            )
        )

    if not elements:
        raise ExtractionError(f"No content extracted from {path.name}")

    logger.info("Extracted %d elements from %s", len(elements), path.name)
    return ExtractedDocument(source_docx=path, elements=elements)


def extraction_statistics(document: ExtractedDocument) -> dict[str, object]:
    counts: dict[str, int] = {}
    for element in document.elements:
        counts[element.category] = counts.get(element.category, 0) + 1
    return {
        "elements": document.element_count,
        "characters": sum(len(e.text) for e in document.elements),
        "categories": counts,
    }