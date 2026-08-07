"""
Tests for ingestion.extractor.

These tests focus on the module's pure-Python logic and avoid invoking
Unstructured or PyMuPDF on real PDFs. External dependencies are mocked where
appropriate.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest

from ingestion.extractor import (
    ExtractedDocument,
    ExtractedElement,
    ExtractedPage,
    ExtractionError,
    PDFMetadata,
    document_has_content,
    document_text,
    extraction_statistics,
    get_page,
    iter_elements,
    iter_pages,
    section_titles,
    validate_document,
    _extract_block_text,
    _block_category,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_document():
    """Create a representative extracted document."""

    page1 = ExtractedPage(
        page_number=1,
        raw_text="Heading\n\nParagraph one.",
        elements=[
            ExtractedElement(
                id=1,
                page_number=1,
                category="title",
                text="Heading",
                section_title="Heading",
            ),
            ExtractedElement(
                id=2,
                page_number=1,
                category="paragraph",
                text="Paragraph one.",
                section_title="Heading",
            ),
        ],
    )

    page2 = ExtractedPage(
        page_number=2,
        raw_text="Paragraph two.",
        elements=[
            ExtractedElement(
                id=3,
                page_number=2,
                category="paragraph",
                text="Paragraph two.",
                section_title="Heading",
            ),
        ],
    )

    return ExtractedDocument(
        source_pdf=Path("sample.pdf"),
        metadata=PDFMetadata(page_count=2),
        pages=[page1, page2],
        extraction_method="unstructured",
    )


# ---------------------------------------------------------------------------
# document_has_content
# ---------------------------------------------------------------------------


def test_document_has_content_true(sample_document):
    text = "x" * 300

    sample_document.pages[0].elements = [
        ExtractedElement(
            id=i,
            page_number=1,
            category="paragraph",
            text=text,
            section_title=None,
        )
        for i in range(5)
    ]

    assert document_has_content(sample_document)


def test_document_has_content_false_too_few_elements(sample_document):
    sample_document.pages[0].elements = [
        sample_document.pages[0].elements[0]
    ]
    sample_document.pages[1].elements = []

    assert not document_has_content(sample_document)


# ---------------------------------------------------------------------------
# Iterators
# ---------------------------------------------------------------------------


def test_iter_elements(sample_document):
    elements = list(iter_elements(sample_document))

    assert len(elements) == 3
    assert elements[0].text == "Heading"


def test_iter_pages(sample_document):
    pages = list(iter_pages(sample_document))

    assert len(pages) == 2
    assert pages[1].page_number == 2


# ---------------------------------------------------------------------------
# Page lookup
# ---------------------------------------------------------------------------


def test_get_page(sample_document):
    page = get_page(sample_document, 2)

    assert page.page_number == 2


def test_get_page_missing(sample_document):
    with pytest.raises(KeyError):
        get_page(sample_document, 99)


# ---------------------------------------------------------------------------
# Document text
# ---------------------------------------------------------------------------


def test_document_text(sample_document):
    text = document_text(sample_document)

    assert "Heading" in text
    assert "Paragraph two." in text


# ---------------------------------------------------------------------------
# Section titles
# ---------------------------------------------------------------------------


def test_section_titles(sample_document):
    assert section_titles(sample_document) == ["Heading"]


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_validate_document_valid(sample_document):
    validate_document(sample_document)


def test_validate_document_no_pages():
    document = ExtractedDocument(
        source_pdf=Path("x.pdf"),
        metadata=PDFMetadata(),
        pages=[],
        extraction_method="test",
    )

    with pytest.raises(ExtractionError):
        validate_document(document)


def test_validate_document_empty_element():
    page = ExtractedPage(
        page_number=1,
        elements=[
            ExtractedElement(
                id=1,
                page_number=1,
                category="paragraph",
                text="",
                section_title=None,
            )
        ],
    )

    document = ExtractedDocument(
        source_pdf=Path("x.pdf"),
        metadata=PDFMetadata(page_count=1),
        pages=[page],
        extraction_method="test",
    )

    with pytest.raises(ExtractionError):
        validate_document(document)


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------


def test_extraction_statistics(sample_document):
    stats = extraction_statistics(sample_document)

    assert stats["pages"] == 2
    assert stats["elements"] == 3
    assert stats["method"] == "unstructured"
    assert "title" in stats["categories"]


# ---------------------------------------------------------------------------
# PyMuPDF helpers
# ---------------------------------------------------------------------------


def test_extract_block_text():
    block = {
        "lines": [
            {
                "spans": [
                    {"text": "Hello"},
                    {"text": " World"},
                ]
            },
            {
                "spans": [
                    {"text": "Second line"},
                ]
            },
        ]
    }

    assert _extract_block_text(block) == "Hello World\nSecond line"


def test_block_category_title():
    block = {
        "lines": [
            {
                "spans": [
                    {
                        "text": "Heading",
                        "font": "Helvetica-Bold",
                        "size": 18,
                    }
                ]
            }
        ]
    }

    assert _block_category(block) == "title"


def test_block_category_heading():
    block = {
        "lines": [
            {
                "spans": [
                    {
                        "text": "Heading",
                        "font": "Arial-Bold",
                        "size": 12,
                    }
                ]
            }
        ]
    }

    assert _block_category(block) == "heading"


def test_block_category_paragraph():
    block = {
        "lines": [
            {
                "spans": [
                    {
                        "text": "Paragraph",
                        "font": "Arial",
                        "size": 11,
                    }
                ]
            }
        ]
    }

    assert _block_category(block) == "paragraph"