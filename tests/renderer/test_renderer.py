"""
tests/rendering/test_renderer.py
================================

Tests for renderer.renderer.

Covers:

* complete rendering pipeline
* HTML escaping
* glossary hyperlink integration
* search highlighting integration
* pipeline ordering
* empty input behaviour
* pure-function behaviour
"""

from __future__ import annotations

import pytest

from renderer.renderer import render_paragraph
from renderer.hyperlinks import GlossaryMatch


# ---------------------------------------------------------------------
# Basic rendering
# ---------------------------------------------------------------------


def test_render_paragraph_returns_plain_escaped_html() -> None:
    result = render_paragraph(
        "<Climate policy>"
    )

    assert result == (
        "&lt;Climate policy&gt;"
    )


def test_render_paragraph_empty_input_returns_empty_string() -> None:
    assert render_paragraph("") == ""


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
    ],
)
def test_render_paragraph_handles_missing_text(
    value: str | None,
) -> None:
    assert render_paragraph(value) == ""


# ---------------------------------------------------------------------
# HTML escaping safety
# ---------------------------------------------------------------------


def test_raw_html_is_escaped_before_rendering() -> None:
    result = render_paragraph(
        "<script>alert('x')</script>"
    )

    assert "<script>" not in result
    assert "&lt;script&gt;" in result


def test_quotes_are_escaped() -> None:
    result = render_paragraph(
        '"quoted text"'
    )

    assert "&quot;" in result


# ---------------------------------------------------------------------
# Glossary hyperlink integration
# ---------------------------------------------------------------------


def test_renders_glossary_terms_as_links() -> None:
    result = render_paragraph(
        "Climate adaptation improves resilience.",
        glossary_matches=[
            GlossaryMatch(
                term="Climate adaptation",
            )
        ],
    )

    assert (
        '<a class="glossary-term"'
        in result
    )

    assert (
        "Climate adaptation"
        in result
    )


def test_glossary_links_are_created_after_escaping() -> None:
    result = render_paragraph(
        "<Climate adaptation>",
        glossary_matches=[
            GlossaryMatch(
                term="Climate adaptation",
            )
        ],
    )

    assert "<Climate adaptation>" not in result
    assert "&lt;Climate adaptation&gt;" in result


def test_multiple_glossary_matches_are_supported() -> None:
    result = render_paragraph(
        (
            "Climate policy and "
            "water governance."
        ),
        glossary_matches=[
            GlossaryMatch("Climate policy"),
            GlossaryMatch("water governance"),
        ],
    )

    assert result.count(
        'class="glossary-term"'
    ) == 2


# ---------------------------------------------------------------------
# Search highlighting integration
# ---------------------------------------------------------------------


def test_applies_search_highlighting() -> None:
    result = render_paragraph(
        "Climate adaptation",
        search_query="adaptation",
    )

    assert (
        'class="search-highlight"'
        in result
    )


def test_highlighting_preserves_glossary_links() -> None:
    result = render_paragraph(
        "Climate adaptation",
        glossary_matches=[
            GlossaryMatch(
                term="Climate adaptation"
            )
        ],
        search_query="Climate",
    )

    assert (
        'class="glossary-term"'
        in result
    )

    assert (
        'class="search-highlight"'
        not in result
    )


# ---------------------------------------------------------------------
# Pipeline ordering
# ---------------------------------------------------------------------


def test_pipeline_escapes_before_hyperlinking() -> None:
    result = render_paragraph(
        "<Climate adaptation>",
        glossary_matches=[
            GlossaryMatch(
                term="Climate adaptation"
            )
        ],
    )

    href_index = result.find(
        '<a class="glossary-term"'
    )

    escaped_index = result.find(
        "&lt;"
    )

    assert href_index >= 0
    assert escaped_index >= 0
    assert escaped_index < href_index


def test_pipeline_highlights_after_hyperlinks() -> None:
    result = render_paragraph(
        "Climate adaptation",
        glossary_matches=[
            GlossaryMatch(
                term="adaptation"
            )
        ],
        search_query="Climate",
    )

    #
    # Glossary term should remain a hyperlink.
    #
    assert (
        '<a class="glossary-term"'
        in result
    )


# ---------------------------------------------------------------------
# Iterable handling
# ---------------------------------------------------------------------


def test_accepts_generator_for_glossary_matches() -> None:
    matches = (
        GlossaryMatch("Climate")
        for _ in range(1)
    )

    result = render_paragraph(
        "Climate policy",
        glossary_matches=matches,
    )

    assert (
        'class="glossary-term"'
        in result
    )


# ---------------------------------------------------------------------
# Purity / no mutation
# ---------------------------------------------------------------------


def test_does_not_mutate_glossary_match_collection() -> None:
    matches = [
        GlossaryMatch(
            term="Climate"
        )
    ]

    original = list(matches)

    render_paragraph(
        "Climate policy",
        glossary_matches=matches,
    )

    assert matches == original