"""
Tests for Full-Text Search (FTS5).

These tests verify that:

- INSERT triggers populate the FTS index
- UPDATE triggers keep the index synchronized
- DELETE triggers remove rows
- FTS queries return expected paragraphs
- Phrase searches work
- Boolean queries work
- BM25 ranking executes correctly
- FTS rebuild restores synchronization

The tests use only schema.py and repository.py functionality.
"""

from __future__ import annotations

import sqlite3
import repository
import pytest

from database.migrations import apply_schema, rebuild_fts


# ---------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------


@pytest.fixture()
def connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")

    try:
        apply_schema(conn)
    except sqlite3.OperationalError as exc:
        if "fts5" in str(exc).lower():
            pytest.skip("SQLite build lacks FTS5.")
        raise

    conn.execute(
        """
        INSERT INTO documents(
            filename,
            page_count
        )
        VALUES(
            'sample.pdf',
            1
        )
        """
    )

    document_id = conn.execute(
        "SELECT id FROM documents"
    ).fetchone()[0]

    paragraphs = [

        (
            document_id,
            1,
            1,
            "Renewable energy is essential for climate policy.",
            "default",
        ),

        (
            document_id,
            1,
            2,
            "Solar power and wind energy are renewable resources.",
            "default",
        ),

        (
            document_id,
            1,
            3,
            "Healthcare reform remains an important issue.",
            "default",
        ),
    ]

    conn.executemany(
        """
        INSERT INTO paragraphs(
            document_id,
            page_number,
            paragraph_number,
            text,
            chunk_method
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        paragraphs,
    )

    yield conn
    conn.close()


# ---------------------------------------------------------------------
# Trigger synchronization
# ---------------------------------------------------------------------


def test_insert_trigger_updates_fts(connection):
    count = connection.execute(
        "SELECT COUNT(*) FROM paragraphs_fts"
    ).fetchone()[0]

    assert count == 3


def test_delete_trigger_updates_fts(connection):
    connection.execute(
        "DELETE FROM paragraphs WHERE paragraph_number = 3"
    )

    count = connection.execute(
        "SELECT COUNT(*) FROM paragraphs_fts"
    ).fetchone()[0]

    assert count == 2


def test_update_trigger_updates_fts(connection):
    connection.execute(
        """
        UPDATE paragraphs
        SET text='Quantum computing research'
        WHERE paragraph_number=3
        """
    )

    row = connection.execute(
        """
        SELECT rowid
        FROM paragraphs_fts
        WHERE paragraphs_fts MATCH 'quantum'
        """
    ).fetchone()

    assert row is not None


# ---------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------


def test_simple_word_search(connection):
    rows = connection.execute(
        """
        SELECT rowid
        FROM paragraphs_fts
        WHERE paragraphs_fts MATCH 'renewable'
        """
    ).fetchall()

    assert len(rows) == 2


def test_phrase_search(connection):
    rows = connection.execute(
        """
        SELECT rowid
        FROM paragraphs_fts
        WHERE paragraphs_fts MATCH '"solar power"'
        """
    ).fetchall()

    assert len(rows) == 1


def test_boolean_and_query(connection):
    rows = connection.execute(
        """
        SELECT rowid
        FROM paragraphs_fts
        WHERE paragraphs_fts MATCH 'renewable AND energy'
        """
    ).fetchall()

    assert len(rows) == 2


def test_boolean_or_query(connection):
    rows = connection.execute(
        """
        SELECT rowid
        FROM paragraphs_fts
        WHERE paragraphs_fts MATCH 'healthcare OR solar'
        """
    ).fetchall()

    assert len(rows) == 2


def test_boolean_not_query(connection):
    rows = connection.execute(
        """
        SELECT rowid
        FROM paragraphs_fts
        WHERE paragraphs_fts MATCH 'energy NOT solar'
        """
    ).fetchall()

    assert len(rows) == 1


def test_no_results(connection):
    rows = connection.execute(
        """
        SELECT rowid
        FROM paragraphs_fts
        WHERE paragraphs_fts MATCH 'spaceship'
        """
    ).fetchall()

    assert rows == []


# ---------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------


def test_bm25_returns_scores(connection):
    rows = connection.execute(
        """
        SELECT
            rowid,
            bm25(paragraphs_fts)
        FROM paragraphs_fts
        WHERE paragraphs_fts MATCH 'renewable'
        ORDER BY bm25(paragraphs_fts)
        """
    ).fetchall()

    assert len(rows) == 2


# ---------------------------------------------------------------------
# Synchronization
# ---------------------------------------------------------------------


def test_rebuild_fts(connection):
    """rebuild_fts() should synchronize the FTS index with paragraphs."""

    doc_id = _insert_document(connection)

    repository.create_paragraph(
        document_id=doc_id,
        page_number=1,
        paragraph_number=1,
        text="first searchable paragraph",
        chunk_method="unit-test",
        connection=connection,
    )

    repository.create_paragraph(
        document_id=doc_id,
        page_number=1,
        paragraph_number=2,
        text="second searchable paragraph",
        chunk_method="unit-test",
        connection=connection,
    )

    # Rebuilding should be safe even when the index is already populated.
    repository.rebuild_fts(connection)

    assert repository.verify_fts_sync(connection)
    assert repository.paragraph_count(connection) == 2
    assert repository.fts_row_count(connection) == 2


def test_paragraph_and_fts_counts_match(connection):
    paragraphs = connection.execute(
        "SELECT COUNT(*) FROM paragraphs"
    ).fetchone()[0]

    fts = connection.execute(
        "SELECT COUNT(*) FROM paragraphs_fts"
    ).fetchone()[0]

    assert paragraphs == fts


# ---------------------------------------------------------------------
# Unicode / tokenization
# ---------------------------------------------------------------------


def test_unicode_search(connection):
    connection.execute(
        """
        INSERT INTO paragraphs(
            document_id,
            page_number,
            paragraph_number,
            text,
            chunk_method
        )
        VALUES(
            1,
            2,
            1,
            'Café politics',
            'default'
        )
        """
    )

    row = connection.execute(
        """
        SELECT rowid
        FROM paragraphs_fts
        WHERE paragraphs_fts MATCH 'cafe'
        """
    ).fetchone()

    assert row is not None


def test_punctuation_is_ignored(connection):
    connection.execute(
        """
        INSERT INTO paragraphs(
            document_id,
            page_number,
            paragraph_number,
            text,
            chunk_method
        )
        VALUES(
            1,
            2,
            2,
            'Energy, policy: climate!',
            'default'
        )
        """
    )

    row = connection.execute(
        """
        SELECT rowid
        FROM paragraphs_fts
        WHERE paragraphs_fts MATCH 'climate'
        """
    ).fetchone()

    assert row is not None