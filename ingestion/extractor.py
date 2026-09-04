"""
extract.py
==========

Production-quality PDF extraction pipeline.

This module consumes the searchable PDF produced by ``ocr.py`` and
returns a unified internal representation regardless of whether the
original PDF was digital-native or OCR scanned.

Extraction strategy
-------------------

1. Read document metadata using PyMuPDF.
2. Attempt structured extraction with Unstructured
   (partition_pdf).
3. Preserve document hierarchy (titles, headings, narrative text,
   tables, lists).
4. Preserve original page numbers.
5. If Unstructured extraction fails or produces poor output,
   automatically fall back to PyMuPDF block extraction.
6. Return a common document model used by downstream cleaning,
   chunking and database ingestion.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from typing import Iterable

import fitz

from unstructured.documents.elements import Element
from unstructured.documents.elements import ListItem
from unstructured.documents.elements import Table
from unstructured.documents.elements import Title
from unstructured.partition.pdf import partition_pdf
from unstructured.chunking.title import chunk_by_title
from unstructured.documents.elements import Table, TableChunk, ListItem, Title
from ingestion.text_artifacts import (
    normalise_whitespace,
    remove_toc_artifacts,
    PAGE_NUMBER_PATTERN,
    STRAY_CHARACTER_PATTERN,
    detect_headers_and_footers,
)

from .ocr import OCRResult

logger = logging.getLogger(__name__)


###############################################################################
# Exceptions
###############################################################################


class ExtractionError(Exception):
    """Base extraction exception."""


class UnstructuredExtractionError(ExtractionError):
    """Raised when Unstructured extraction fails."""


class PyMuPDFExtractionError(ExtractionError):
    """Raised when PyMuPDF extraction fails."""


###############################################################################
# Configuration
###############################################################################


@dataclass(slots=True, frozen=True)
class ExtractionConfig:
    """
    Configuration for extraction.

    Parameters
    ----------
    infer_table_structure
        Enable table structure inference.

    strategy
        Unstructured extraction strategy.

    include_page_breaks
        Preserve page boundaries.

    max_characters
        Soft character limit for an extracted section.

    combine_text_under_n_chars
        Merge short adjacent elements.

    new_after_n_chars
        Split oversized sections.

    extract_images
        Enable image extraction.

    """

    infer_table_structure: bool = True

    strategy: str = "hi_res"

    include_page_breaks: bool = False

    combine_text_under_n_chars: int = 200

    extract_images: bool = False


###############################################################################
# Internal document model
###############################################################################


@dataclass(slots=True)
class PDFMetadata:
    """
    Document metadata.

    Additional metadata (session, year, location) will be
    enriched later during metadata parsing.
    """

    title: str | None = None

    author: str | None = None

    subject: str | None = None

    creator: str | None = None

    producer: str | None = None

    keywords: str | None = None

    creation_date: str | None = None

    modification_date: str |None = None

    page_count: int = 0


@dataclass(slots=True)
class ExtractedElement:
    """
    Canonical extracted element.
    """

    id: int

    page_number: int

    category: str

    text: str

    section_title: str | None

    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class ExtractedPage:
    """
    One extracted page.
    """

    page_number: int

    elements: list[ExtractedElement] = field(default_factory=list)

    raw_text: str = ""


@dataclass(slots=True)
class ExtractedDocument:
    """
    Canonical extraction result.

    Downstream modules only consume this object.
    """

    source_pdf: Path

    metadata: PDFMetadata

    pages: list[ExtractedPage]

    extraction_method: str

    warnings: list[str] = field(default_factory=list)

    @property
    def element_count(self) -> int:

        return sum(
            len(page.elements)
            for page in self.pages
        )

    @property
    def page_count(self) -> int:

        return len(self.pages)


###############################################################################
# Metadata helpers
###############################################################################


def extract_document_metadata(
    pdf_path: Path,
) -> PDFMetadata:
    """
    Read document metadata using PyMuPDF.
    """

    try:

        document = fitz.open(pdf_path)

    except Exception as exc:

        raise PyMuPDFExtractionError(
            f"Unable to open {pdf_path}"
        ) from exc

    metadata = document.metadata or {}

    result = PDFMetadata(
        title=metadata.get("title"),
        author=metadata.get("author"),
        subject=metadata.get("subject"),
        creator=metadata.get("creator"),
        producer=metadata.get("producer"),
        keywords=metadata.get("keywords"),
        creation_date=metadata.get("creationDate"),
        modification_date=metadata.get("modDate"),
        page_count=len(document),
    )

    document.close()

    return result


###############################################################################
# Unstructured conversion helpers
###############################################################################


def _page_number(
    element: Element,
) -> int:
    """
    Read page number from Unstructured metadata.
    """

    metadata = getattr(element, "metadata", None)

    if metadata is None:
        return 1

    orig_elements = getattr(metadata, "orig_elements", None)

    if orig_elements:
        for orig in orig_elements:
            orig_metadata = getattr(orig, "metadata", None)
            page = getattr(orig_metadata, "page_number", None)
            if page is not None:
                return int(page)

    else:
        page = getattr(
            metadata,
            "page_number",
            None,
        )

    if page is None:
        return 1

    return int(page)


def _strip_document_noise(elements: list[Element]) -> list[Element]:
    """
    Remove repeated headers/footers, standalone page numbers, and
    TOC-only elements from atomic Unstructured elements, BEFORE they
    get merged by chunk_by_title. Once merged into composite chunks,
    these patterns can no longer match reliably.
    """
    pairs = [
        (_page_number(el), normalise_whitespace(str(el.text or "")))
        for el in elements
    ]
    headers, footers = detect_headers_and_footers(pairs)

    kept: list[Element] = []
    for element, (_, norm_text) in zip(elements, pairs):
        raw_text = (element.text or "").strip()

        if not raw_text:
            continue
        if norm_text in headers or norm_text in footers:
            continue
        if PAGE_NUMBER_PATTERN.match(raw_text):
            continue
        if STRAY_CHARACTER_PATTERN.match(raw_text):
            continue
        if not remove_toc_artifacts(raw_text).strip():
            continue

        kept.append(element)

    return kept


###############################################################################
# Structured extraction
###############################################################################


def extract_with_unstructured(
    pdf: OCRResult,
    config: ExtractionConfig = ExtractionConfig(),
) -> ExtractedDocument:
    """
    Extract document using Unstructured.

    Returns a canonical document model.
    """

    logger.info(
        "Running Unstructured extraction."
    )

    try:

        strategy = (
            "hi_res" if (pdf.inspection.needs_ocr or config.strategy == "hi_res" or config.infer_table_structure)
            else "fast"
        )

        elements = partition_pdf(
            filename=str(pdf.processed_pdf),
            strategy=strategy,
            infer_table_structure=config.infer_table_structure,
            include_page_breaks=config.include_page_breaks,
            extract_images_in_pdf=config.extract_images,
        )

        elements = _strip_document_noise(elements)    

        chunks = chunk_by_title(
            elements,
            combine_text_under_n_chars=config.combine_text_under_n_chars,
            multipage_sections=True,
        )

    except Exception as exc:

        raise UnstructuredExtractionError(
            "partition_pdf failed."
        ) from exc

    metadata = extract_document_metadata(
        pdf.processed_pdf,
    )

    pages: dict[int, ExtractedPage] = {}

    current_section: str | None = None

    element_id = 1

    for chunk in chunks:
        text = _chunk_body_text(chunk)
        if not text:
            continue

        current_section = _chunk_section_title(chunk, current_section)
        page_number = _page_number(chunk)

        if page_number not in pages:
            pages[page_number] = ExtractedPage(page_number=page_number)

        pages[page_number].elements.append(
            ExtractedElement(
                id=element_id,
                page_number=page_number,
                category=_chunk_category(chunk),
                text=text,
                section_title=current_section,
                metadata={"coordinates": getattr(chunk.metadata, "coordinates", None)},
            )
        )

        element_id += 1

    for page in pages.values():

        page.raw_text = "\n\n".join(
            element.text
            for element in page.elements
            if element.text.strip()
        )

    document = ExtractedDocument(
        source_pdf=pdf.processed_pdf,
        metadata=metadata,
        pages=[
            pages[number]
            for number in sorted(pages)
        ],
        extraction_method="unstructured",
    )

    logger.info(
        "Unstructured extraction completed "
        "(pages=%d, elements=%d).",
        document.page_count,
        document.element_count,
    )

    return document


###############################################################################
# Quality assessment helpers
###############################################################################


def document_has_content(
    document: ExtractedDocument,
    *,
    minimum_elements: int = 5,
    minimum_characters: int = 500,
) -> bool:
    """
    Determine whether an extracted document contains a useful amount
    of structured content.

    Parameters
    ----------
    document
        Extracted document.

    minimum_elements
        Minimum acceptable number of extracted elements.

    minimum_characters
        Minimum total text length.

    Returns
    -------
    bool
    """

    if document.element_count < minimum_elements:
        return False

    character_count = sum(
        len(element.text)
        for page in document.pages
        for element in page.elements
    )

    return character_count >= minimum_characters


def iter_elements(
    document: ExtractedDocument,
) -> Iterable[ExtractedElement]:
    """
    Iterate through every extracted element in reading order.
    """

    for page in document.pages:

        yield from page.elements


###############################################################################
# PyMuPDF extraction
###############################################################################

def _block_category(
    block: dict,
) -> str:
    """
    Infer a canonical category for a PyMuPDF text block.

    PyMuPDF does not provide semantic labels comparable to
    Unstructured. This heuristic classifies blocks using font
    information and layout characteristics.
    """

    lines = block.get("lines", [])

    if not lines:
        return "text"

    max_size = 0.0
    is_bold = False

    for line in lines:

        for span in line.get("spans", []):

            max_size = max(
                max_size,
                float(span.get("size", 0.0)),
            )

            font = span.get("font", "").lower()

            if (
                "bold" in font
                or "black" in font
                or "heavy" in font
            ):
                is_bold = True

    if is_bold and max_size >= 14:
        return "title"

    if is_bold:
        return "heading"

    return "paragraph"


def _extract_block_text(
    block: dict,
) -> str:
    """
    Convert a PyMuPDF text block into plain text.
    """

    paragraphs: list[str] = []

    for line in block.get("lines", []):

        spans = []

        for span in line.get("spans", []):

            text = span.get("text", "")

            if text:
                spans.append(text)

        line_text = "".join(spans).strip()

        if line_text:

            paragraphs.append(line_text)

    return "\n".join(paragraphs).strip()


def _iter_text_blocks(
    page: fitz.Page,
) -> Iterable[dict]:
    """
    Yield text blocks only.

    Image blocks are ignored because OCR has already converted
    scanned pages into searchable text.
    """

    page_dict = page.get_text("dict")

    for block in page_dict.get("blocks", []):

        if block.get("type") == 0:

            yield block


def extract_with_pymupdf(
    pdf: OCRResult,
) -> ExtractedDocument:
    """
    Extract document using PyMuPDF only.

    This serves as the fallback extraction path whenever
    Unstructured fails or produces insufficient output.
    """

    logger.info(
        "Running PyMuPDF extraction."
    )

    try:

        document = fitz.open(
            pdf.processed_pdf,
        )

    except Exception as exc:

        raise PyMuPDFExtractionError(
            "Unable to open searchable PDF."
        ) from exc

    metadata = extract_document_metadata(
        pdf.processed_pdf,
    )

    pages: list[ExtractedPage] = []

    current_section: str | None = None

    element_id = 1

    for page in document:

        extracted_page = ExtractedPage(
            page_number=page.number + 1,
        )

        raw_blocks: list[str] = []

        for block in _iter_text_blocks(page):

            text = _extract_block_text(block)

            if not text:

                continue

            category = _block_category(block)

            if category in (
                "title",
                "heading",
            ):

                current_section = text

            bbox = block.get("bbox")

            extracted_page.elements.append(
                ExtractedElement(
                    id=element_id,
                    page_number=page.number + 1,
                    category=category,
                    text=text,
                    section_title=current_section,
                    metadata={
                        "bbox": bbox,
                        "source": "pymupdf",
                    },
                )
            )

            raw_blocks.append(text)

            element_id += 1

        extracted_page.raw_text = (
            "\n\n".join(raw_blocks)
        )

        pages.append(extracted_page)

    document.close()

    extracted = ExtractedDocument(
        source_pdf=pdf.processed_pdf,
        metadata=metadata,
        pages=pages,
        extraction_method="pymupdf",
    )

    logger.info(
        "PyMuPDF extraction completed "
        "(pages=%d, elements=%d).",
        extracted.page_count,
        extracted.element_count,
    )

    return extracted


def _chunk_category(chunk) -> str:
    if isinstance(chunk, (Table, TableChunk)):
        return "table"

    orig = getattr(chunk.metadata, "orig_elements", None) or []
    if orig and all(isinstance(e, ListItem) for e in orig):
        return "list"

    return "paragraph"


def _chunk_section_title(chunk, current_section):
    orig = getattr(chunk.metadata, "orig_elements", None) or []
    for element in orig:
        if isinstance(element, Title) and element.text.strip():
            current_section = element.text.strip()
    return current_section


def _chunk_body_text(chunk) -> str:
    """
    Reconstruct chunk text excluding the Title element.

    chunk_by_title concatenates every constituent element's text,
    including the Title that opens the section — which we already
    store separately as section_title. Left in, it duplicates the
    title inside every paragraph body.
    """
    orig = getattr(chunk.metadata, "orig_elements", None)
    if not orig:
        return (chunk.text or "").strip()

    body_parts = [
        str(element.text).strip()
        for element in orig
        if not isinstance(element, Title) and str(element.text or "").strip()
    ]

    if not body_parts:
        return (chunk.text or "").strip()

    return "\n\n".join(body_parts)


###############################################################################
# Extraction orchestration
###############################################################################

def extract_document(
    pdf: OCRResult,
    config: ExtractionConfig = ExtractionConfig(),
) -> ExtractedDocument:
    """
    Extract a searchable PDF into the canonical internal
    representation.

    Extraction strategy
    -------------------
    1. Attempt structured extraction using Unstructured.
    2. Validate extraction quality.
    3. Automatically fall back to PyMuPDF if required.
    4. Return a unified document representation.

    Parameters
    ----------
    pdf
        Result returned from ``ensure_searchable_pdf()``.

    config
        Extraction configuration.

    Returns
    -------
    ExtractedDocument
    """

    logger.info(
        "Beginning extraction for %s",
        pdf.processed_pdf,
    )

    fallback_reason: str | None = None

    try:

        structured = extract_with_unstructured(
            pdf=pdf,
            config=config,
        )

        if document_has_content(structured):

            logger.info(
                "Using Unstructured extraction."
            )

            return structured

        fallback_reason = (
            "Structured extraction produced "
            "insufficient content."
        )

        logger.warning(fallback_reason)

    except Exception as exc:

        fallback_reason = str(exc)

        logger.exception(
            "Structured extraction failed."
        )

    logger.info(
        "Falling back to PyMuPDF extraction."
    )

    fallback = extract_with_pymupdf(pdf)

    if fallback_reason:

        fallback.warnings.append(fallback_reason)

    return fallback


###############################################################################
# Validation helpers
###############################################################################


def validate_document(
    document: ExtractedDocument,
) -> None:
    """
    Validate an extracted document.

    Raises
    ------
    ExtractionError
        If the extracted document is structurally invalid.
    """

    if document.page_count == 0:

        raise ExtractionError(
            "Extracted document contains no pages."
        )

    if document.element_count == 0:

        raise ExtractionError(
            "Extracted document contains no elements."
        )

    seen_pages: set[int] = set()

    for page in document.pages:

        if page.page_number in seen_pages:

            raise ExtractionError(
                f"Duplicate page number {page.page_number}."
            )

        seen_pages.add(page.page_number)

        for element in page.elements:

            if not element.text:

                raise ExtractionError(
                    "Encountered empty extracted element."
                )


###############################################################################
# Statistics
###############################################################################


def extraction_statistics(
    document: ExtractedDocument,
) -> dict[str, object]:
    """
    Produce extraction statistics for logging and diagnostics.
    """

    category_counts: dict[str, int] = {}

    character_count = 0

    for element in iter_elements(document):

        character_count += len(element.text)

        category_counts[element.category] = (
            category_counts.get(element.category, 0)
            + 1
        )

    return {
        "pages": document.page_count,
        "elements": document.element_count,
        "characters": character_count,
        "method": document.extraction_method,
        "categories": category_counts,
    }


###############################################################################
# Convenience API
###############################################################################


def extract(
    pdf: OCRResult,
    config: ExtractionConfig = ExtractionConfig(),
) -> ExtractedDocument:
    """
    Public extraction entry point.

    This is the only function that downstream ingestion modules
    should call.
    """

    document = extract_document(
        pdf=pdf,
        config=config,
    )

    validate_document(document)

    logger.info(
        "Extraction finished successfully."
    )

    logger.debug(
        "Statistics: %s",
        extraction_statistics(document),
    )

    return document


###############################################################################
# Module exports
###############################################################################

__all__ = [
    "PDFMetadata",
    "ExtractedDocument",
    "ExtractedElement",
    "ExtractedPage",
    "ExtractionConfig",
    "ExtractionError",
    "PyMuPDFExtractionError",
    "UnstructuredExtractionError",
    "document_has_content",
    "extract",
    "extract_document",
    "extract_document_metadata",
    "extract_with_pymupdf",
    "extract_with_unstructured",
    "extraction_statistics",
    "iter_elements",
    "validate_document",
]