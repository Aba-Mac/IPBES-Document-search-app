"""
Unit tests for tagging.embeddings.

These tests verify:

* vector normalisation
* cosine similarity
* embedding model wrapper
* batch embedding generation
* anchor embedding cache
* similarity tagging
* singleton helpers
* convenience wrappers
* confidence threshold logic

The SentenceTransformer model is fully mocked to ensure the tests are
fast, deterministic and suitable for CI.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from tagging.anchors import TopicAnchor
from tagging.embeddings import AnchorEmbeddingStore
from tagging.embeddings import EmbeddingModel
from tagging.embeddings import ParagraphEmbedding
from tagging.embeddings import SimilarityMatch
from tagging.embeddings import SimilarityTagger
from tagging.embeddings import cosine_similarity
from tagging.embeddings import embed_paragraph
from tagging.embeddings import embed_paragraphs
from tagging.embeddings import get_anchor_store
from tagging.embeddings import get_embedding_model
from tagging.embeddings import get_similarity_tagger
from tagging.embeddings import is_high_confidence
from tagging.embeddings import l2_normalize
from tagging.embeddings import requires_llm_verification
from tagging.embeddings import tag_paragraph
from tagging.embeddings import tag_paragraphs


# ---------------------------------------------------------------------
# Fake SentenceTransformer
# ---------------------------------------------------------------------


class FakeSentenceTransformer:
    """
    Deterministic embedding generator.

    Produces predictable vectors so cosine similarity tests are stable.
    """

    def __init__(
        self,
        model_name: str,
        device: str | None = None,
    ) -> None:

        self.model_name = model_name
        self.device = device

    def encode(
        self,
        texts,
        *,
        normalize_embeddings=True,
        convert_to_numpy=True,
        batch_size=32,
        show_progress_bar=False,
    ):

        if isinstance(texts, str):
            texts = [texts]
            single = True
        else:
            single = False

        vectors = []

        for text in texts:

            length = float(len(text))

            vowels = float(
                sum(
                    c.lower() in "aeiou"
                    for c in text
                )
            )

            spaces = float(text.count(" "))

            vector = np.array(
                [
                    length,
                    vowels,
                    spaces,
                    1.0,
                ],
                dtype=np.float32,
            )

            norm = np.linalg.norm(vector)

            vector = vector / norm

            vectors.append(vector)

        if single:
            return vectors[0]

        return np.asarray(vectors)


# ---------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------


@pytest.fixture
def fake_model(
    monkeypatch: pytest.MonkeyPatch,
):

    from tagging import embeddings as module

    monkeypatch.setattr(
        module,
        "SentenceTransformer",
        FakeSentenceTransformer,
    )

    monkeypatch.setattr(
        module,
        "settings",
        SimpleNamespace(
            embedding_model="fake-model",
            embedding_device="cpu",
            embedding_batch_size=8,
            embedding_similarity_threshold=0.80,
            embedding_low_confidence_min=0.70,
            embedding_low_confidence_max=0.80,
        ),
    )

    return EmbeddingModel()


@pytest.fixture
def anchors():

    return (
        TopicAnchor(
            name="management",
            phrases=(
                "data management",
                "information management",
            ),
        ),
        TopicAnchor(
            name="licensing",
            phrases=(
                "creative commons",
            ),
        ),
    )


@pytest.fixture
def anchor_store(
    fake_model,
    anchors,
):

    return AnchorEmbeddingStore(
        fake_model,
        anchors,
    )


@pytest.fixture
def similarity_tagger(
    fake_model,
    anchor_store,
):

    return SimilarityTagger(
        embedding_model=fake_model,
        anchor_store=anchor_store,
        similarity_threshold=0.75,
    )


# ---------------------------------------------------------------------
# Normalisation utilities
# ---------------------------------------------------------------------


def test_l2_normalize():

    vector = np.array(
        [
            3.0,
            4.0,
        ]
    )

    result = l2_normalize(vector)

    assert np.isclose(
        np.linalg.norm(result),
        1.0,
    )


def test_l2_normalize_zero_vector():

    vector = np.zeros(5)

    result = l2_normalize(vector)

    assert np.array_equal(
        result,
        vector,
    )


# ---------------------------------------------------------------------
# Cosine similarity
# ---------------------------------------------------------------------


def test_cosine_similarity_identical():

    vector = np.array(
        [
            0.5,
            0.5,
        ]
    )

    score = cosine_similarity(
        vector,
        vector,
    )

    assert score == pytest.approx(
        0.5,
    )


def test_cosine_similarity_orthogonal():

    left = np.array(
        [
            1.0,
            0.0,
        ]
    )

    right = np.array(
        [
            0.0,
            1.0,
        ]
    )

    assert cosine_similarity(
        left,
        right,
    ) == pytest.approx(
        0.0,
    )


# ---------------------------------------------------------------------
# Embedding model
# ---------------------------------------------------------------------


def test_model_loaded_lazily(
    fake_model,
):

    model = fake_model.model

    assert isinstance(
        model,
        FakeSentenceTransformer,
    )


def test_embed_single(
    fake_model,
):

    embedding = fake_model.embed(
        "Data management",
    )

    assert isinstance(
        embedding,
        ParagraphEmbedding,
    )

    assert embedding.dimension == 4

    assert embedding.model == "fake-model"

    assert np.isclose(
        np.linalg.norm(
            embedding.vector,
        ),
        1.0,
    )


def test_embed_many(
    fake_model,
):

    embeddings = fake_model.embed_many(
        [
            "one",
            "two",
            "three",
        ]
    )

    assert len(
        embeddings
    ) == 3

    assert all(
        isinstance(
            item,
            ParagraphEmbedding,
        )
        for item in embeddings
    )


def test_embed_many_empty(
    fake_model,
):

    assert (
        fake_model.embed_many(
            [],
        )
        == []
    )


# ---------------------------------------------------------------------
# Anchor cache
# ---------------------------------------------------------------------


def test_anchor_cache_builds(
    anchor_store,
):

    cache = anchor_store.embeddings

    assert len(cache) == 2

    assert "management" in cache

    assert "licensing" in cache

    assert len(
        cache["management"]
    ) == 2


def test_anchor_cache_cached_property(
    anchor_store,
):

    first = anchor_store.embeddings

    second = anchor_store.embeddings

    assert first is second


# ---------------------------------------------------------------------
# Similarity tagging
# ---------------------------------------------------------------------


def test_similarity_returns_embedding(
    similarity_tagger,
):

    embedding, matches = similarity_tagger.tag(
        "Data management policy.",
    )

    assert isinstance(
        embedding,
        ParagraphEmbedding,
    )

    assert isinstance(
        matches,
        list,
    )


def test_similarity_match_type(
    similarity_tagger,
):

    _, matches = similarity_tagger.tag(
        "Creative Commons licence",
    )

    assert all(
        isinstance(
            item,
            SimilarityMatch,
        )
        for item in matches
    )


def test_similarity_sorted(
    similarity_tagger,
):

    _, matches = similarity_tagger.tag(
        "Data management under Creative Commons licensing.",
    )

    scores = [
        match.similarity
        for match in matches
    ]

    assert scores == sorted(
        scores,
        reverse=True,
    )


# ---------------------------------------------------------------------
# Confidence utilities
# ---------------------------------------------------------------------


def test_is_high_confidence_default_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    from tagging import embeddings as module

    monkeypatch.setattr(
        module,
        "settings",
        SimpleNamespace(
            embedding_similarity_threshold=0.80,
            embedding_low_confidence_min=0.70,
            embedding_low_confidence_max=0.80,
        ),
    )

    assert is_high_confidence(0.81)
    assert is_high_confidence(0.80)
    assert not is_high_confidence(0.79)


def test_is_high_confidence_override() -> None:

    assert is_high_confidence(
        0.65,
        threshold=0.60,
    )

    assert not is_high_confidence(
        0.55,
        threshold=0.60,
    )


def test_requires_llm_verification_inside_band(
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    from tagging import embeddings as module

    monkeypatch.setattr(
        module,
        "settings",
        SimpleNamespace(
            embedding_similarity_threshold=0.80,
            embedding_low_confidence_min=0.65,
            embedding_low_confidence_max=0.80,
        ),
    )

    assert requires_llm_verification(0.70)
    assert requires_llm_verification(0.79)


def test_requires_llm_verification_outside_band(
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    from tagging import embeddings as module

    monkeypatch.setattr(
        module,
        "settings",
        SimpleNamespace(
            embedding_similarity_threshold=0.80,
            embedding_low_confidence_min=0.65,
            embedding_low_confidence_max=0.80,
        ),
    )

    assert not requires_llm_verification(0.64)

    assert not requires_llm_verification(0.81)


# ---------------------------------------------------------------------
# Batch tagging
# ---------------------------------------------------------------------


def test_tag_many(
    similarity_tagger: SimilarityTagger,
) -> None:

    results = similarity_tagger.tag_many(
        [
            "Data management.",
            "Creative Commons licence.",
            "Random paragraph.",
        ]
    )

    assert len(results) == 3

    assert isinstance(
        results[0][0],
        ParagraphEmbedding,
    )

    assert isinstance(
        results[0][1],
        list,
    )


def test_tag_many_empty(
    similarity_tagger: SimilarityTagger,
) -> None:

    assert similarity_tagger.tag_many([]) == {}


# ---------------------------------------------------------------------
# Convenience wrappers
# ---------------------------------------------------------------------


def test_embed_paragraph_wrapper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    expected = ParagraphEmbedding(
        vector=np.array([1.0]),
        model="fake",
        dimension=1,
    )

    class FakeModel:

        def embed(self, text: str):

            assert text == "paragraph"

            return expected

    monkeypatch.setattr(
        "tagging.embeddings.get_embedding_model",
        lambda: FakeModel(),
    )

    assert embed_paragraph("paragraph") == expected


def test_embed_paragraphs_wrapper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    expected = [
        ParagraphEmbedding(
            vector=np.array([1.0]),
            model="fake",
            dimension=1,
        )
    ]

    class FakeModel:

        def embed_many(self, texts):

            assert texts == ["a"]

            return expected

    monkeypatch.setattr(
        "tagging.embeddings.get_embedding_model",
        lambda: FakeModel(),
    )

    assert embed_paragraphs(["a"]) == expected


def test_tag_paragraph_wrapper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    expected = (
        ParagraphEmbedding(
            vector=np.array([1.0]),
            model="fake",
            dimension=1,
        ),
        [],
    )

    class FakeTagger:

        def tag(self, paragraph):

            assert paragraph == "example"

            return expected

    monkeypatch.setattr(
        "tagging.embeddings.get_similarity_tagger",
        lambda: FakeTagger(),
    )

    assert tag_paragraph("example") == expected


def test_tag_paragraphs_wrapper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    expected = {
        0: (
            ParagraphEmbedding(
                vector=np.array([1.0]),
                model="fake",
                dimension=1,
            ),
            [],
        )
    }

    class FakeTagger:

        def tag_many(self, paragraphs):

            assert paragraphs == ["example"]

            return expected

    monkeypatch.setattr(
        "tagging.embeddings.get_similarity_tagger",
        lambda: FakeTagger(),
    )

    assert tag_paragraphs(["example"]) == expected


# ---------------------------------------------------------------------
# Singleton helpers
# ---------------------------------------------------------------------


def test_embedding_model_singleton(
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    from tagging import embeddings as module

    module._default_model = None

    monkeypatch.setattr(
        module,
        "EmbeddingModel",
        lambda: object(),
    )

    first = get_embedding_model()

    second = get_embedding_model()

    assert first is second


def test_anchor_store_singleton(
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    from tagging import embeddings as module

    module._default_store = None

    sentinel = object()

    monkeypatch.setattr(
        module,
        "AnchorEmbeddingStore",
        lambda model: sentinel,
    )

    monkeypatch.setattr(
        module,
        "get_embedding_model",
        lambda: object(),
    )

    assert get_anchor_store() is sentinel

    assert get_anchor_store() is sentinel


def test_similarity_tagger_singleton(
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    from tagging import embeddings as module

    module._default_tagger = None

    sentinel = object()

    monkeypatch.setattr(
        module,
        "SimilarityTagger",
        lambda **kwargs: sentinel,
    )

    monkeypatch.setattr(
        module,
        "get_embedding_model",
        lambda: object(),
    )

    monkeypatch.setattr(
        module,
        "get_anchor_store",
        lambda: object(),
    )

    assert get_similarity_tagger() is sentinel

    assert get_similarity_tagger() is sentinel


# ---------------------------------------------------------------------
# Regression tests
# ---------------------------------------------------------------------


def test_embedding_dimension(
    fake_model: EmbeddingModel,
) -> None:

    embedding = fake_model.embed(
        "abc",
    )

    assert embedding.dimension == 4


def test_embedding_model_name(
    fake_model: EmbeddingModel,
) -> None:

    embedding = fake_model.embed(
        "abc",
    )

    assert embedding.model == "fake-model"


def test_similarity_match_layer(
    similarity_tagger: SimilarityTagger,
) -> None:

    _, matches = similarity_tagger.tag(
        "Creative Commons licence",
    )

    for match in matches:

        assert match.layer == "embedding"


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
    similarity_tagger: SimilarityTagger,
    text: str,
) -> None:

    embedding, matches = similarity_tagger.tag(
        text,
    )

    assert isinstance(
        embedding,
        ParagraphEmbedding,
    )

    assert isinstance(
        matches,
        list,
    )


def test_public_exports() -> None:

    from tagging import embeddings

    expected = {
        "AnchorEmbeddingStore",
        "EmbeddingModel",
        "ParagraphEmbedding",
        "SimilarityMatch",
        "SimilarityTagger",
        "cosine_similarity",
        "embed_paragraph",
        "embed_paragraphs",
        "get_anchor_store",
        "get_embedding_model",
        "get_similarity_tagger",
        "is_high_confidence",
        "l2_normalize",
        "requires_llm_verification",
        "tag_paragraph",
        "tag_paragraphs",
    }

    assert expected.issubset(
        set(embeddings.__all__)
    )