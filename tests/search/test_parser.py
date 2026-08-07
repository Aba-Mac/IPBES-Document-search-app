"""
tests/search/test_parser.py

Tests for search query parsing utilities.

These tests verify:

- basic term parsing
- phrase parsing
- boolean operators
- normalization
- invalid query handling
"""

from __future__ import annotations

import pytest

from search.parser import (
    parse_query,
    normalize_query,
)


# ---------------------------------------------------------------------
# normalize_query
# ---------------------------------------------------------------------


def test_normalize_query_lowercases_terms():
    """
    Query normalization should lowercase text.
    """

    result = normalize_query(
        "Climate Change"
    )

    assert result == "climate change"


def test_normalize_query_strips_whitespace():
    """
    Leading and trailing whitespace should be removed.
    """

    result = normalize_query(
        "   parliament   "
    )

    assert result == "parliament"


def test_normalize_query_preserves_phrase_quotes():
    """
    Phrase boundaries should survive normalization.
    """

    result = normalize_query(
        '"Climate Change"'
    )

    assert result == '"climate change"'


# ---------------------------------------------------------------------
# parse_query
# ---------------------------------------------------------------------


def test_parse_simple_term():

    query = parse_query(
        "budget"
    )

    assert query is not None

    assert "budget" in query


def test_parse_multiple_terms():

    query = parse_query(
        "budget parliament"
    )

    assert "budget" in query
    assert "parliament" in query


def test_parse_phrase_query():

    query = parse_query(
        '"climate change"'
    )

    assert '"climate change"' in query


def test_parse_boolean_and():

    query = parse_query(
        "budget AND finance"
    )

    assert "budget" in query
    assert "finance" in query
    assert "AND" in query


def test_parse_boolean_or():

    query = parse_query(
        "budget OR finance"
    )

    assert "budget" in query
    assert "finance" in query
    assert "OR" in query


def test_parse_boolean_not():

    query = parse_query(
        "budget NOT deficit"
    )

    assert "budget" in query
    assert "deficit" in query
    assert "NOT" in query


def test_parse_empty_query_returns_empty():

    result = parse_query(
        ""
    )

    assert result == ""


def test_parse_whitespace_query_returns_empty():

    result = parse_query(
        "   "
    )

    assert result == ""


def test_parse_invalid_query_raises():

    with pytest.raises(Exception):

        parse_query(
            '"unclosed phrase'
        )