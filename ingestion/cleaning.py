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

import re
from collections import Counter
from dataclasses import dataclass
from typing import Iterable, List, Sequence
from ingestion.extractor import ExtractedDocument, ExtractedElement
from unstructured.documents.elements import (
    NarrativeText,
    Title,
    ListItem,
    Text,
    )

import ftfy


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MIN_HEADER_FOOTER_OCCURRENCES = 3

PAGE_NUMBER_PATTERN = re.compile(
    r"^\s*(?:page\s*)?\d+\s*$",
    flags=re.IGNORECASE,
)

DOT_LEADER_PATTERN = re.compile(
    r"\.{2,}\s*\d+\s*$"
)

TOC_ENTRY_PATTERN = re.compile(
    r"(?:^|\s)(?P<label>.{3,80}?)(\.{2,}|…+)\s*(?P<num>\d{1,4})(?=\s|$)"
)

MULTIPLE_WHITESPACE_PATTERN = re.compile(
    r"[ \t]+"
)

MULTIPLE_NEWLINES_PATTERN = re.compile(
    r"\n{3,}"
)

STRAY_CHARACTER_PATTERN = re.compile(
    r"^[^A-Za-z0-9À-ž]+$"
)

OCR_GARBAGE_PATTERN = re.compile(
    r"(?<!\w)[|¦•]{2,}(?!\w)"
)

PRINTED_PAGE_NUMBER_PATTERN = re.compile(
    r"^\s*(?:page\s*)?(\d{1,4})\s*$", re.IGNORECASE
    )

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


def detect_headers_and_footers(
    extracted: Sequence[CleanedElement],
) -> tuple[set[str], set[str]]:
    """
    Detect repeated header and footer candidates using repetition
    frequency plus position on the page.

    Word-count heuristics are unreliable for headers (running titles are
    often long, e.g. full report titles). Position is more robust: a
    header candidate should consistently be the first element on its
    page; a footer candidate should consistently be the last, or look
    like a page number.
    """
    by_page: dict[int, list[str]] = {}
    for element in extracted:
        text = normalise_whitespace(element.text)
        if not text:
            continue
        by_page.setdefault(element.page_number, []).append(text)

    counts = Counter(
        normalise_whitespace(element.text)
        for element in extracted
        if element.text.strip()
    )

    first_on_page = Counter(texts[0] for texts in by_page.values() if texts)
    last_on_page = Counter(texts[-1] for texts in by_page.values() if texts)

    headers: set[str] = set()
    footers: set[str] = set()

    for text, count in counts.items():
        if count < MIN_HEADER_FOOTER_OCCURRENCES:
            continue

        if PAGE_NUMBER_PATTERN.match(text):
            footers.add(text)
            continue

        if first_on_page[text] >= MIN_HEADER_FOOTER_OCCURRENCES:
            headers.add(text)
        elif last_on_page[text] >= MIN_HEADER_FOOTER_OCCURRENCES:
            footers.add(text)

    return headers, footers


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


def strip_dot_leaders(text: str) -> str:
    """
    Remove OCR-generated dot leaders.

    Example:

        Introduction ........ 12

    becomes:

        Introduction

    Args:
        text:
            Input text.

    Returns:
        Cleaned text.
    """

    return DOT_LEADER_PATTERN.sub("", text)



def remove_toc_artifacts(text: str) -> str:
    """
    Remove table-of-contents style entries.

    Unstructured sometimes merges an entire TOC section into one element,
    so this checks for dot-leader entries anywhere in the text rather than
    requiring the whole block to be a single entry.
    """
    stripped = text.strip()
    if not stripped:
        return text

    matches = list(TOC_ENTRY_PATTERN.finditer(stripped))
    if not matches:
        return text

    if len(matches) >= 2:
        # Multiple dot-leader entries packed into one element = a merged
        # TOC block. Drop the whole thing.
        return ""

    # Single entry: only drop if it accounts for essentially the whole
    # element (this preserves the old single-line TOC behaviour).
    match = matches[0]
    covered = match.end() - match.start()
    if covered / len(stripped) > 0.8:
        return ""

    return text


def remove_stray_characters(text: str) -> str:
    """
    Remove OCR blocks containing only meaningless symbols.

    Examples removed:

        ||||
        •••
        ----

    Real punctuation inside sentences is preserved.

    Args:
        text:
            Input text.

    Returns:
        Cleaned text.
    """

    if STRAY_CHARACTER_PATTERN.match(text.strip()):
        return ""

    text = OCR_GARBAGE_PATTERN.sub(" ", text)

    return text


def normalise_whitespace(text: str) -> str:
    """
    Normalise whitespace while preserving paragraph structure.

    Args:
        text:
            Input text.

    Returns:
        Whitespace-normalised text.
    """

    text = text.replace("\r\n", "\n")
    text = text.replace("\r", "\n")

    text = MULTIPLE_WHITESPACE_PATTERN.sub(
        " ",
        text,
    )

    text = MULTIPLE_NEWLINES_PATTERN.sub(
        "\n\n",
        text,
    )

    return text.strip()


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
