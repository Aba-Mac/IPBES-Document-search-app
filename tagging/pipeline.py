"""
Topic tagging pipeline orchestration.

This module coordinates the three topic-tagging layers:

1. Anchor matching
   - deterministic dictionary matching
   - rapidfuzz fuzzy matching

2. Embedding similarity
   - BAAI/bge-base-en-v1.5 embeddings
   - cosine similarity against anchor embeddings

3. LLM verification
   - Ollama qwen2.5:7B-instruct verification
   - only applied to low-confidence embedding matches

The pipeline:

- reads paragraphs from the database repository layer
- generates topic tags
- stores topic tags and embeddings
- does not affect live search ranking

This module is intended to run as an independent batch job.

It must not be required when starting the Shiny application.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from tagging.anchors import AnchorMatch
from tagging.anchors import detect_topics
from tagging.embeddings import ParagraphEmbedding
from tagging.embeddings import SimilarityMatch
from tagging.embeddings import SimilarityTagger
from tagging.embeddings import get_similarity_tagger
from tagging.embeddings import requires_llm_verification
from tagging.verifier import VerificationResult
from tagging.verifier import TagVerifier
from tagging.verifier import get_verifier

from database import repository

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class TopicTag:
    """
    Persistable topic tag.

    Attributes
    ----------
    paragraph_id
        Database paragraph identifier.

    topic
        Topic label.

    confidence
        Confidence score.

    layer
        Detection layer.

    embedding_model
        Embedding model used.

    verified
        Whether LLM verification occurred.
    """

    paragraph_id: int
    topic: str
    confidence: float
    layer: str
    embedding_model: str | None
    verified: bool


@dataclass(slots=True, frozen=True)
class ParagraphTaggingResult:
    """
    Complete tagging result for one paragraph.
    """

    paragraph_id: int

    embedding: ParagraphEmbedding

    tags: tuple[TopicTag, ...]


# ---------------------------------------------------------------------
# Conversion helpers
# ---------------------------------------------------------------------


def anchor_match_to_tag(
    paragraph_id: int,
    match: AnchorMatch,
) -> TopicTag:
    """
    Convert deterministic anchor matches into persistable tags.
    """

    return TopicTag(
        paragraph_id=paragraph_id,
        topic=match.topic,
        confidence=match.confidence,
        layer=match.layer,
        embedding_model=None,
        verified=False,
    )


def similarity_match_to_tag(
    paragraph_id: int,
    match: SimilarityMatch,
    embedding_model: str,
) -> TopicTag:
    """
    Convert embedding matches into persistable tags.
    """

    return TopicTag(
        paragraph_id=paragraph_id,
        topic=match.topic,
        confidence=match.confidence,
        layer=match.layer,
        embedding_model=embedding_model,
        verified=False,
    )


def verification_to_tag(
    paragraph_id: int,
    result: VerificationResult,
) -> TopicTag | None:
    """
    Convert accepted LLM verification results into tags.
    """

    if not result.accepted:
        return None

    return TopicTag(
        paragraph_id=paragraph_id,
        topic=result.topic,
        confidence=result.confidence,
        layer=result.layer,
        embedding_model=None,
        verified=True,
    )


# ---------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------


class TopicTaggingPipeline:
    """
    Executes topic tagging for database paragraphs.

    Dependencies are injected to simplify testing.
    """

    def __init__(
        self,
        *,
        similarity_tagger: SimilarityTagger | None = None,
        verifier: TagVerifier | None = None,
        repository_module=None,
    ) -> None:

        self._similarity_tagger = (
            similarity_tagger
            or get_similarity_tagger()
        )

        self._verifier = (
            verifier
            or get_verifier()
        )

        self._repository = (
            repository_module
            or repository
        )

    # --------------------------------------------------------------

    def process_paragraph(
        self,
        paragraph_id: int,
        text: str,
    ) -> ParagraphTaggingResult:
        """
        Process a single paragraph.

        Execution order:

        1. Anchor layer
        2. Embedding layer
        3. LLM verification for uncertain cases
        """

        tags: list[TopicTag] = []

        # ----------------------------------------------------------
        # Layer 1: direct anchor matching
        # ----------------------------------------------------------

        anchor_matches = detect_topics(
            text,
        )

        for match in anchor_matches:

            tags.append(
                anchor_match_to_tag(
                    paragraph_id,
                    match,
                )
            )

        # ----------------------------------------------------------
        # Layer 2: embeddings
        # ----------------------------------------------------------

        embedding, semantic_matches = (
            self._similarity_tagger.tag(text)
        )

        for match in semantic_matches:

            tags.append(
                similarity_match_to_tag(
                    paragraph_id,
                    match,
                    embedding.model,
                )
            )

        return ParagraphTaggingResult(
            paragraph_id=paragraph_id,
            embedding=embedding,
            tags=tuple(tags),
        )


        # ----------------------------------------------------------
        # Layer 3: LLM verification
        # ----------------------------------------------------------

        verified_tags: list[TopicTag] = []

        for match in semantic_matches:

            if not requires_llm_verification(
                match.similarity,
            ):
                continue

            verification = self._verifier.verify(
                text,
                match,
            )

            verified = verification_to_tag(
                paragraph_id,
                verification,
            )

            if verified is not None:
                verified_tags.append(
                    verified
                )

        # ----------------------------------------------------------
        # Merge results
        # ----------------------------------------------------------

        tags.extend(
            verified_tags
        )

        tags = self._deduplicate_tags(
            tags,
        )

        return ParagraphTaggingResult(
            paragraph_id=paragraph_id,
            embedding=embedding,
            tags=tuple(tags),
        )

    # --------------------------------------------------------------

    @staticmethod
    def _deduplicate_tags(
        tags: Iterable[TopicTag],
    ) -> list[TopicTag]:
        """
        Remove duplicate topic tags.

        When multiple layers produce the same topic, the highest
        confidence result is retained.

        Priority is therefore:

        1. highest confidence
        2. verified result
        3. latest processing layer
        """

        grouped: dict[str, TopicTag] = {}

        for tag in tags:

            existing = grouped.get(
                tag.topic
            )

            if existing is None:

                grouped[tag.topic] = tag

                continue

            existing_score = (
                existing.confidence,
                int(existing.verified),
            )

            candidate_score = (
                tag.confidence,
                int(tag.verified),
            )

            if candidate_score > existing_score:

                grouped[tag.topic] = tag

        return list(
            grouped.values()
        )

    # --------------------------------------------------------------

    def process_paragraphs(
        self,
        paragraphs: Iterable[tuple[int, str]],
    ) -> list[ParagraphTaggingResult]:
        """
        Process multiple paragraphs.

        Parameters
        ----------
        paragraphs

            Iterable of:

                (paragraph_id, paragraph_text)

        Returns
        -------
        list[ParagraphTaggingResult]
        """

        results: list[ParagraphTaggingResult] = []

        for paragraph_id, text in paragraphs:

            try:

                results.append(
                    self.process_paragraph(
                        paragraph_id,
                        text,
                    )
                )

            except Exception:

                logger.exception(
                    "Failed tagging paragraph %s",
                    paragraph_id,
                )

        return results


# ---------------------------------------------------------------------
# Database persistence
# ---------------------------------------------------------------------


class TopicTagRepository:
    """
    Database persistence adapter.

    This wrapper keeps database operations isolated from the tagging
    logic and allows repository implementations to evolve.
    """

    def __init__(
        self,
        repository_module=None,
    ) -> None:

        self._repository = (
            repository_module
            or repository
        )

    # --------------------------------------------------------------

    def save_embedding(
        self,
        paragraph_id: int,
        embedding: ParagraphEmbedding,
    ) -> None:
        """
        Persist paragraph embedding.

        The repository layer owns the actual SQL implementation.
        """

        self._repository.save_paragraph_embedding(
            paragraph_id=paragraph_id,
            vector=embedding.vector,
            model=embedding.model,
            dimension=embedding.dimension,
        )

    # --------------------------------------------------------------

    def save_tags(
        self,
        tags: Iterable[TopicTag],
    ) -> None:
        """
        Persist generated topic tags.
        """

        for tag in tags:

            self._repository.save_topic_tag(
                paragraph_id=tag.paragraph_id,
                topic=tag.topic,
                confidence=tag.confidence,
                layer=tag.layer,
                embedding_model=tag.embedding_model,
                verified=tag.verified,
            )

    # --------------------------------------------------------------

    def save_result(
        self,
        result: ParagraphTaggingResult,
    ) -> None:
        """
        Persist complete tagging result.
        """

        self.save_embedding(
            result.paragraph_id,
            result.embedding,
        )

        self.save_tags(
            result.tags,
        )


# ---------------------------------------------------------------------
# Batch runner
# ---------------------------------------------------------------------


class TopicTaggingJob:
    """
    Standalone batch job runner.

    Intended usage:

        python -m tagging.pipeline

    The job is independent of:

    - Shiny startup
    - live search
    - UI rendering
    """

    def __init__(
        self,
        *,
        pipeline: TopicTaggingPipeline | None = None,
        storage: TopicTagRepository | None = None,
    ) -> None:

        self._pipeline = (
            pipeline
            or TopicTaggingPipeline()
        )

        self._storage = (
            storage
            or TopicTagRepository()
        )

    # --------------------------------------------------------------

    def run(
        self,
        paragraphs: Iterable[tuple[int, str]],
    ) -> int:
        """
        Execute the tagging batch.

        Returns
        -------
        int

            Number of successfully processed paragraphs.
        """

        processed = 0

        for paragraph_id, text in paragraphs:

            result = self._pipeline.process_paragraph(
                paragraph_id,
                text,
            )

            self._storage.save_result(
                result,
            )

            processed += 1

        logger.info(
            "Topic tagging completed for %d paragraphs.",
            processed,
        )

        return processed


# ---------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------


def run_topic_tagging_job(
    paragraphs: Iterable[tuple[int, str]],
) -> int:
    """
    Convenience batch entry point.

    This function is intended for scripts, scheduled jobs,
    or manual maintenance runs.
    """

    return TopicTaggingJob().run(
        paragraphs,
    )


def run_database_topic_tagging() -> int:
    """
    Run tagging against all untagged paragraphs.

    The repository implementation decides how paragraphs are selected.
    """

    paragraphs = repository.iter_tagging_candidates()

    return run_topic_tagging_job(
        paragraphs,
    )


# ---------------------------------------------------------------------
# Command-line execution
# ---------------------------------------------------------------------


def main() -> None:
    """
    CLI entry point.
    """

    started = datetime.utcnow()

    logger.info(
        "Starting topic tagging batch at %s",
        started.isoformat(),
    )

    count = run_database_topic_tagging()

    finished = datetime.utcnow()

    logger.info(
        "Finished topic tagging batch. "
        "Processed=%s Duration=%s",
        count,
        finished - started,
    )


# ---------------------------------------------------------------------
# Public exports
# ---------------------------------------------------------------------

__all__ = [
    "ParagraphTaggingResult",
    "TopicTag",
    "TopicTagRepository",
    "TopicTaggingJob",
    "TopicTaggingPipeline",
    "anchor_match_to_tag",
    "main",
    "run_database_topic_tagging",
    "run_topic_tagging_job",
    "similarity_match_to_tag",
    "verification_to_tag",
]


if __name__ == "__main__":
    main()