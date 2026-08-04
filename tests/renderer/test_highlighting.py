"""
tests/rendering/test_highlighting.py
===================================

Tests for renderer.highlighting.

Covers:

* basic term highlighting
* case-insensitive matching
* multi-word phrases
* longest-term-first ordering
* duplicate query terms
* preservation of HTML tags
* protection of glossary hyperlinks
* empty queries
"""

from __future__ import annotations

import pytest

from renderer.highlighting import (
    HIGHLIGHT_CLASS,
    highlight_search_terms,
)


# ---------------------------------------------------------------------
# Basic highlighting
# ---------------------------------------------------------------------


def test_highlights_single_search_term() -> None:
    html = "Climate adaptation is important."

    result = highlight_search_terms(
        html,
        "adaptation",
    )

    assert (
        f'<span class="{HIGHLIGHT_CLASS}">adaptation</span>'
        in result
    )


def test_highlighting_is_case_insensitive() -> None:
    html = "Climate ADAPTATION is important."

    result = highlight_search_terms(
        html,
        "adaptation",
    )

    assert (
        f'<span class="{HIGHLIGHT_CLASS}">ADAPTATION</span>'
        in result
    )


def test_preserves_original_case() -> None:
    html = "CLIMATE policy"

    result = highlight_search_terms(
        html,
        "climate",
    )

    assert (
        f'<span class="{HIGHLIGHT_CLASS}">CLIMATE</span>'
        in result
    )


# ---------------------------------------------------------------------
# Query parsing behaviour
# ---------------------------------------------------------------------


def test_supports_multi_word_search_phrase() -> None:
    html = "Climate change adaptation policies."

    result = highlight_search_terms(
        html,
        "climate change",
    )

    assert (
        f'<span class="{HIGHLIGHT_CLASS}">'
        "Climate change"
        "</span>"
        in result
    )


def test_duplicate_query_terms_are_only_applied_once() -> None:
    html = "Climate adaptation"

    result = highlight_search_terms(
        html,
        "climate climate",
    )

    assert result.count(
        f'class="{HIGHLIGHT_CLASS}"'
    ) == 1


def test_longer_terms_are_highlighted_before_shorter_terms() -> None:
    html = "climate change"

    result = highlight_search_terms(
        html,
        "climate change climate",
    )

    assert (
        result.count(
            f'class="{HIGHLIGHT_CLASS}"'
        )
        == 1
    )

    assert (
        f'<span class="{HIGHLIGHT_CLASS}">'
        "climate change"
        "</span>"
        in result
    )


# ---------------------------------------------------------------------
# HTML safety
# ---------------------------------------------------------------------


def test_does_not_modify_html_tags() -> None:
    html = (
        '<a href="?q=climate">'
        "climate"
        "</a>"
    )

    result = highlight_search_terms(
        html,
        "href",
    )

    assert result == html


def test_does_not_highlight_inside_existing_links() -> None:
    html = (
        '<a class="glossary-term" href="?q=climate">'
        "climate"
        "</a>"
        " climate"
    )

    result = highlight_search_terms(
        html,
        "climate",
    )

    assert (
        '<a class="glossary-term" href="?q=climate">'
        "climate"
        "</a>"
        in result
    )

    assert result.count(
        f'class="{HIGHLIGHT_CLASS}"'
    ) == 1


def test_preserves_non_matching_html() -> None:
    html = (
        "<p>"
        "Governance text"
        "</p>"
    )

    result = highlight_search_terms(
        html,
        "climate",
    )

    assert result == html


# ---------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "query",
    [
        None,
        "",
        "   ",
    ],
)
def test_empty_search_query_returns_original_html(
    query: str | None,
) -> None:
    html = "Climate adaptation"

    result = highlight_search_terms(
        html,
        query,
    )

    assert result == html


def test_empty_html_returns_empty_html() -> None:
    result = highlight_search_terms(
        "",
        "climate",
    )

    assert result == ""


def test_multiple_terms_highlight_independently() -> None:
    html = (
        "Climate policy supports adaptation."
    )

    result = highlight_search_terms(
        html,
        "climate adaptation",
    )

    assert result.count(
        f'class="{HIGHLIGHT_CLASS}"'
    ) == 2