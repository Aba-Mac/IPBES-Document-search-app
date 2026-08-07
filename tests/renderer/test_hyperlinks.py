"""
tests/rendering/test_hyperlinks.py

Tests for renderer.hyperlinks.

Covers:
- glossary term hyperlink generation
- HTML escaping compatibility
- case-insensitive matching
- whole-word matching
- longest-term-first replacement
- preservation of existing links
"""

from __future__ import annotations

from renderer.hyperlinks import (
    GlossaryMatch,
    hyperlink_glossary_terms,
)


# ---------------------------------------------------------------------
# Basic hyperlink generation
# ---------------------------------------------------------------------


def test_single_glossary_term_is_linked():

    result = hyperlink_glossary_terms(
        escaped_html="Climate adaptation policy",
        glossary_matches=[
            GlossaryMatch(
                term="adaptation",
                category="policy",
            )
        ],
    )

    assert (
        '<a class="glossary-term" '
        'data-term="adaptation" '
        'href="?q=adaptation">'
        "adaptation"
        "</a>"
    ) in result


def test_multiple_glossary_terms_are_linked():

    result = hyperlink_glossary_terms(
        escaped_html=(
            "Climate and biodiversity policy"
        ),
        glossary_matches=[
            GlossaryMatch("climate"),
            GlossaryMatch("biodiversity"),
        ],
    )

    assert (
        result.count(
            'class="glossary-term"'
        )
        == 2
    )


# ---------------------------------------------------------------------
# Matching behaviour
# ---------------------------------------------------------------------


def test_matching_is_case_insensitive():

    result = hyperlink_glossary_terms(
        escaped_html="CLIMATE policy",
        glossary_matches=[
            GlossaryMatch("climate"),
        ],
    )

    assert (
        "CLIMATE"
        in result
    )

    assert (
        'class="glossary-term"'
        in result
    )


def test_matching_requires_word_boundaries():

    result = hyperlink_glossary_terms(
        escaped_html="climate climatic",

        glossary_matches=[
            GlossaryMatch("climate"),
        ],
    )

    assert (
        result.count(
            'class="glossary-term"'
        )
        == 1
    )


def test_longer_terms_are_processed_first():

    result = hyperlink_glossary_terms(
        escaped_html=(
            "climate change adaptation"
        ),
        glossary_matches=[
            GlossaryMatch(
                "climate"
            ),
            GlossaryMatch(
                "climate change"
            ),
        ],
    )

    assert (
        "climate change"
        in result
    )

    assert (
        result.count(
            'class="glossary-term"'
        )
        == 2
    )


# ---------------------------------------------------------------------
# HTML safety
# ---------------------------------------------------------------------


def test_term_attribute_is_html_escaped():

    result = hyperlink_glossary_terms(
        escaped_html=(
            "water policy"
        ),
        glossary_matches=[
            GlossaryMatch(
                term='water "quality"',
            )
        ],
    )

    assert (
        'data-term="water &quot;quality&quot;"'
        in result
    )


def test_href_is_html_escaped():

    result = hyperlink_glossary_terms(
        escaped_html=(
            "water quality"
        ),
        glossary_matches=[
            GlossaryMatch(
                term='water "quality"',
            )
        ],
    )

    assert (
        "href=\"?q=water%20"
        not in result
    )


# ---------------------------------------------------------------------
# Existing markup handling
# ---------------------------------------------------------------------


def test_existing_anchor_is_not_double_wrapped():

    existing = (
        '<a href="?q=climate">'
        "climate"
        "</a>"
    )

    result = hyperlink_glossary_terms(
        escaped_html=existing,
        glossary_matches=[
            GlossaryMatch(
                "climate"
            )
        ],
    )

    assert (
        result.count(
            "<a "
        )
        == 1
    )


def test_existing_anchor_content_is_preserved():

    existing = (
        '<a href="?q=term">'
        "term"
        "</a>"
    )

    result = hyperlink_glossary_terms(
        escaped_html=existing,
        glossary_matches=[
            GlossaryMatch(
                "term"
            )
        ],
    )

    assert result == existing


# ---------------------------------------------------------------------
# Empty input behaviour
# ---------------------------------------------------------------------


def test_empty_html_returns_empty():

    assert hyperlink_glossary_terms(
        escaped_html="",
        glossary_matches=[
            GlossaryMatch("term")
        ],
    ) == ""


def test_empty_matches_return_original_html():

    html = (
        "climate policy"
    )

    assert hyperlink_glossary_terms(
        escaped_html=html,
        glossary_matches=[],
    ) == html


def test_generator_matches_are_supported():

    result = hyperlink_glossary_terms(
        escaped_html="climate",
        glossary_matches=(
            item
            for item in [
                GlossaryMatch("climate")
            ]
        ),
    )

    assert (
        'class="glossary-term"'
        in result
    )