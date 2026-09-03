"""
Topic anchor detection.

This module implements the first stage of the topic-tagging pipeline.

The anchor layer is intentionally lightweight and deterministic. It detects
candidate topic tags using:

1. Exact matching
2. RapidFuzz fuzzy matching

Later stages (embeddings and LLM verification) may add or reject tags.

No database access occurs in this module.
Persistence is handled exclusively by tagging.pipeline.

The anchor dictionary is defined in core.config so new topics can be added
without modifying this module.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Sequence

from rapidfuzz import fuzz

from core.config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class TopicAnchor:
    """
    Represents a configured topic.

    Attributes
    ----------
    name
        Canonical topic name.

    phrases
        List of phrases representing the topic.
    """

    name: str
    phrases: tuple[str, ...]


@dataclass(slots=True, frozen=True)
class AnchorMatch:
    """
    Candidate topic tag produced by this layer.
    """

    topic: str
    matched_phrase: str
    confidence: float
    layer: str = "anchor"


# ---------------------------------------------------------------------
# Anchor loading
# ---------------------------------------------------------------------


def load_anchor_dictionary() -> tuple[TopicAnchor, ...]:
    """
    Load configured topic anchors.

    Returns
    -------
    tuple[TopicAnchor, ...]

    Raises
    ------
    ValueError
        If configuration is malformed.
    """

    configured = settings.topic_anchors

    anchors: list[TopicAnchor] = []

    for topic, phrases in configured.items():

        if not phrases:
            raise ValueError(
                f"Topic '{topic}' has no configured anchor phrases."
            )

        cleaned = tuple(
            phrase.strip().lower()
            for phrase in phrases
            if phrase.strip()
        )

        anchors.append(
            TopicAnchor(
                name=topic,
                phrases=cleaned,
            )
        )

    return tuple(anchors)


# ---------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------


def normalize_text(text: str) -> str:
    """
    Normalise paragraph text.

    This intentionally performs only light normalisation because OCR
    cleanup has already occurred during ingestion.
    """

    text = text.lower()

    text = re.sub(r"\s+", " ", text)

    return text.strip()


# ---------------------------------------------------------------------
# Matching engine
# ---------------------------------------------------------------------


class AnchorMatcher:
    """
    Detect candidate topic tags.

    Matching order:

    1. Exact phrase search
    2. RapidFuzz fuzzy search

    Each topic appears at most once.
    """

    def __init__(
        self,
        anchors: Sequence[TopicAnchor] | None = None,
        *,
        fuzzy_threshold: int | None = None,
    ) -> None:

        self._anchors = tuple(
            anchors if anchors is not None else load_anchor_dictionary()
        )

        self._threshold = (
            fuzzy_threshold
            if fuzzy_threshold is not None
            else settings.anchor_fuzzy_threshold
        )

    def match(self, paragraph: str) -> list[AnchorMatch]:
        """
        Match paragraph against all configured anchors.
        """

        text = normalize_text(paragraph)

        results: list[AnchorMatch] = []

        for anchor in self._anchors:

            match = self._match_anchor(anchor, text)

            if match is not None:
                results.append(match)

        logger.debug(
            "Anchor layer produced %d candidate tags.",
            len(results),
        )

        return results
    
    def _match_anchor(
        self,
        anchor: TopicAnchor,
        text: str,
    ) -> AnchorMatch | None:

        # -----------------------------------------
        # Exact match
        # -----------------------------------------

        for phrase in anchor.phrases:

            if phrase in text:

                return AnchorMatch(
                    topic=anchor.name,
                    matched_phrase=phrase,
                    confidence=1.0,
                )

        # -----------------------------------------
        # Fuzzy match
        # -----------------------------------------

        score = 0.0
        matched = None

        for phrase in anchor.phrases:

            current = fuzz.partial_ratio(
                phrase,
                text,
            )

            if current > score:
                score = current
                matched = phrase

        if matched is None:
            return None

        if score < self._threshold:
            return None

        return AnchorMatch(
            topic=anchor.name,
            matched_phrase=matched,
            confidence=score / 100.0,
        )


# ---------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------


def detect_topics(paragraph: str) -> list[AnchorMatch]:
    """
    Convenience wrapper.

    Used by the tagging pipeline.
    """

    return AnchorMatcher().match(paragraph)