"""
Tests for database.migrations.

These tests verify that schema migration, validation, and FTS maintenance
behave correctly. They intentionally test migrations.py independently from
repository.py.
"""

from __future__ import annotations

import sqlite3

import pytest

from database.migrations import (
    _existing_objects,
    _fts_is_populated,
    apply_schema,
    optimize_fts,
    rebuild_fts,
    validate_schema,
)


# ---------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------


@pytest.fixture()
def connection() -> sqlite3.Connection:
    """
    Fresh in-memory database.
    """
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")

    try:
        apply_schema(conn)
    except sqlite3.OperationalError as exc:
        if "fts5" in str(exc).lower():
            pytest.skip("SQLite build does not support FTS5.")
        raise

    yield conn
    conn.close()


# ---------------------------------------------------------------------
# apply_schema()
# ---------------------------------------------------------------------


def test_apply_schema_creates_tables(connection):
    tables = _existing_objects(connection, "table")

    assert "documents" in tables
    assert "paragraphs" in tables
    assert "terms" in tables
    assert "anchors" in tables
    assert "embeddings" in tables


def test_apply_schema_is_idempotent(connection):
    apply_schema(connection)
    apply_schema(connection)

    tables = _existing_objects(connection, "table")

    assert "documents" in tables


# ---------------------------------------------------------------------
# validate_schema()
# ---------------------------------------------------------------------


def test_validate_schema_passes(connection):
    validate_schema(connection)


def test_validate_schema_missing_table():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row

    with pytest.raises(RuntimeError):
        validate_schema(conn)

    conn.close()


def test_validate_schema_missing_trigger():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row

    apply_schema(conn)

    conn.execute("DROP TRIGGER paragraphs_ai")

    with pytest.raises(RuntimeError, match="Missing triggers"):
        validate_schema(conn)

    conn.close()


def test_validate_schema_missing_fts():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row

    conn.execute(
        """
        CREATE TABLE documents(
            id INTEGER PRIMARY KEY,
            filename TEXT,
            page_count INTEGER
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE paragraphs(
            id INTEGER PRIMARY KEY,
            document_id INTEGER,
            page_number INTEGER,
            paragraph_number INTEGER,
            text TEXT,
            chunk_method TEXT
        )
        """
    )

    conn.execute("CREATE TABLE terms(id INTEGER PRIMARY KEY)")
    conn.execute("CREATE TABLE paragraph_terms(id INTEGER PRIMARY KEY)")
    conn.execute("CREATE TABLE anchors(id INTEGER PRIMARY KEY)")
    conn.execute("CREATE TABLE paragraph_anchors(id INTEGER PRIMARY KEY)")
    conn.execute("CREATE TABLE embeddings(id INTEGER PRIMARY KEY)")

    conn.execute(
        """
        CREATE TRIGGER paragraphs_ai
        AFTER INSERT ON paragraphs
        BEGIN
        SELECT 1;
        END;
        """
    )

    conn.execute(
        """
        CREATE TRIGGER paragraphs_ad
        AFTER DELETE ON paragraphs
        BEGIN
        SELECT 1;
        END;
        """
    )

    conn.execute(
        """
        CREATE TRIGGER paragraphs_au
        AFTER UPDATE ON paragraphs
        BEGIN
        SELECT 1;
        END;
        """
    )

    with pytest.raises(RuntimeError, match="FTS5"):
        validate_schema(conn)

    conn.close()


# ---------------------------------------------------------------------
# _existing_objects()
# ---------------------------------------------------------------------


def test_existing_objects_returns_tables(connection):
    tables = _existing_objects(connection, "table")

    assert isinstance(tables, set)
    assert "documents" in tables


def test_existing_objects_returns_triggers(connection):
    triggers = _existing_objects(connection, "trigger")

    assert "paragraphs_ai" in triggers
    assert "paragraphs_ad" in triggers
    assert "paragraphs_au" in triggers


# ---------------------------------------------------------------------
# FTS population detection
# ---------------------------------------------------------------------


def test_fts_is_empty_initially(connection):
    assert _fts_is_populated(connection) is False


def test_fts_is_populated_after_insert(connection):
    connection.execute(
        """
        INSERT INTO documents(filename, page_count)
        VALUES('doc.pdf', 1)
        """
    )

    document_id = connection.execute(
        "SELECT id FROM documents"
    ).fetchone()[0]

    connection.execute(
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
        (
            document_id,
            1,
            1,
            "Energy policy",
            "default",
        ),
    )

    assert _fts_is_populated(connection) is True


# ---------------------------------------------------------------------
# FTS maintenance
# ---------------------------------------------------------------------


def test_rebuild_fts_executes(connection):
    rebuild_fts(connection)


def test_optimize_fts_executes(connection):
    optimize_fts(connection)


def test_rebuild_fts_after_data(connection):
    connection.execute(
        """
        INSERT INTO documents(filename, page_count)
        VALUES('sample.pdf', 1)
        """
    )

    document_id = connection.execute(
        "SELECT id FROM documents"
    ).fetchone()[0]

    connection.execute(
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
        (
            document_id,
            1,
            1,
            "renewable energy",
            "default",
        ),
    )

    rebuild_fts(connection)

    count = connection.execute(
        "SELECT COUNT(*) FROM paragraphs_fts"
    ).fetchone()[0]

    assert count == 1