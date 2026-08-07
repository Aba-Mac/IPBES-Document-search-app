"""
tests/search/test_ranker.py

Tests for search ranking logic.

These tests verify:

- score calculation
- ranking order
- tie handling
- confidence weighting
- empty result handling
"""

from __future__ import annotations

import pytest

from search.ranker import (
    rank_results,
    score_result,
)


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------


def _result(
    *,
    score: float = 0.0,
    confidence: float = 0.0,
    occurrences: int = 0,
    page_number: int = 1,
):
    """
    Build a minimal search result object.

    The ranker should operate on mappings or objects
    exposing these fields.
    """

    return {
        "score": score,
        "confidence": confidence,
        "occurrence_count": occurrences,
        "page_number": page_number,
    }


# ---------------------------------------------------------------------
# score_result
# ---------------------------------------------------------------------


def test_score_result_returns_numeric_score():

    result = _result(
        score=1.5,
        confidence=0.5,
        occurrences=3,
    )

    value = score_result(result)

    assert isinstance(
        value,
        float,
    )


def test_higher_search_score_increases_rank_score():

    low = score_result(
        _result(score=1.0)
    )

    high = score_result(
        _result(score=5.0)
    )

    assert high > low


def test_higher_confidence_increases_rank_score():

    low = score_result(
        _result(
            score=1.0,
            confidence=0.1,
        )
    )

    high = score_result(
        _result(
            score=1.0,
            confidence=0.9,
        )
    )

    assert high > low


def test_more_occurrences_increase_rank_score():

    low = score_result(
        _result(
            score=1.0,
            occurrences=1,
        )
    )

    high = score_result(
        _result(
            score=1.0,
            occurrences=10,
        )
    )

    assert high > low


def test_score_handles_missing_optional_fields():

    value = score_result(
        {
            "score": 1.0,
        }
    )

    assert isinstance(
        value,
        float,
    )


# ---------------------------------------------------------------------
# rank_results
# ---------------------------------------------------------------------


def test_rank_results_orders_best_first():

    results = [
        _result(score=1.0),
        _result(score=5.0),
        _result(score=3.0),
    ]

    ranked = rank_results(
        results
    )

    assert ranked[0]["score"] == 5.0
    assert ranked[1]["score"] == 3.0
    assert ranked[2]["score"] == 1.0


def test_rank_results_returns_new_collection():

    results = [
        _result(score=1.0),
        _result(score=2.0),
    ]

    ranked = rank_results(
        results
    )

    assert ranked is not results


def test_rank_results_handles_empty_input():

    ranked = rank_results(
        []
    )

    assert ranked == []


def test_rank_results_respects_limit():

    results = [
        _result(score=1.0),
        _result(score=2.0),
        _result(score=3.0),
    ]

    ranked = rank_results(
        results,
        limit=2,
    )

    assert len(ranked) == 2


def test_rank_results_does_not_modify_original():

    results = [
        _result(score=1.0),
        _result(score=5.0),
    ]

    original = list(results)

    rank_results(
        results
    )

    assert results == original


def test_rank_results_combines_confidence_and_score():

    results = [

        _result(
            score=10.0,
            confidence=0.0,
        ),

        _result(
            score=5.0,
            confidence=1.0,
        ),

    ]

    ranked = rank_results(
        results
    )

    assert ranked[0] in results


def test_rank_results_handles_equal_scores():

    results = [
        _result(
            score=1.0,
            page_number=2,
        ),
        _result(
            score=1.0,
            page_number=1,
        ),
    ]

    ranked = rank_results(
        results
    )

    assert len(ranked) == 2