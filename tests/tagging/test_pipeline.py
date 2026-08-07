"""
Unit tests for tagging.pipeline.

These tests validate:

* conversion helpers
* pipeline layer ordering
* anchor + embedding integration
* LLM verification integration
* tag de-duplication
* batch processing
* persistence adapters
* standalone job execution

All external systems are mocked.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from tagging.embeddings import ParagraphEmbedding
from tagging.embeddings import SimilarityMatch
from tagging.verifier import VerificationResult

from tagging.pipeline import ParagraphTaggingResult
from tagging.pipeline import TopicTag
from tagging.pipeline import TopicTagRepository
from tagging.pipeline import TopicTaggingJob
from tagging.pipeline import TopicTaggingPipeline
from tagging.pipeline import anchor_match_to_tag
from tagging.pipeline import run_topic_tagging_job
from tagging.pipeline import similarity_match_to_tag
from tagging.pipeline import verification_to_tag


# ---------------------------------------------------------------------
# Fake objects
# ---------------------------------------------------------------------


class FakeAnchorMatch:

    def __init__(
        self,
        topic="data_management",
        confidence=0.9,
    ) -> None:

        self.topic = topic
        self.confidence = confidence
        self.layer = "anchor"
        self.matched_phrase = "data management"


class FakeSimilarityTagger:

    def __init__(
        self,
        matches=None,
    ) -> None:

        self.matches = (
            matches
            if matches is not None
            else []
        )

        self.called = False

    def tag(
        self,
        text,
    ):

        self.called = True

        return (
            ParagraphEmbedding(
                vector=np.array(
                    [
                        1.0,
                    ]
                ),
                model="fake-model",
                dimension=1,
            ),
            self.matches,
        )


class FakeVerifier:

    def __init__(
        self,
        result=None,
    ) -> None:

        self.result = result

        self.called = False

    def verify(
        self,
        paragraph,
        candidate,
    ):

        self.called = True

        return self.result


class FakeRepository:

    def __init__(self):

        self.embeddings = []

        self.tags = []

    def save_paragraph_embedding(
        self,
        **kwargs,
    ):

        self.embeddings.append(
            kwargs
        )

    def save_topic_tag(
        self,
        **kwargs,
    ):

        self.tags.append(
            kwargs
        )


# ---------------------------------------------------------------------
# Conversion helpers
# ---------------------------------------------------------------------


def test_anchor_match_to_tag():

    tag = anchor_match_to_tag(
        10,
        FakeAnchorMatch(),
    )

    assert isinstance(
        tag,
        TopicTag,
    )

    assert tag.paragraph_id == 10

    assert tag.topic == "data_management"

    assert tag.layer == "anchor"

    assert tag.verified is False


def test_similarity_match_to_tag():

    match = SimilarityMatch(
        topic="licensing",
        similarity=0.8,
        confidence=0.8,
        matched_phrase="licence",
    )

    tag = similarity_match_to_tag(
        5,
        match,
        "bge-base",
    )

    assert tag.topic == "licensing"

    assert tag.embedding_model == "bge-base"

    assert tag.layer == "embedding"

    assert tag.verified is False


def test_verification_to_tag_accept():

    result = VerificationResult(
        accepted=True,
        topic="governance",
        confidence=0.95,
        reason="matched",
        model="qwen",
    )

    tag = verification_to_tag(
        1,
        result,
    )

    assert tag is not None

    assert tag.topic == "governance"

    assert tag.verified is True

    assert tag.layer == "llm"


def test_verification_to_tag_reject():

    result = VerificationResult(
        accepted=False,
        topic="governance",
        confidence=0.2,
        reason="not relevant",
        model="qwen",
    )

    assert (
        verification_to_tag(
            1,
            result,
        )
        is None
    )


# ---------------------------------------------------------------------
# Pipeline processing
# ---------------------------------------------------------------------


def test_process_paragraph_embedding_only():

    tagger = FakeSimilarityTagger()

    pipeline = TopicTaggingPipeline(
        similarity_tagger=tagger,
        verifier=FakeVerifier(),
    )

    result = pipeline.process_paragraph(
        1,
        "paragraph",
    )

    assert isinstance(
        result,
        ParagraphTaggingResult,
    )

    assert result.paragraph_id == 1

    assert result.embedding.model == "fake-model"

    assert tagger.called is True


def test_process_paragraph_with_embedding_match():

    match = SimilarityMatch(
        topic="data_management",
        similarity=0.95,
        confidence=0.95,
        matched_phrase="data",
    )

    tagger = FakeSimilarityTagger(
        matches=[
            match,
        ]
    )

    pipeline = TopicTaggingPipeline(
        similarity_tagger=tagger,
        verifier=FakeVerifier(),
    )

    result = pipeline.process_paragraph(
        2,
        "paragraph",
    )

    assert len(
        result.tags
    ) == 1

    assert result.tags[0].topic == (
        "data_management"
    )


def test_low_confidence_match_sent_to_verifier(
    monkeypatch: pytest.MonkeyPatch,
):

    match = SimilarityMatch(
        topic="governance",
        similarity=0.72,
        confidence=0.72,
        matched_phrase="governance",
    )

    verifier_result = VerificationResult(
        accepted=True,
        topic="governance",
        confidence=0.85,
        reason="verified",
        model="qwen",
    )

    verifier = FakeVerifier(
        verifier_result,
    )

    pipeline = TopicTaggingPipeline(
        similarity_tagger=FakeSimilarityTagger(
            [
                match,
            ]
        ),
        verifier=verifier,
    )

    result = pipeline.process_paragraph(
        3,
        "paragraph",
    )

    assert verifier.called is True

    assert any(
        tag.layer == "llm"
        for tag in result.tags
    )


# ---------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------


def test_duplicate_tags_keep_highest_confidence():

    pipeline = TopicTaggingPipeline(
        similarity_tagger=FakeSimilarityTagger(),
        verifier=FakeVerifier(),
    )

    tags = [
        TopicTag(
            paragraph_id=1,
            topic="governance",
            confidence=0.70,
            layer="embedding",
            embedding_model="bge",
            verified=False,
        ),
        TopicTag(
            paragraph_id=1,
            topic="governance",
            confidence=0.90,
            layer="llm",
            embedding_model=None,
            verified=True,
        ),
    ]

    result = pipeline._deduplicate_tags(
        tags,
    )

    assert len(result) == 1

    assert result[0].confidence == 0.90

    assert result[0].verified is True


def test_duplicate_tags_keep_verified_when_equal_confidence():

    pipeline = TopicTaggingPipeline(
        similarity_tagger=FakeSimilarityTagger(),
        verifier=FakeVerifier(),
    )

    tags = [
        TopicTag(
            paragraph_id=1,
            topic="licensing",
            confidence=0.80,
            layer="embedding",
            embedding_model="bge",
            verified=False,
        ),
        TopicTag(
            paragraph_id=1,
            topic="licensing",
            confidence=0.80,
            layer="llm",
            embedding_model=None,
            verified=True,
        ),
    ]

    result = pipeline._deduplicate_tags(
        tags,
    )

    assert len(result) == 1

    assert result[0].verified is True


def test_unique_topics_are_preserved():

    pipeline = TopicTaggingPipeline(
        similarity_tagger=FakeSimilarityTagger(),
        verifier=FakeVerifier(),
    )

    tags = [
        TopicTag(
            paragraph_id=1,
            topic="governance",
            confidence=0.8,
            layer="embedding",
            embedding_model="bge",
            verified=False,
        ),
        TopicTag(
            paragraph_id=1,
            topic="licensing",
            confidence=0.7,
            layer="anchor",
            embedding_model=None,
            verified=False,
        ),
    ]

    result = pipeline._deduplicate_tags(
        tags,
    )

    assert len(result) == 2


# ---------------------------------------------------------------------
# Batch processing
# ---------------------------------------------------------------------


def test_process_paragraphs():

    pipeline = TopicTaggingPipeline(
        similarity_tagger=FakeSimilarityTagger(),
        verifier=FakeVerifier(),
    )

    results = pipeline.process_paragraphs(
        [
            (1, "first"),
            (2, "second"),
        ]
    )

    assert len(results) == 2

    assert results[0].paragraph_id == 1

    assert results[1].paragraph_id == 2


def test_process_paragraphs_handles_failure():

    class FailingPipeline(
        TopicTaggingPipeline
    ):

        def process_paragraph(
            self,
            paragraph_id,
            text,
        ):

            raise RuntimeError(
                "failure"
            )

    pipeline = FailingPipeline(
        similarity_tagger=FakeSimilarityTagger(),
        verifier=FakeVerifier(),
    )

    results = pipeline.process_paragraphs(
        [
            (1, "bad"),
        ]
    )

    assert results == []


# ---------------------------------------------------------------------
# Repository persistence
# ---------------------------------------------------------------------


def test_repository_saves_embedding():

    repository = FakeRepository()

    storage = TopicTagRepository(
        repository,
    )

    embedding = ParagraphEmbedding(
        vector=np.array(
            [
                1.0,
                2.0,
            ]
        ),
        model="bge",
        dimension=2,
    )

    storage.save_embedding(
        10,
        embedding,
    )

    assert len(
        repository.embeddings
    ) == 1

    assert repository.embeddings[0][
        "paragraph_id"
    ] == 10

    assert repository.embeddings[0][
        "model"
    ] == "bge"


def test_repository_saves_tags():

    repository = FakeRepository()

    storage = TopicTagRepository(
        repository,
    )

    storage.save_tags(
        [
            TopicTag(
                paragraph_id=1,
                topic="governance",
                confidence=0.9,
                layer="llm",
                embedding_model=None,
                verified=True,
            )
        ]
    )

    assert len(
        repository.tags
    ) == 1

    assert repository.tags[0][
        "topic"
    ] == "governance"


def test_repository_save_result():

    repository = FakeRepository()

    storage = TopicTagRepository(
        repository,
    )

    result = ParagraphTaggingResult(
        paragraph_id=5,
        embedding=ParagraphEmbedding(
            vector=np.array(
                [
                    1.0,
                ]
            ),
            model="bge",
            dimension=1,
        ),
        tags=(
            TopicTag(
                paragraph_id=5,
                topic="management",
                confidence=0.8,
                layer="embedding",
                embedding_model="bge",
                verified=False,
            ),
        ),
    )

    storage.save_result(
        result,
    )

    assert len(
        repository.embeddings
    ) == 1

    assert len(
        repository.tags
    ) == 1


# ---------------------------------------------------------------------
# Job runner
# ---------------------------------------------------------------------


def test_job_runs_pipeline_and_storage():

    class FakePipeline:

        def process_paragraph(
            self,
            paragraph_id,
            text,
        ):

            return ParagraphTaggingResult(
                paragraph_id=paragraph_id,
                embedding=ParagraphEmbedding(
                    vector=np.array(
                        [
                            1.0,
                        ]
                    ),
                    model="fake",
                    dimension=1,
                ),
                tags=(),
            )

    class FakeStorage:

        def __init__(self):

            self.saved = []

        def save_result(
            self,
            result,
        ):

            self.saved.append(
                result
            )

    storage = FakeStorage()

    job = TopicTaggingJob(
        pipeline=FakePipeline(),
        storage=storage,
    )

    count = job.run(
        [
            (1, "one"),
            (2, "two"),
        ]
    )

    assert count == 2

    assert len(
        storage.saved
    ) == 2


def test_job_empty_input():

    class FakePipeline:
        pass

    class FakeStorage:

        def save_result(
            self,
            result,
        ):
            raise AssertionError(
                "should not save"
            )

    job = TopicTaggingJob(
        pipeline=FakePipeline(),
        storage=FakeStorage(),
    )

    assert job.run([]) == 0


# ---------------------------------------------------------------------
# Convenience entry point
# ---------------------------------------------------------------------


def test_run_topic_tagging_job(
    monkeypatch: pytest.MonkeyPatch,
):

    expected = 5

    class FakeJob:

        def run(
            self,
            paragraphs,
        ):

            assert list(
                paragraphs
            ) == [
                (1, "text"),
            ]

            return expected

    monkeypatch.setattr(
        "tagging.pipeline.TopicTaggingJob",
        lambda: FakeJob(),
    )

    result = run_topic_tagging_job(
        [
            (1, "text"),
        ]
    )

    assert result == expected


# ---------------------------------------------------------------------
# Regression tests
# ---------------------------------------------------------------------


def test_result_types():

    result = ParagraphTaggingResult(
        paragraph_id=1,
        embedding=ParagraphEmbedding(
            vector=np.array(
                [
                    1.0,
                ]
            ),
            model="model",
            dimension=1,
        ),
        tags=(),
    )

    assert isinstance(
        result.tags,
        tuple,
    )


def test_public_pipeline_exports():

    import tagging.pipeline as module

    expected = {
        "ParagraphTaggingResult",
        "TopicTag",
        "TopicTagRepository",
        "TopicTaggingJob",
        "TopicTaggingPipeline",
        "run_topic_tagging_job",
        "run_database_topic_tagging",
    }

    assert expected.issubset(
        set(module.__all__)
    )