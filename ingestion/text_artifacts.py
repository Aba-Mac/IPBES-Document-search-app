"""
Shared low-level text-artifact detection.

Operates on plain (page_number, text) pairs so it can be used both
pre-chunking (raw Unstructured elements) and post-extraction
(CleanedElement / PyMuPDF blocks) without any dependency on either
module's dataclasses.
"""
from __future__ import annotations
import re
from collections import Counter
from typing import Sequence

MIN_HEADER_FOOTER_OCCURRENCES = 3
HEADER_FOOTER_WINDOW = 3

PAGE_NUMBER_PATTERN = re.compile(r"^\s*(?:page\s*)?\d+\s*$", flags=re.IGNORECASE)
DOT_LEADER_PATTERN = re.compile(r"\.{2,}\s*\d+\s*$")
TOC_ENTRY_PATTERN = re.compile(
    r"(?:^|\s)(?P<label>.{3,80}?)(\.{2,}|…+)\s*(?P<num>\d{1,4})(?=\s|$)"
)
MULTIPLE_WHITESPACE_PATTERN = re.compile(r"[ \t]+")
MULTIPLE_NEWLINES_PATTERN = re.compile(r"\n{3,}")
STRAY_CHARACTER_PATTERN = re.compile(r"^[^A-Za-z0-9À-ž]+$")
OCR_GARBAGE_PATTERN = re.compile(r"(?<!\w)[|¦•]{2,}(?!\w)")
PRINTED_PAGE_NUMBER_PATTERN = re.compile(r"^\s*(?:page\s*)?(\d{1,4})\s*$", re.IGNORECASE)


def normalise_whitespace(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = MULTIPLE_WHITESPACE_PATTERN.sub(" ", text)
    text = MULTIPLE_NEWLINES_PATTERN.sub("\n\n", text)
    return text.strip()


def strip_dot_leaders(text: str) -> str:
    return DOT_LEADER_PATTERN.sub("", text)


def remove_toc_artifacts(text: str) -> str:
    stripped = text.strip()
    if not stripped:
        return text
    matches = list(TOC_ENTRY_PATTERN.finditer(stripped))
    if not matches:
        return text
    if len(matches) >= 2:
        return ""
    match = matches[0]
    covered = match.end() - match.start()
    if covered / len(stripped) > 0.8:
        return ""
    return text


def remove_stray_characters(text: str) -> str:
    if STRAY_CHARACTER_PATTERN.match(text.strip()):
        return ""
    return OCR_GARBAGE_PATTERN.sub(" ", text)


def detect_headers_and_footers(
    pairs: Sequence[tuple[int, str]],
) -> tuple[set[str], set[str]]:
    """
    pairs: sequence of (page_number, normalised_text), in document order.
    """
    by_page: dict[int, list[str]] = {}
    for page, text in pairs:
        if not text:
            continue
        by_page.setdefault(page, []).append(text)

    counts = Counter(text for _, text in pairs if text)

    first_position_counts: dict[int, Counter] = {}
    last_position_counts: dict[int, Counter] = {}
    for texts in by_page.values():
        window = min(HEADER_FOOTER_WINDOW, len(texts))
        for offset in range(window):
            first_position_counts.setdefault(offset, Counter())[texts[offset]] += 1
            last_position_counts.setdefault(offset, Counter())[texts[-1 - offset]] += 1

    headers, footers = set(), set()
    for text, count in counts.items():
        if count < MIN_HEADER_FOOTER_OCCURRENCES:
            continue
        if PAGE_NUMBER_PATTERN.match(text):
            footers.add(text)
            continue
        is_header = any(
            pc.get(text, 0) >= MIN_HEADER_FOOTER_OCCURRENCES
            for pc in first_position_counts.values()
        )
        is_footer = any(
            pc.get(text, 0) >= MIN_HEADER_FOOTER_OCCURRENCES
            for pc in last_position_counts.values()
        )
        if is_header:
            headers.add(text)
        elif is_footer:
            footers.add(text)

    return headers, footers