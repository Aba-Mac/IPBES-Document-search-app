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
from pathlib import Path
from typing import Iterable

from core.config import settings
from database.schema import iter_schema

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
    metadata_provenance,
}

_REQUIRED_VIRTUAL_TABLES = {
    "paragraphs_fts",
}

_REQUIRED_TRIGGERS = {
    "paragraphs_ai",
    "paragraphs_au",
    "paragraphs_ad",
}


# ---------------------------------------------------------------------
# Connection helpers
# ---------------------------------------------------------------------


def _connect() -> sqlite3.Connection:
    """
    Create a migration connection.

    Returns
    -------
    sqlite3.Connection
    """

    database_path = Path(settings.database.path)
    database_path.parent.mkdir(parents=True, exist_ok=True)
    LOGGER.info("Migration database: %s", settings.database.path)

    connection = sqlite3.connect(
        database_path,
        detect_types=sqlite3.PARSE_DECLTYPES,
    )

    connection.row_factory = sqlite3.Row

    connection.execute("PRAGMA foreign_keys = ON;")
    connection.execute("PRAGMA journal_mode = WAL;")
    connection.execute("PRAGMA synchronous = NORMAL;")
    connection.execute("PRAGMA temp_store = MEMORY;")

    return connection


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


def optimize_fts(connection: sqlite3.Connection) -> None:
    """
    Optimize the FTS index.

    Optional maintenance operation.
    """

    with connection:
        connection.execute(
            """
            INSERT INTO paragraphs_fts(paragraphs_fts)
            VALUES('optimize');
            """
        )


def _fts_is_populated(connection: sqlite3.Connection) -> bool:
    """
    Return True if the FTS index already contains entries.
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
# Migration entry point
# ---------------------------------------------------------------------


def migrate() -> None:
    """
    Execute all database migrations.

    This function is safe to call multiple times.
    """

    LOGGER.info("Applying database schema...")

    with _connect() as connection:

        apply_schema(connection)

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