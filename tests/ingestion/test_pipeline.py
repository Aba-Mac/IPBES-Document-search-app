"""
Tests for ingestion.pipeline.

These tests focus on the orchestration logic rather than the individual
processing modules. Every pipeline dependency is mocked so the tests are
fast and deterministic.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest

from ingestion.pipeline import (
    IngestionResult,
    calculate_file_hash,
    ingest_directory,
    ingest_paths,
    needs_reindex,
    reindex_document,
)


# ---------------------------------------------------------------------------
# calculate_file_hash
# ---------------------------------------------------------------------------


def test_calculate_file_hash(tmp_path):
    pdf = tmp_path / "sample.pdf"
    pdf.write_bytes(b"hello world")

    digest1 = calculate_file_hash(pdf)
    digest2 = calculate_file_hash(pdf)

    assert digest1 == digest2
    assert len(digest1) == 64


# ---------------------------------------------------------------------------
# needs_reindex
# ---------------------------------------------------------------------------


def test_needs_reindex_new_document(monkeypatch):
    from ingestion import pipeline

    monkeypatch.setattr(
        pipeline.repository,
        "get_document_by_filename",
        lambda _: None,
    )

    needs, doc_id = needs_reindex(Path("example.pdf"))

    assert needs is True
    assert doc_id is None


def test_needs_reindex_existing_without_hash(monkeypatch):
    from ingestion import pipeline

    monkeypatch.setattr(
        pipeline.repository,
        "get_document_by_filename",
        lambda _: {
            "id": 7,
        },
    )

    needs, doc_id = needs_reindex(Path("example.pdf"))

    assert needs is False
    assert doc_id == 7


def test_needs_reindex_same_hash(monkeypatch):
    from ingestion import pipeline

    monkeypatch.setattr(
        pipeline.repository,
        "get_document_by_filename",
        lambda _: {
            "id": 3,
            "source_hash": "abc",
        },
    )

    monkeypatch.setattr(
        pipeline,
        "calculate_file_hash",
        lambda _: "abc",
    )

    needs, doc_id = needs_reindex(Path("example.pdf"))

    assert needs is False
    assert doc_id == 3


def test_needs_reindex_changed_hash(monkeypatch):
    from ingestion import pipeline

    monkeypatch.setattr(
        pipeline.repository,
        "get_document_by_filename",
        lambda _: {
            "id": 3,
            "source_hash": "old",
        },
    )

    monkeypatch.setattr(
        pipeline,
        "calculate_file_hash",
        lambda _: "new",
    )

    needs, doc_id = needs_reindex(Path("example.pdf"))

    assert needs is True
    assert doc_id == 3


# ---------------------------------------------------------------------------
# ingest_paths
# ---------------------------------------------------------------------------


def test_ingest_paths(monkeypatch):
    from ingestion import pipeline

    calls = []

    def fake_ingest(path, *, terms_csv):
        calls.append(Path(path).name)

        return IngestionResult(
            document_id=1,
            paragraphs=5,
            glossary_matches=2,
        )

    monkeypatch.setattr(
        pipeline,
        "ingest_document",
        fake_ingest,
    )

    results = ingest_paths(
        [
            "a.pdf",
            "b.pdf",
        ],
        terms_csv="terms.csv",
    )

    assert len(results) == 2
    assert calls == ["a.pdf", "b.pdf"]


# ---------------------------------------------------------------------------
# ingest_directory
# ---------------------------------------------------------------------------


def test_ingest_directory(tmp_path, monkeypatch):
    from ingestion import pipeline

    (tmp_path / "one.pdf").write_text("")
    (tmp_path / "two.pdf").write_text("")
    (tmp_path / "ignore.txt").write_text("")

    monkeypatch.setattr(
        pipeline,
        "ingest_document",
        lambda *args, **kwargs: IngestionResult(
            document_id=1,
            paragraphs=1,
            glossary_matches=0,
        ),
    )

    results = ingest_directory(
        tmp_path,
        terms_csv="terms.csv",
        recursive=False,
    )

    assert len(results) == 2


def test_ingest_directory_missing():
    with pytest.raises(FileNotFoundError):
        ingest_directory(
            Path("does_not_exist"),
            terms_csv="terms.csv",
        )


# ---------------------------------------------------------------------------
# reindex_document
# ---------------------------------------------------------------------------


def test_reindex_document_existing(monkeypatch):
    from ingestion import pipeline

    deleted = []

    monkeypatch.setattr(
        pipeline.repository,
        "get_document_by_filename",
        lambda _: {"id": 99},
    )

    monkeypatch.setattr(
        pipeline.repository,
        "delete_document",
        lambda doc_id: deleted.append(doc_id),
    )

    monkeypatch.setattr(
        pipeline,
        "ingest_document",
        lambda *args, **kwargs: IngestionResult(
            document_id=99,
            paragraphs=4,
            glossary_matches=1,
            updated=True,
        ),
    )

    result = reindex_document(
        "example.pdf",
        terms_csv="terms.csv",
    )

    assert deleted == [99]
    assert result.document_id == 99


def test_reindex_document_new(monkeypatch):
    from ingestion import pipeline

    monkeypatch.setattr(
        pipeline.repository,
        "get_document_by_filename",
        lambda _: None,
    )

    monkeypatch.setattr(
        pipeline,
        "ingest_document",
        lambda *args, **kwargs: IngestionResult(
            document_id=5,
            paragraphs=3,
            glossary_matches=2,
        ),
    )

    result = reindex_document(
        "example.pdf",
        terms_csv="terms.csv",
    )

    assert result.document_id == 5


# ---------------------------------------------------------------------------
# IngestionResult
# ---------------------------------------------------------------------------


def test_ingestion_result_defaults():
    result = IngestionResult(
        document_id=1,
        paragraphs=10,
        glossary_matches=4,
    )

    assert result.updated is False
    assert result.skipped is False