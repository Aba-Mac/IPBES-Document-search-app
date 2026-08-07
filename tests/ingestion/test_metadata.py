### `tests/ingestion/test_metadata.py`

from pathlib import Path
from unittest.mock import Mock, patch

from ingestion.metadata import (
    build_metadata,
    normalise_date,
    validate_llm_output,
)


def test_normalise_date():
    date, year = normalise_date(
        "15 March 2024"
    )

    assert date == "2024-03-15"
    assert year == 2024


def test_validate_llm_output_removes_invalid_values():

    result = validate_llm_output(
        {
            "title": "Example",
            "location": "",
            "year": None,
            "date": "null",
        }
    )

    assert result["title"] == "Example"
    assert result["location"] is None


def test_llm_fallback_is_used_when_metadata_missing(tmp_path):

    pdf = tmp_path / "example.pdf"

    pdf.write_bytes(b"%PDF-1.4")

    llm = Mock()

    llm.extract_metadata.return_value = {
        "title": "Recovered title",
        "location": "Geneva",
    }

    with patch(
        "ingestion.metadata.extract_pdf_metadata",
        return_value={},
    ), patch(
        "ingestion.metadata.detect_unstructured_title",
        return_value=None,
    ), patch(
        "ingestion.metadata.extract_first_page_text",
        return_value="Document text",
    ):

        result = build_metadata(
            pdf,
            llm_client=llm,
        )

    assert result.title.value == "Recovered title"
    assert result.title.source == "llm"

    assert result.location.value == "Geneva"
    assert result.location.source == "llm"


def test_pymupdf_metadata_has_priority(tmp_path):

    pdf = tmp_path / "example.pdf"

    pdf.write_bytes(b"%PDF-1.4")

    with patch(
        "ingestion.metadata.extract_pdf_metadata",
        return_value={
            "title": "Embedded title"
        },
    ), patch(
        "ingestion.metadata.detect_unstructured_title",
        return_value="Detected title",
    ):

        result = build_metadata(pdf)

    assert result.title.value == "Embedded title"
    assert result.title.source == "pymupdf"
