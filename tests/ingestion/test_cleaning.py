"""
tests/ingestion/test_cleaning.py

Unit tests for ingestion.cleaning.
"""

from types import SimpleNamespace

import pytest

from ingestion.cleaning import (
    CleanedElement,
    clean_elements,
    clean_text,
    detect_headers_and_footers,
    normalise_whitespace,
    remove_page_numbers,
    remove_stray_characters,
    remove_toc_artifacts,
    repair_encoding,
    strip_dot_leaders,
    _extract_element,
)


# ---------------------------------------------------------------------------
# repair_encoding
# ---------------------------------------------------------------------------


def test_repair_encoding_fixes_mojibake():
    assert repair_encoding("FranÃ§ais") == "Français"


def test_repair_encoding_leaves_valid_text():
    text = "The quick brown fox."
    assert repair_encoding(text) == text


# ---------------------------------------------------------------------------
# remove_page_numbers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "12",
        "  7 ",
        "Page 3",
        "PAGE 99",
    ],
)
def test_remove_page_numbers(text):
    assert remove_page_numbers(text) == ""


@pytest.mark.parametrize(
    "text",
    [
        "Page three",
        "Section 12",
        "Page12",
    ],
)
def test_remove_page_numbers_keeps_normal_text(text):
    assert remove_page_numbers(text) == text


# ---------------------------------------------------------------------------
# strip_dot_leaders
# ---------------------------------------------------------------------------


def test_strip_dot_leaders():
    assert (
        strip_dot_leaders("Introduction ........ 12")
        == "Introduction "
    )


def test_strip_dot_leaders_no_change():
    text = "Introduction"
    assert strip_dot_leaders(text) == text


# ---------------------------------------------------------------------------
# remove_toc_artifacts
# ---------------------------------------------------------------------------


def test_remove_toc_artifacts():
    assert remove_toc_artifacts(
        "Chapter One ............. 5"
    ) == ""


def test_remove_toc_artifacts_keeps_normal_text():
    text = "Chapter One"
    assert remove_toc_artifacts(text) == text


# ---------------------------------------------------------------------------
# remove_stray_characters
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "||||",
        "••••",
        "----",
        "***",
    ],
)
def test_remove_stray_characters_discards_symbol_blocks(text):
    assert remove_stray_characters(text) == ""


def test_remove_stray_characters_removes_ocr_garbage():
    assert remove_stray_characters("Hello ||| World") == "Hello   World"


def test_remove_stray_characters_keeps_sentence():
    text = "This is a sentence."
    assert remove_stray_characters(text) == text


# ---------------------------------------------------------------------------
# normalise_whitespace
# ---------------------------------------------------------------------------


def test_normalise_whitespace_spaces():
    assert (
        normalise_whitespace("Hello    world")
        == "Hello world"
    )


def test_normalise_whitespace_newlines():
    assert (
        normalise_whitespace("A\n\n\n\nB")
        == "A\n\nB"
    )


def test_normalise_whitespace_windows_newlines():
    assert (
        normalise_whitespace("A\r\nB\rC")
        == "A\nB\nC"
    )


# ---------------------------------------------------------------------------
# clean_text
# ---------------------------------------------------------------------------


def test_clean_text_full_pipeline():
    text = "Page 3"

    assert clean_text(text) == ""


def test_clean_text_removes_dot_leaders():
    assert (
        clean_text("Introduction ........ 12")
        == "Introduction"
    )


def test_clean_text_empty():
    assert clean_text("") == ""


# ---------------------------------------------------------------------------
# detect_headers_and_footers
# ---------------------------------------------------------------------------


def test_detect_headers_and_footers_detects_repeated_header():
    texts = [
        "Standing Committee",
        "Standing Committee",
        "Standing Committee",
        "Body",
    ]

    headers, footers = detect_headers_and_footers(texts)

    assert "Standing Committee" in headers
    assert footers == set()


def test_detect_headers_and_footers_detects_page_numbers():
    texts = [
        "Page 1",
        "Page 1",
        "Page 1",
    ]

    headers, footers = detect_headers_and_footers(texts)

    assert "Page 1" in footers


def test_detect_headers_and_footers_no_repetition():
    headers, footers = detect_headers_and_footers(
        [
            "A",
            "B",
            "C",
        ]
    )

    assert headers == set()
    assert footers == set()


# ---------------------------------------------------------------------------
# _extract_element
# ---------------------------------------------------------------------------


def test_extract_element_from_dict():
    element = {
        "text": "Example",
        "category": "paragraph",
    }

    extracted = _extract_element(element)

    assert extracted.text == "Example"
    assert extracted.category == "paragraph"


def test_extract_element_from_object():
    obj = SimpleNamespace(
        text="Hello",
        category="title",
    )

    extracted = _extract_element(obj)

    assert extracted.text == "Hello"
    assert extracted.category == "title"


def test_extract_element_missing_attributes():
    extracted = _extract_element(object())

    assert extracted.text == ""
    assert extracted.category is None


# ---------------------------------------------------------------------------
# clean_elements
# ---------------------------------------------------------------------------


def test_clean_elements_returns_cleaned_objects():
    elements = [
        {
            "text": "Paragraph",
            "category": "paragraph",
        }
    ]

    cleaned = clean_elements(elements)

    assert len(cleaned) == 1

    assert isinstance(cleaned[0], CleanedElement)

    assert cleaned[0].text == "Paragraph"
    assert cleaned[0].category == "paragraph"


def test_clean_elements_removes_page_number():
    elements = [
        {
            "text": "Page 4",
            "category": "text",
        }
    ]

    cleaned = clean_elements(elements)

    assert cleaned == []


def test_clean_elements_filters_repeated_headers():
    elements = [
        {"text": "Committee", "category": "title"},
        {"text": "Committee", "category": "title"},
        {"text": "Committee", "category": "title"},
        {"text": "Real paragraph", "category": "paragraph"},
    ]

    cleaned = clean_elements(elements)

    assert len(cleaned) == 1
    assert cleaned[0].text == "Real paragraph"


def test_clean_elements_handles_object_elements():
    elements = [
        SimpleNamespace(
            text="Paragraph",
            category="paragraph",
        )
    ]

    cleaned = clean_elements(elements)

    assert cleaned[0].text == "Paragraph"


def test_clean_elements_empty_input():
    assert clean_elements([]) == []