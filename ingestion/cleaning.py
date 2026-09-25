"""
cleaning.py

Text cleaning for extracted elements: repair encoding, normalise whitespace.
"""
from __future__ import annotations

from dataclasses import replace

import ftfy

from ingestion.extractor import ExtractedDocument, ExtractedElement
from ingestion.text_artifacts import normalise_whitespace


def repair_encoding(text: str) -> str:
    return ftfy.fix_text(text)


def clean_text(text: str) -> str:
    if not text:
        return ""
    return normalise_whitespace(repair_encoding(text)).strip()


def clean_elements(document: ExtractedDocument) -> list[ExtractedElement]:
    cleaned = []
    for element in document.elements:
        text = clean_text(element.text)
        if text:
            cleaned.append(replace(element, text=text))
    return cleaned