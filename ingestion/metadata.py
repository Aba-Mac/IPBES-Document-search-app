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


CITATION_PATTERN = re.compile(
    r"Suggested\s+citation\s*:?\s*\n?"
    r"\s*IPBES\s*\(\s*(?P<year>(?:19|20)\d{2})\s*\)\.\s*"
    r"(?P<body>.+?)(?=\n\s*\n|\Z)",
    flags=re.IGNORECASE | re.DOTALL,
)


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
    Extract the beginning of the document for metadata extraction.

    The suggested citation is normally located near the beginning
    of the report, so the first few pages are inspected.
    """
    with fitz.open(pdf_path) as document:
        if document.page_count == 0:
            return ""

        pages = min(5, document.page_count)

        return "\n".join(
            document[index].get_text("text")
            for index in range(pages)
        )


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

    year_match = re.search(
        r"\b((?:19|20)\d{2})\b",
        text,
    )

    if year_match:
        year = int(year_match.group(1))
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


def _parse_citation_body(body: str) -> tuple[str | None, str | None]:
    """
    Split citation body into (title, location).

    Expected format:
        <authors>. <title>. <date>, <location>
    """
    body = re.sub(r"\s+", " ", body).strip()

    parts = re.split(r"\.\s+", body, maxsplit=2)

    if len(parts) < 3:
        return None, None

    _, title, tail = parts

    tail_parts = [p.strip() for p in tail.rsplit(",", 1)]
    location = tail_parts[-1] if len(tail_parts) == 2 else None

    return (title.strip() or None), location


def build_metadata(
    pdf_path: Path,
    llm_client: MetadataLLMClient | None = None,
) -> DocumentMetadata:
    """
    Extract complete document metadata.

    Extraction priority
    -------------------
        1. Suggested citation
        2. PyMuPDF creation date
        3. LLM

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

    initial_text = extract_first_page_text(pdf_path)

    # ------------------------------------------------------------------
    # Suggested citation (highest-priority source: title, year, location)
    # ------------------------------------------------------------------

    citation_match = CITATION_PATTERN.search(initial_text)

    if citation_match:
        citation_year = int(citation_match.group("year"))
        fields["year"] = MetadataField(citation_year, "suggested_citation")

        citation_title, citation_location = _parse_citation_body(
            citation_match.group("body")
        )

        if citation_title:
            fields["title"] = MetadataField(citation_title, "suggested_citation")

        if citation_location:
            fields["location"] = MetadataField(citation_location, "suggested_citation")

        logger.info(
            "Extracted from suggested citation: year=%s title=%r location=%r",
            citation_year, citation_title, citation_location,
        )

    # ------------------------------------------------------------------
    # Title fallback (only if citation didn't provide one)
    # ------------------------------------------------------------------

    if not fields["title"].value:
        title = clean_value(embedded.get("title"))
        if title:
            fields["title"] = MetadataField(title, "pymupdf")

    if not fields["title"].value:
        unstructured_title = detect_unstructured_title(pdf_path)
        if unstructured_title:
            fields["title"] = MetadataField(unstructured_title, "unstructured")

    # ------------------------------------------------------------------
    # PDF creation date (year only used if citation didn't provide one)
    # ------------------------------------------------------------------

    date_value = clean_value(embedded.get("creationDate"))
    date, embedded_year = normalise_date(date_value)

    if date:
        fields["date"] = MetadataField(date, "pymupdf")

    if embedded_year is not None and fields["year"].value is None:
        fields["year"] = MetadataField(embedded_year, "pymupdf")

    # ------------------------------------------------------------------
    # LLM fallback
    # ------------------------------------------------------------------

    missing_fields = [name for name, field in fields.items() if field.value is None]

    if missing_fields and llm_client:
        try:
            response = validate_llm_output(llm_client.extract_metadata(initial_text))

            for key in missing_fields:
                value = response.get(key)
                if value is None:
                    continue

                if key == "date":
                    date, year = normalise_date(value)
                    if date:
                        fields["date"] = MetadataField(date, "llm")
                    if year is not None and fields["year"].value is None:
                        fields["year"] = MetadataField(year, "llm")
                else:
                    fields[key] = MetadataField(value, "llm")

        except Exception:
            logger.exception("LLM metadata extraction failed for %s", pdf_path)

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