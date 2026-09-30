"""
database/migrations.py

Database migration runner for the document search application.

This module is intentionally lightweight. It applies the schema defined in
``database.schema`` using idempotent DDL statements and performs basic
post-migration validation.

Characteristics
---------------
- Safe to execute repeatedly.
- Creates the database if it does not exist.
- Enables SQLite foreign keys and WAL mode.
- Applies the complete schema from schema.py.
- Upgrades databases created before the lemma index existed
  (adds paragraphs.lemmas, backfills it, rebuilds paragraphs_fts).
- Verifies that required tables, indexes, triggers and the FTS5 virtual
  table exist.
- Rebuilds the FTS index if required.
- Intended to be called during application startup or ingestion.

Example
-------
>>> from database.migrations import migrate
>>> migrate()
"""

from __future__ import annotations

import logging
import sqlite3

from core.config import settings
from database.schema import iter_schema
from database.repository import connect

LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------
# Required database objects
# ---------------------------------------------------------------------

_REQUIRED_TABLES = {
    "documents",
    "paragraphs",
    "terms",
    "paragraph_terms",
    "anchors",
    "paragraph_anchors",
    "embeddings",
}

_REQUIRED_TRIGGERS = {
    "paragraphs_ai",
    "paragraphs_au",
    "paragraphs_ad",
}


# ---------------------------------------------------------------------
# Schema application
# ---------------------------------------------------------------------


def apply_schema(connection: sqlite3.Connection) -> None:
    """
    Apply every DDL statement defined in schema.py.

    Parameters
    ----------
    connection
        Open SQLite connection.
    """
    with connection:
        for statement in iter_schema():
            connection.executescript(statement)

    tables = connection.execute("""
        SELECT name
        FROM sqlite_master
        WHERE type='table'
        ORDER BY name
    """).fetchall()

    LOGGER.info("Tables after migration: %s", [t[0] for t in tables])

# ---------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------


def _existing_objects(
    connection: sqlite3.Connection,
    object_type: str,
) -> set[str]:
    """
    Return the names of existing SQLite objects.

    Parameters
    ----------
    connection
        SQLite connection.

    object_type
        table, trigger, index, ...

    Returns
    -------
    set[str]
    """

    cursor = connection.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = ?
        """,
        (object_type,),
    )

    return {row["name"] for row in cursor.fetchall()}


def validate_schema(connection: sqlite3.Connection) -> None:
    """
    Verify that required schema objects exist.

    Raises
    ------
    RuntimeError
        If validation fails.
    """

    tables = _existing_objects(connection, "table")
    triggers = _existing_objects(connection, "trigger")

    missing_tables = _REQUIRED_TABLES - tables
    if missing_tables:
        raise RuntimeError(
            f"Missing database tables: {sorted(missing_tables)}"
        )

    missing_triggers = _REQUIRED_TRIGGERS - triggers
    if missing_triggers:
        raise RuntimeError(
            f"Missing triggers: {sorted(missing_triggers)}"
        )

    cursor = connection.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type='table'
          AND name='paragraphs_fts'
        """
    )

    if cursor.fetchone() is None:
        raise RuntimeError(
            "FTS5 virtual table 'paragraphs_fts' does not exist."
        )


# ---------------------------------------------------------------------
# FTS maintenance
# ---------------------------------------------------------------------


def rebuild_fts(connection: sqlite3.Connection) -> None:
    """
    Rebuild the FTS5 index from the content table.

    Safe to call repeatedly.
    """

    with connection:
        connection.execute(
            """
            INSERT INTO paragraphs_fts(paragraphs_fts)
            VALUES('rebuild');
            """
        )


def _fts_is_populated(connection: sqlite3.Connection) -> bool:
    """
    Return True if the FTS index already contains entries.

    NOTE: paragraphs_fts is an external-content table, so a plain SELECT
    reads through to ``paragraphs`` and returns True whenever paragraphs
    has rows, even if the index itself is empty. This is therefore only
    a cheap first-run check; code that has just recreated the FTS table
    (see upgrade_to_lemma_index) calls rebuild_fts explicitly.
    """

    cursor = connection.execute(
        """
        SELECT EXISTS(
            SELECT 1
            FROM paragraphs_fts
            LIMIT 1
        );
        """
    )

    return bool(cursor.fetchone()[0])


# ---------------------------------------------------------------------
# Upgrade: lemma-based FTS index
# ---------------------------------------------------------------------


def _column_names(connection: sqlite3.Connection, table: str) -> set[str]:
    """Column names of a table or virtual table."""
    return {
        row[1] for row in connection.execute(f"PRAGMA table_info({table})")
    }


def upgrade_to_lemma_index(connection: sqlite3.Connection) -> bool:
    """
    Upgrade a database created before paragraphs.lemmas existed.

    Steps (order matters):

    1. Drop the old FTS triggers and the old FTS table.
    2. Add paragraphs.lemmas.
    3. Backfill lemmas for every existing paragraph. This happens while
       no triggers exist, so nothing tries to 'delete' entries from an
       index that was just thrown away (which would corrupt it).
    4. Re-apply the schema (creates the new FTS table and triggers).
    5. Rebuild the FTS index from paragraphs.lemmas.

    Paragraph text, glossary tables, anchors and embeddings are not
    touched.

    Returns
    -------
    bool
        True if an upgrade was performed, False if none was needed.
    """
    if (
        "lemmas" in _column_names(connection, "paragraphs")
        and "lemmas" in _column_names(connection, "paragraphs_fts")
    ):
        return False

    # Imported lazily so ordinary migrations don't load spaCy.
    from ingestion.glossary import lemmatise_many

    LOGGER.info("Upgrading database to lemma-based full-text index...")

    with connection:
        for trigger in ("paragraphs_ai", "paragraphs_ad", "paragraphs_au"):
            connection.execute(f"DROP TRIGGER IF EXISTS {trigger}")
        connection.execute("DROP TABLE IF EXISTS paragraphs_fts")

        if "lemmas" not in _column_names(connection, "paragraphs"):
            connection.execute(
                "ALTER TABLE paragraphs "
                "ADD COLUMN lemmas TEXT NOT NULL DEFAULT ''"
            )

    rows = connection.execute("SELECT id, text FROM paragraphs").fetchall()
    lemma_lists = lemmatise_many(row[1] for row in rows)

    with connection:
        connection.executemany(
            "UPDATE paragraphs SET lemmas = ? WHERE id = ?",
            [
                (" ".join(lemmas), row[0])
                for row, lemmas in zip(rows, lemma_lists)
            ],
        )

    apply_schema(connection)
    rebuild_fts(connection)

    LOGGER.info("Lemma index built for %d paragraphs.", len(rows))
    return True


# ---------------------------------------------------------------------
# Migration entry point
# ---------------------------------------------------------------------


def migrate() -> None:
    """
    Execute all database migrations.

    This function is safe to call multiple times.
    """

    LOGGER.info("Applying database schema...")

    with connect() as connection:

        apply_schema(connection)

        upgrade_to_lemma_index(connection)

        validate_schema(connection)

        if not _fts_is_populated(connection):
            LOGGER.info("Building FTS index...")
            rebuild_fts(connection)

    LOGGER.info("Database migration completed successfully.")


# ---------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------


if __name__ == "__main__":

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(message)s",
    )

    migrate()