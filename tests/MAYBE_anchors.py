"""
Unit tests for tagging.anchors.

These tests validate:

* configuration loading
* text normalisation
* tokenisation
* exact matching
* fuzzy matching
* confidence scoring
* duplicate prevention
* batch matching
* convenience wrapper

The embedding and LLM verification layers are tested separately.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from tagging.anchors import AnchorMatcher
from tagging.anchors import AnchorMatch
from tagging.anchors import TopicAnchor
from tagging.anchors import detect_topics
from tagging.anchors import load_anchor_dictionary
from tagging.anchors import match_paragraphs
from tagging.anchors import normalize_text
from tagging.anchors import tokenize


# ---------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------


@pytest.fixture
def anchors() -> tuple[TopicAnchor, ...]:
    return (
        TopicAnchor(
            name="data_management",
            phrases=(
                "data management",
                "information management",
            ),
        ),
        TopicAnchor(
            name="licensing",
            phrases=(
                "creative commons",
                "open licence",
                "licensing",
            ),
        ),
        TopicAnchor(
            name="governance",
            phrases=(
                "data governance",
                "governance framework",
            ),
        ),
    )


@pytest.fixture
def matcher(
    anchors: tuple[TopicAnchor, ...],
) -> AnchorMatcher:
    return AnchorMatcher(
        anchors=anchors,
        fuzzy_threshold=85,
    )


# ---------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------


def test_normalize_text_lowercase() -> None:

    text = "Data MANAGEMENT"

    assert normalize_text(text) == "data management"


def test_normalize_text_collapses_whitespace() -> None:

    text = "Data     management\n\npolicy"

    assert normalize_text(text) == "data management policy"


def test_tokenize() -> None:

    tokens = tokenize(
        "Data-governance improves information management."
    )

    assert tokens == [
        "data-governance",
        "improves",
        "information",
        "management",
    ]


# ---------------------------------------------------------------------
# Dictionary loading
# ---------------------------------------------------------------------


def test_load_anchor_dictionary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    from tagging import anchors as module

    monkeypatch.setattr(
        module,
        "settings",
        SimpleNamespace(
            topic_anchors={
                "licensing": [
                    "Creative Commons",
                    "Open Licence",
                ]
            },
            anchor_fuzzy_threshold=90,
        ),
    )

    loaded = load_anchor_dictionary()

    assert len(loaded) == 1

    assert loaded[0].name == "licensing"

    assert loaded[0].phrases == (
        "creative commons",
        "open licence",
    )


def test_empty_anchor_configuration_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    from tagging import anchors as module

    monkeypatch.setattr(
        module,
        "settings",
        SimpleNamespace(
            topic_anchors={
                "licensing": [],
            },
            anchor_fuzzy_threshold=90,
        ),
    )

    with pytest.raises(ValueError):
        load_anchor_dictionary()


# ---------------------------------------------------------------------
# Exact matching
# ---------------------------------------------------------------------


def test_exact_match(
    matcher: AnchorMatcher,
) -> None:

    paragraph = (
        "The organisation adopted a comprehensive "
        "data management strategy."
    )

    matches = matcher.match(paragraph)

    assert len(matches) == 1

    assert matches[0].topic == "data_management"

    assert matches[0].matched_phrase == "data management"

    assert matches[0].confidence == 1.0

    assert matches[0].layer == "anchor"


def test_multiple_exact_matches(
    matcher: AnchorMatcher,
) -> None:

    paragraph = (
        "The Creative Commons licence supports "
        "good data governance."
    )

    matches = matcher.match(paragraph)

    topics = {m.topic for m in matches}

    assert topics == {
        "licensing",
        "governance",
    }


def test_no_match_returns_empty(
    matcher: AnchorMatcher,
) -> None:

    paragraph = (
        "This paragraph discusses biodiversity."
    )

    assert matcher.match(paragraph) == []


# ---------------------------------------------------------------------
# Fuzzy matching
# ---------------------------------------------------------------------


def test_fuzzy_match_typo(
    matcher: AnchorMatcher,
) -> None:

    paragraph = (
        "The project improved data managment "
        "across the organisation."
    )

    matches = matcher.match(paragraph)

    assert len(matches) == 1

    assert matches[0].topic == "data_management"

    assert matches[0].confidence < 1.0

    assert matches[0].confidence >= 0.85


def test_fuzzy_match_creative_commons_typo(
    matcher: AnchorMatcher,
) -> None:

    paragraph = (
        "Released under Creative Comons."
    )

    matches = matcher.match(paragraph)

    assert len(matches) == 1

    assert matches[0].topic == "licensing"


def test_below_threshold_rejected(
    anchors: tuple[TopicAnchor, ...],
) -> None:

    matcher = AnchorMatcher(
        anchors=anchors,
        fuzzy_threshold=98,
    )

    paragraph = (
        "Data managment policy."
    )

    assert matcher.match(paragraph) == []


# ---------------------------------------------------------------------
# Duplicate prevention
# ---------------------------------------------------------------------


def test_single_topic_only_once(
    matcher: AnchorMatcher,
) -> None:

    paragraph = (
        "Data management is essential. "
        "Effective data management "
        "improves quality."
    )

    matches = matcher.match(paragraph)

    assert len(matches) == 1

    assert matches[0].topic == "data_management"


def test_multiple_anchor_phrases_same_topic(
    matcher: AnchorMatcher,
) -> None:

    paragraph = (
        "Information management and data "
        "management are closely related."
    )

    matches = matcher.match(paragraph)

    topics = [m.topic for m in matches]

    assert topics.count("data_management") == 1


# ---------------------------------------------------------------------
# Batch helper
# ---------------------------------------------------------------------


def test_match_paragraphs(
    matcher: AnchorMatcher,
) -> None:

    paragraphs = [
        "Data management policy.",
        "Creative Commons licence.",
        "Random paragraph.",
    ]

    result = match_paragraphs(
        paragraphs,
        matcher=matcher,
    )

    assert len(result) == 3

    assert len(result[0]) == 1

    assert len(result[1]) == 1

    assert result[2] == []


def test_match_paragraphs_empty(
    matcher: AnchorMatcher,
) -> None:

    assert match_paragraphs(
        [],
        matcher=matcher,
    ) == {}


# ---------------------------------------------------------------------
# Convenience wrapper
# ---------------------------------------------------------------------


def test_detect_topics_uses_default_matcher(
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    expected = [
        AnchorMatch(
            topic="licensing",
            matched_phrase="creative commons",
            confidence=1.0,
        )
    ]

    class FakeMatcher:

        def match(
            self,
            paragraph: str,
        ):

            assert paragraph == "example"

            return expected

    from tagging import anchors as module

    monkeypatch.setattr(
        module,
        "AnchorMatcher",
        FakeMatcher,
    )

    result = detect_topics("example")

    assert result == expected


# ---------------------------------------------------------------------
# Confidence values
# ---------------------------------------------------------------------


def test_confidence_range(
    matcher: AnchorMatcher,
) -> None:

    paragraph = (
        "Data management."
    )

    matches = matcher.match(paragraph)

    assert matches

    assert 0.0 <= matches[0].confidence <= 1.0


def test_anchor_layer_name(
    matcher: AnchorMatcher,
) -> None:

    paragraph = (
        "Creative Commons licensing."
    )

    matches = matcher.match(paragraph)

    assert matches[0].layer == "anchor"


# ---------------------------------------------------------------------
# Regression tests
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "DATA MANAGEMENT",
            "data_management",
        ),
        (
            "Creative Commons",
            "licensing",
        ),
        (
            "data governance",
            "governance",
        ),
    ],
)
def test_regression_exact_matching(
    matcher: AnchorMatcher,
    text: str,
    expected: str,
) -> None:

    matches = matcher.match(text)

    assert matches

    assert matches[0].topic == expected


@pytest.mark.parametrize(
    "text",
    [
        "",
        " ",
        "\n",
        "\t",
    ],
)
def test_empty_inputs(
    matcher: AnchorMatcher,
    text: str,
) -> None:

    assert matcher.match(text) == []