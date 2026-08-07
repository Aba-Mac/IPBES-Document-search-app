"""
tests/rendering/test_html.py

Tests for renderer.html.

Covers:
- HTML escaping
- escaped detection
- HTML tokenisation
- safe injection
- tag stripping
"""

from __future__ import annotations

import pytest

from renderer.html import (
    HTMLToken,
    TokenType,
    escape_html,
    is_html_escaped,
    safe_inject,
    split_html,
    strip_tags,
)


# ---------------------------------------------------------------------
# escape_html
# ---------------------------------------------------------------------


def test_escape_html_escapes_special_characters():
    result = escape_html(
        '<script>alert("x")</script>'
    )

    assert result == (
        "&lt;script&gt;"
        "alert(&quot;x&quot;)"
        "&lt;/script&gt;"
    )


def test_escape_html_handles_none():
    assert escape_html(None) == ""


def test_escape_html_preserves_normal_text():
    assert escape_html(
        "climate adaptation"
    ) == "climate adaptation"


# ---------------------------------------------------------------------
# is_html_escaped
# ---------------------------------------------------------------------


def test_is_html_escaped_returns_true_for_plain_text():
    assert is_html_escaped(
        "hello world"
    )


def test_is_html_escaped_returns_true_for_escaped_html():
    assert is_html_escaped(
        "&lt;b&gt;text&lt;/b&gt;"
    )


def test_is_html_escaped_returns_false_for_raw_html():
    assert not is_html_escaped(
        "<b>text</b>"
    )


def test_is_html_escaped_handles_empty_string():
    assert is_html_escaped("")


# ---------------------------------------------------------------------
# split_html
# ---------------------------------------------------------------------


def test_split_html_separates_tags_and_text():

    tokens = split_html(
        "hello <b>world</b>"
    )

    assert tokens == [
        HTMLToken(
            TokenType.TEXT,
            "hello ",
        ),
        HTMLToken(
            TokenType.TAG,
            "<b>",
        ),
        HTMLToken(
            TokenType.TEXT,
            "world",
        ),
        HTMLToken(
            TokenType.TAG,
            "</b>",
        ),
    ]


def test_split_html_preserves_attributes():

    tokens = split_html(
        '<a href="?q=test">test</a>'
    )

    assert tokens[0].value == (
        '<a href="?q=test">'
    )

    assert tokens[0].type is TokenType.TAG


# ---------------------------------------------------------------------
# safe_inject
# ---------------------------------------------------------------------


def test_safe_inject_inserts_html():

    result = safe_inject(
        "hello world",
        [
            (
                6,
                11,
                "<b>world</b>",
            )
        ],
    )

    assert result == (
        "hello <b>world</b>"
    )


def test_safe_inject_multiple_replacements():

    result = safe_inject(
        "abcdef",
        [
            (
                0,
                1,
                "<b>a</b>",
            ),
            (
                2,
                3,
                "<b>c</b>",
            ),
        ],
    )

    assert result == (
        "<b>a</b>"
        "b"
        "<b>c</b>"
        "def"
    )


def test_safe_inject_returns_original_when_empty():

    assert safe_inject(
        "hello",
        [],
    ) == "hello"


def test_safe_inject_rejects_overlapping_spans():

    with pytest.raises(
        ValueError,
        match="overlap",
    ):
        safe_inject(
            "abcdef",
            [
                (
                    1,
                    4,
                    "<b>x</b>",
                ),
                (
                    3,
                    5,
                    "<b>y</b>",
                ),
            ],
        )


def test_safe_inject_rejects_invalid_span():

    with pytest.raises(
        ValueError,
        match="start exceeds end",
    ):
        safe_inject(
            "abcdef",
            [
                (
                    5,
                    2,
                    "<b>x</b>",
                )
            ],
        )


# ---------------------------------------------------------------------
# strip_tags
# ---------------------------------------------------------------------


def test_strip_tags_removes_html_tags():

    assert strip_tags(
        "<b>Hello</b>"
    ) == "Hello"


def test_strip_tags_removes_nested_markup():

    assert strip_tags(
        "<a href='x'><span>term</span></a>"
    ) == "term"