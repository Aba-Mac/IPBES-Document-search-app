"""
Tests for database.schema.

These tests validate that the raw schema can be applied to a fresh SQLite
database and that all expected objects are created correctly.

They intentionally test schema.py independently of migrations.py.
"""

from __future__ import annotations

import sqlite3

import pytest

from database.schema import iter_schema


# ---------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------


@pytest.fixture()
def connection() -> sqlite3.Connection:
    """
    Fresh in-memory database with schema applied.
    """
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row

    conn.execute("PRAGMA foreign_keys = ON;")

    try:
        for statement in iter_schema():
            conn.executescript(statement)
    except sqlite3.OperationalError as exc:
        if "fts5" in str(exc).lower():
            pytest.skip("SQLite build does not support FTS5.")
        raise

    yield conn
    conn.close()


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------


def sqlite_objects(
    connection: sqlite3.Connection,
    object_type: str,
) -> set[str]:
    rows = connection.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = ?
        """,
        (object_type,),
    ).fetchall()

    return {row["name"] for row in rows}


# ---------------------------------------------------------------------
# iter_schema()
# ---------------------------------------------------------------------


def test_iter_schema_returns_list():
    schema = iter_schema()

    assert isinstance(schema, list)
    assert schema


def test_iter_schema_contains_strings():
    schema = iter_schema()

    assert all(isinstance(statement, str) for statement in schema)


# ---------------------------------------------------------------------
# Schema execution
# ---------------------------------------------------------------------


def test_schema_can_be_applied_twice():
    conn = sqlite3.connect(":memory:")

    conn.execute("PRAGMA foreign_keys = ON;")

    try:
        for _ in range(2):
            for statement in iter_schema():
                conn.executescript(statement)
    except sqlite3.OperationalError as exc:
        if "fts5" in str(exc).lower():
            pytest.skip("SQLite build does not support FTS5.")
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------


def test_expected_tables_exist(connection):
    expected = {
        "documents",
        "paragraphs",
        "metadata_provenance",
        "terms",
        "paragraph_terms",
        "anchors",
        "paragraph_anchors",
        "embeddings",
    }

    tables = sqlite_objects(connection, "table")

    assert expected.issubset(tables)


def test_fts_virtual_table_exists(connection):
    row = connection.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type='table'
        AND name='paragraphs_fts'
        """
    ).fetchone()

    assert row is not None


# ---------------------------------------------------------------------
# Triggers
# ---------------------------------------------------------------------


def test_expected_triggers_exist(connection):
    expected = {
        "paragraphs_ai",
        "paragraphs_ad",
        "paragraphs_au",
    }

    triggers = sqlite_objects(connection, "trigger")

    assert expected.issubset(triggers)


# ---------------------------------------------------------------------
# Indexes
# ---------------------------------------------------------------------


def test_expected_indexes_exist(connection):
    expected = {
        "idx_documents_year",
        "idx_documents_title",
        "idx_paragraph_document",
        "idx_paragraph_page",
        "idx_terms_term",
        "idx_paragraph_terms_term",
        "idx_paragraph_terms_para",
        "idx_anchor_label",
        "idx_paragraph_anchor_anchor",
        "idx_paragraph_anchor_para",
        "idx_embeddings_model",
        "idx_metadata_provenance_document",
    }

    indexes = sqlite_objects(connection, "index")

    assert expected.issubset(indexes)


# ---------------------------------------------------------------------
# Foreign keys
# ---------------------------------------------------------------------


def test_foreign_keys_enabled(connection):
    enabled = connection.execute(
        "PRAGMA foreign_keys;"
    ).fetchone()[0]

    assert enabled == 1


def test_paragraph_table_has_foreign_key(connection):
    rows = connection.execute(
        "PRAGMA foreign_key_list(paragraphs);"
    ).fetchall()

    assert len(rows) == 1
    assert rows[0]["table"] == "documents"


# ---------------------------------------------------------------------
# Basic insert sanity
# ---------------------------------------------------------------------


def test_can_insert_document(connection):
    connection.execute(
        """
        INSERT INTO documents(
            filename,
            page_count
        )
        VALUES(?, ?)
        """,
        ("sample.pdf", 12),
    )

    count = connection.execute(
        "SELECT COUNT(*) FROM documents"
    ).fetchone()[0]

    assert count == 1


def test_can_insert_paragraph(connection):
    connection.execute(
        """
        INSERT INTO documents(filename, page_count)
        VALUES('doc.pdf', 1)
        """
    )

    doc_id = connection.execute(
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
            doc_id,
            1,
            1,
            "Hello world",
            "default",
        ),
    )

    count = connection.execute(
        "SELECT COUNT(*) FROM paragraphs"
    ).fetchone()[0]

    assert count == 1


# ---------------------------------------------------------------------
# FTS sanity
# ---------------------------------------------------------------------


def test_insert_trigger_populates_fts(connection):
    connection.execute(
        """
        INSERT INTO documents(filename, page_count)
        VALUES('doc.pdf', 1)
        """
    )

    doc_id = connection.execute(
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
            doc_id,
            1,
            1,
            "renewable energy transition",
            "default",
        ),
    )

    row = connection.execute(
        """
        SELECT rowid
        FROM paragraphs_fts
        WHERE paragraphs_fts MATCH 'renewable'
        """
    ).fetchone()

    assert row is not None