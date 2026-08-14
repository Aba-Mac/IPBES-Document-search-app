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

The module deliberately does not perform:

* OCR
* Text cleaning
* Chunking
* Topic tagging
* Database storage

Those belong to later pipeline stages.

"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from typing import Iterable
from typing import Optional

import fitz

from unstructured.documents.elements import Element
from unstructured.documents.elements import ListItem
from unstructured.documents.elements import NarrativeText
from unstructured.documents.elements import Table
from unstructured.documents.elements import Text
from unstructured.documents.elements import Title
from unstructured.partition.pdf import partition_pdf
from unstructured.chunking.title import chunk_by_title
from unstructured.documents.elements import CompositeElement, Table, TableChunk, ListItem, Title

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

    max_characters: int = 5000

    combine_text_under_n_chars: int = 400

    new_after_n_chars: int = 3500

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


def _element_category(
    element: Element,
) -> str:
    """
    Convert an Unstructured element into a canonical category.
    """

    if isinstance(element, Title):
        return "title"

    if isinstance(element, NarrativeText):
        return "paragraph"

    if isinstance(element, ListItem):
        return "list"

    if isinstance(element, Table):
        return "table"

    if isinstance(element, Text):
        return "text"

    return element.category.lower()


def _page_number(
    element: Element,
) -> int:
    """
    Read page number from Unstructured metadata.
    """

    metadata = getattr(element, "metadata", None)

    if metadata is None:
        return 1

    page = getattr(
        metadata,
        "page_number",
        None,
    )

    if page is None:
        return 1

    return int(page)


def _section_title(
    element: Element,
    current_section: str | None,
) -> str | None:
    """
    Determine section ownership.

    Titles become the active section until another
    title is encountered.
    """

    if isinstance(element, Title):

        text = element.text.strip()

        if text:

            return text

    return current_section


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
            "hi_res" if (pdf.inspection.needs_ocr or config.strategy == "hi_res") else "fast"
        )

        elements = partition_pdf(
            filename=str(pdf.processed_pdf),
            strategy=strategy,
            infer_table_structure=config.infer_table_structure,
            include_page_breaks=config.include_page_breaks,
            extract_images_in_pdf=config.extract_images,
        )

        chunks = chunk_by_title(
            elements,
            max_characters=config.max_characters,
            combine_text_under_n_chars=config.combine_text_under_n_chars,
            new_after_n_chars=config.new_after_n_chars,
            multipage_sections=False,
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
        text = (chunk.text or "").strip()
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
    #
    # Build raw page text from the ordered extracted elements.
    #
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


def iter_pages(
    document: ExtractedDocument,
) -> Iterable[ExtractedPage]:
    """
    Iterate over pages.
    """

    yield from document.pages


###############################################################################
# Shared utility functions
###############################################################################


def get_page(
    document: ExtractedDocument,
    page_number: int,
) -> ExtractedPage:
    """
    Retrieve a page by page number.

    Raises
    ------
    KeyError
        If the requested page does not exist.
    """

    for page in document.pages:

        if page.page_number == page_number:
            return page

    raise KeyError(
        f"Page {page_number} not present."
    )


def document_text(
    document: ExtractedDocument,
) -> str:
    """
    Return the document text in reading order.

    Page boundaries are preserved by blank lines.
    """

    return "\n\n".join(
        page.raw_text
        for page in document.pages
        if page.raw_text
    )


def section_titles(
    document: ExtractedDocument,
) -> list[str]:
    """
    Return unique section titles preserving order.
    """

    titles: list[str] = []
    seen: set[str] = set()

    for element in iter_elements(document):

        if (
            element.section_title
            and element.section_title not in seen
        ):
            titles.append(element.section_title)
            seen.add(element.section_title)

    return titles


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

###############################################################################
# Fallback orchestration helpers
###############################################################################

def _merge_metadata(
    primary: PDFMetadata,
    secondary: PDFMetadata,
) -> PDFMetadata:
    """
    Merge two metadata objects.

    Missing values from the primary source are filled using the
    secondary source.
    """

    return PDFMetadata(
        title=primary.title or secondary.title,
        author=primary.author or secondary.author,
        subject=primary.subject or secondary.subject,
        creator=primary.creator or secondary.creator,
        producer=primary.producer or secondary.producer,
        keywords=primary.keywords or secondary.keywords,
        creation_date=(
            primary.creation_date
            or secondary.creation_date
        ),
        modification_date=(
            primary.modification_date
            or secondary.modification_date
        ),
        page_count=max(
            primary.page_count,
            secondary.page_count,
        ),
    )


def enrich_document(
    document: ExtractedDocument,
    metadata: PDFMetadata,
) -> ExtractedDocument:
    """
    Replace incomplete metadata using an enriched metadata
    object.

    Returns
    -------
    ExtractedDocument
    """

    document.metadata = _merge_metadata(
        document.metadata,
        metadata,
    )

    return document


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
    "document_text",
    "enrich_document",
    "extract",
    "extract_document",
    "extract_document_metadata",
    "extract_with_pymupdf",
    "extract_with_unstructured",
    "extraction_statistics",
    "get_page",
    "iter_elements",
    "iter_pages",
    "section_titles",
    "validate_document",
]