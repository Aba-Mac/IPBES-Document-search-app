"""
Shared low-level whitespace normalisation on extracted text.
"""
from __future__ import annotations
import re

MULTIPLE_WHITESPACE_PATTERN = re.compile(r"[ \t]+")
MULTIPLE_NEWLINES_PATTERN = re.compile(r"\n{3,}")


def normalise_whitespace(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = MULTIPLE_WHITESPACE_PATTERN.sub(" ", text)
    text = MULTIPLE_NEWLINES_PATTERN.sub("\n\n", text)
    return text.strip()