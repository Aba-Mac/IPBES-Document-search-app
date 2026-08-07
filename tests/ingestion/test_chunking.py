### `tests/ingestion/test_chunking.py`

"""
Tests for chunking module.
"""

from unittest.mock import MagicMock

import pytest

from chunking import (
    ChunkCandidate,
    ParagraphChunk,
    _langchain_fallback,
    _requires_fallback,
    chunk_document,
)


def test_requires_fallback_for_large_chunk():
    candidate = ChunkCandidate(
        text="x" * 5000,
        page_numbers=(1,),
        section_title="Large section",
    )

    assert _requires_fallback(
        candidate,
        max_chunk_characters=4000,
        max_pages_per_chunk=5,
    )


def test_requires_fallback_for_many_pages():
    candidate = ChunkCandidate(
        text="short",
        page_numbers=(1, 2, 3, 4, 5, 6),
        section_title=None,
    )

    assert _requires_fallback(
        candidate,
        max_chunk_characters=4000,
        max_pages_per_chunk=5,
    )


def test_small_chunk_does_not_require_fallback():

    candidate = ChunkCandidate(
        text="normal text",
        page_numbers=(1,),
        section_title=None,
    )

    assert not _requires_fallback(
        candidate,
        max_chunk_characters=4000,
        max_pages_per_chunk=5,
    )


def test_langchain_fallback_splits_large_text():

    candidate = ChunkCandidate(
        text="A " * 3000,
        page_numbers=(1,),
        section_title="Section",
    )

    result = _langchain_fallback(candidate)

    assert len(result) > 1

    assert all(
        isinstance(item, ChunkCandidate)
        for item in result
    )


def test_chunk_document_returns_database_objects(monkeypatch):

    fake_element = MagicMock()

    fake_element.text = "Example paragraph"

    fake_chunk = ChunkCandidate(
        text="Example paragraph",
        page_numbers=(4,),
        section_title="Intro",
    )

    monkeypatch.setattr(
        "chunking._chunk_by_title",
        lambda elements: [fake_chunk],
    )

    result = chunk_document(
        document_id=10,
        elements=[fake_element],
    )

    assert len(result) == 1

    chunk = result[0]

    assert isinstance(
        chunk,
        ParagraphChunk,
    )

    assert chunk.document_id == 10
    assert chunk.page_number == 4
    assert chunk.paragraph_number == 1
    assert chunk.chunk_method == "chunk_by_title"


def test_fallback_chunks_are_marked_correctly(monkeypatch):

    oversized = ChunkCandidate(
        text="x" * 5000,
        page_numbers=(2,),
        section_title="Long",
    )

    monkeypatch.setattr(
        "chunking._chunk_by_title",
        lambda elements: [oversized],
    )

    monkeypatch.setattr(
        "chunking._langchain_fallback",
        lambda candidate: [
            ChunkCandidate(
                text="part one",
                page_numbers=(2,),
                section_title="Long",
            )
        ],
    )

    result = chunk_document(
        document_id=5,
        elements=[],
    )

    assert result[0].chunk_method == "langchain_fallback"