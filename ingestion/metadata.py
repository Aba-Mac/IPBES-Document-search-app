"""
Document metadata extraction.

Extraction priority
-------------------

For each metadata field:

1. PyMuPDF embedded metadata
2. Unstructured title detection
3. LLM fallback extraction from first-page text

Every extracted field records its provenance so the ingestion
pipeline can audit how metadata was produced.

Supported fields
----------------

- title
- plenary_session
- year
- date
- location

The module deliberately does not write to the database. Persistence
belongs in database/repository.py.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

import fitz  

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class MetadataField:
    """
    Single metadata value with extraction provenance.
    """

    value: str | int | None
    source: str | None


@dataclass(slots=True)
class DocumentMetadata:
    """
    Normalised document metadata.
    """

    title: MetadataField
    plenary_session: MetadataField
    year: MetadataField
    date: MetadataField
    location: MetadataField

    def as_dict(self) -> dict[str, Any]:
        """
        Convert metadata into serialisable dictionary form.
        """
        return asdict(self)


class MetadataLLMClient(Protocol):
    """
    Interface required by the optional LLM fallback.

    Implementations may use Ollama, OpenAI-compatible APIs,
    or another local model provider.
    """

    def extract_metadata(self, first_page_text: str) -> dict[str, Any]:
        """
        Extract metadata fields from document text.

        Returns
        -------
        dict
            JSON-compatible metadata dictionary.
        """
        ...


def extract_pdf_metadata(pdf_path: Path) -> dict[str, Any]:
    """
    Extract embedded metadata using PyMuPDF.

    Parameters
    ----------
    pdf_path:
        PDF document path.

    Returns
    -------
    dict
        Embedded PDF metadata.
    """

    with fitz.open(pdf_path) as document:
        metadata = document.metadata or {}

    return metadata


def extract_first_page_text(pdf_path: Path) -> str:
    """
    Extract first page text for fallback analysis.

    Parameters
    ----------
    pdf_path:
        PDF document path.

    Returns
    -------
    str
        First page text.
    """

    with fitz.open(pdf_path) as document:
        if document.page_count == 0:
            return ""

        return document[0].get_text("text")


def detect_unstructured_title(pdf_path: Path) -> str | None:
    """
    Detect title using Unstructured.

    This function intentionally keeps the Unstructured dependency
    isolated so ingestion tests can mock it.

    Parameters
    ----------
    pdf_path:
        PDF document path.

    Returns
    -------
    str | None
        Detected title.
    """

    try:
        from unstructured.partition.pdf import partition_pdf

        elements = partition_pdf(
            filename=str(pdf_path),
            strategy="fast",
        )

        for element in elements:
            category = getattr(element, "category", None)

            if category == "Title":
                text = str(element).strip()

                if text:
                    return text

    except Exception:
        logger.exception(
            "Unstructured title detection failed for %s",
            pdf_path,
        )

    return None


def normalise_date(value: Any) -> tuple[str | None, int | None]:
    """
    Normalise dates into ISO format and year.

    Parameters
    ----------
    value:
        Candidate date value.

    Returns
    -------
    tuple
        ISO date and year.
    """

    if not value:
        return None, None

    text = str(value).strip()

    patterns = (
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%B %d %Y",
        "%d %B %Y",
    )

    for pattern in patterns:
        try:
            parsed = datetime.strptime(text, pattern)

            return (
                parsed.date().isoformat(),
                parsed.year,
            )

        except ValueError:
            continue

    year_match = re.search(r"\b(19|20)\d{2}\b", text)

    if year_match:
        year = int(year_match.group())

        return text, year

    return None, None


def clean_value(value: Any) -> str | None:
    """
    Validate and clean extracted string values.

    Empty or clearly invalid values are discarded.
    """

    if value is None:
        return None

    value = str(value).strip()

    if not value:
        return None

    if value.lower() in {
        "unknown",
        "n/a",
        "none",
        "null",
    }:
        return None

    return value


def validate_llm_output(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Validate and sanitise LLM output.

    Invalid or hallucinated empty values are removed.
    """

    allowed = {
        "title",
        "plenary_session",
        "year",
        "date",
        "location",
    }

    cleaned: dict[str, Any] = {}

    for key in allowed:
        if key in payload:
            cleaned[key] = clean_value(payload[key])

    return cleaned


def build_metadata(
    pdf_path: Path,
    llm_client: MetadataLLMClient | None = None,
) -> DocumentMetadata:
    """
    Extract complete document metadata.

    Parameters
    ----------
    pdf_path:
        PDF document path.

    llm_client:
        Optional LLM fallback provider.

    Returns
    -------
    DocumentMetadata
        Extracted metadata with provenance.
    """

    embedded = extract_pdf_metadata(pdf_path)

    fields: dict[str, MetadataField] = {
        "title": MetadataField(None, None),
        "plenary_session": MetadataField(None, None),
        "year": MetadataField(None, None),
        "date": MetadataField(None, None),
        "location": MetadataField(None, None),
    }

    title = clean_value(
        embedded.get("title")
    )

    if title:
        fields["title"] = MetadataField(
            title,
            "pymupdf",
        )

    unstructured_title = None

    if not fields["title"].value:
        unstructured_title = detect_unstructured_title(pdf_path)

        if unstructured_title:
            fields["title"] = MetadataField(
                unstructured_title,
                "unstructured",
            )

    date_value = clean_value(
        embedded.get("creationDate")
    )

    date, year = normalise_date(date_value)

    if date:
        fields["date"] = MetadataField(
            date,
            "pymupdf",
        )

    if year:
        fields["year"] = MetadataField(
            year,
            "pymupdf",
        )

    missing_fields = [
        name
        for name, field in fields.items()
        if field.value is None
    ]

    if missing_fields and llm_client:

        logger.info(
            "Using LLM metadata fallback for %s fields",
            missing_fields,
        )

        first_page = extract_first_page_text(pdf_path)

        try:
            response = llm_client.extract_metadata(
                first_page
            )

            response = validate_llm_output(
                response
            )

            for key in missing_fields:

                value = response.get(key)

                if value is None:
                    continue

                if key == "date":
                    date, year = normalise_date(value)

                    if date:
                        fields["date"] = MetadataField(
                            date,
                            "llm",
                        )

                    if year:
                        fields["year"] = MetadataField(
                            year,
                            "llm",
                        )

                else:
                    fields[key] = MetadataField(
                        value,
                        "llm",
                    )

        except Exception:
            logger.exception(
                "LLM metadata extraction failed for %s",
                pdf_path,
            )

    logger.info(
        "Metadata extraction complete: %s",
        {
            key: {
                "value": field.value,
                "source": field.source,
            }
            for key, field in fields.items()
        },
    )

    return DocumentMetadata(
        title=fields["title"],
        plenary_session=fields["plenary_session"],
        year=fields["year"],
        date=fields["date"],
        location=fields["location"],
    )


def metadata_provenance_fields(
    metadata: DocumentMetadata,
) -> dict[str, tuple[str | int, str]]:
    return {
        "title": (
            metadata.title.value,
            metadata.title.source,
        ),
        "plenary_session": (
            metadata.plenary_session.value,
            metadata.plenary_session.source,
        ),
        "year": (
            metadata.year.value,
            metadata.year.source,
        ),
        "date": (
            metadata.date.value,
            metadata.date.source,
        ),
        "location": (
            metadata.location.value,
            metadata.location.source,
        ),
    }