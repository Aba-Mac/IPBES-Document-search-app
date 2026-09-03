"""
Text cleaning utilities for extracted PDF content.

This module is designed to run after extraction with Unstructured and before
chunking. It preserves paragraph and section boundaries while cleaning common
PDF/OCR artefacts.

Responsibilities:
    - repair encoding issues with ftfy
    - remove repeated headers and footers
    - remove standalone page numbers
    - strip OCR dot leaders
    - remove table-of-contents artefacts
    - remove stray OCR characters
    - normalise whitespace
    - preserve paragraph and section structure

The module operates on lists of paragraph-like objects rather than raw text
where possible, because Unstructured elements contain semantic information
such as titles and narrative text.

Example:

    cleaned_elements = clean_elements(elements)

Each element is expected to expose:
    - text attribute
    - category attribute (optional)

or alternatively behave like a dictionary with:
    - "text"
    - "category"
"""

from __future__ import annotations


from dataclasses import dataclass
from ingestion.extractor import ExtractedDocument, ExtractedElement
from unstructured.documents.elements import (
    NarrativeText,
    Title,
    ListItem,
    Text,
    )
from ingestion.text_artifacts import (
    normalise_whitespace,
    strip_dot_leaders,
    remove_toc_artifacts,
    remove_stray_characters,
    detect_headers_and_footers as _detect_headers_and_footers_generic,
    PAGE_NUMBER_PATTERN,
    PRINTED_PAGE_NUMBER_PATTERN,
)

import ftfy


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class CleanedElement:
    text: str
    category: str
    page_number: int
    section_title: str | None = None

    def to_unstructured(self):
        if self.category == "title":
            return Title(
                text=self.text
            )
        if self.category == "list":
            return ListItem(
                text=self.text
            )
        if self.category == "paragraph":
            return NarrativeText(
                text=self.text
            )
        return Text(
            text=self.text
        ) 


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def clean_elements(
    elements: ExtractedDocument,
) -> list[CleanedElement]:
    """
    Clean extracted Unstructured document elements.

    Cleaning order is intentional:

        1. extract text
        2. repair encoding
        3. remove document-level noise
        4. clean OCR artefacts
        5. normalise whitespace

    Paragraph and section boundaries are preserved because each element is
    cleaned independently.
    """

    extracted = []
    for page in elements.pages:
        for element in page.elements:
            extracted.append(_extract_element(element))

    headers, footers = detect_headers_and_footers(extracted)
    page_labels = _detect_page_labels(extracted)

    cleaned = []
    for element in extracted:
        normalised = normalise_whitespace(element.text)
        if normalised in headers or normalised in footers:
            continue
        text = clean_text(element.text)
        if not text:
            continue
        cleaned.append(CleanedElement(
            text=text,
            category=element.category,
            page_number=page_labels.get(element.page_number, element.page_number),
            section_title=element.section_title,
        ))

    return cleaned


def clean_text(text: str) -> str:
    """
    Clean a single extracted text block.

    This function does not merge paragraphs or alter element ordering.

    Args:
        text:
            Raw extracted text.

    Returns:
        Cleaned text.
    """

    if not text:
        return ""

    text = repair_encoding(text)

    text = strip_dot_leaders(text)

    text = remove_page_numbers(text)

    text = remove_toc_artifacts(text)

    text = remove_stray_characters(text)

    text = normalise_whitespace(text)

    return text.strip()


def repair_encoding(text: str) -> str:
    """
    Repair common mojibake and encoding problems.

    Uses ftfy rather than manual replacement because PDF extraction errors
    vary substantially between documents.

    Args:
        text:
            Input text.

    Returns:
        Encoding-corrected text.
    """

    return ftfy.fix_text(text)


def detect_headers_and_footers(extracted):
    pairs = [
        (el.page_number, normalise_whitespace(el.text))
        for el in extracted if el.text.strip()
    ]
    return _detect_headers_and_footers_generic(pairs)


def remove_page_numbers(text: str) -> str:
    """
    Remove standalone page number artefacts.

    Examples removed:

        12
        Page 12
        PAGE 12

    Args:
        text:
            Text block.

    Returns:
        Cleaned text.
    """

    if PAGE_NUMBER_PATTERN.match(text):
        return ""

    return text


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _extract_element(
    element: ExtractedElement,
) -> CleanedElement:
    """
    Convert an extracted element into a cleaning representation.
    """

    return CleanedElement(
        text=element.text,
        category=element.category,
        page_number=element.page_number,
        section_title=element.section_title,
    )


def _detect_page_labels(extracted: list[CleanedElement]) -> dict[int, int]:
    by_page: dict[int, list[str]] = {}
    for el in extracted:
        by_page.setdefault(el.page_number, []).append(el.text.strip())

    labels: dict[int, int] = {}
    for physical_page, texts in by_page.items():
        label = None
        for text in filter(None, (texts[-1] if texts else None, texts[0] if texts else None)):
            match = PRINTED_PAGE_NUMBER_PATTERN.match(text)
            if match:
                label = int(match.group(1))
                break
        labels[physical_page] = label if label is not None else physical_page

    return labels