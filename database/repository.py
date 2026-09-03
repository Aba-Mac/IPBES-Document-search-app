"""
database/repository.py

Central database access layer.

This module is the ONLY module that should communicate directly with
SQLite. All other modules (ingestion, search, UI, tagging, glossary,
etc.) should import functions from this module rather than using
sqlite3 directly.

Features
--------
- Connection management
- WAL mode
- Foreign key enforcement
- Transaction context manager
- Generic query helpers
- Typed Row access
- Integrity checks
- FTS verification
- Bulk execution helpers

The remainder of this file contains repository functions for each
database table.
"""

from __future__ import annotations

import logging
import sqlite3

from contextlib import contextmanager
from pathlib import Path
from typing import Any
from typing import Generator
from typing import Iterable
from typing import Sequence
from typing import Mapping

from core.config import settings

LOGGER = logging.getLogger(__name__)


###############################################################################
# Connection
###############################################################################


def connect() -> sqlite3.Connection:
    """
    Create a configured SQLite connection.

    Returns
    -------
    sqlite3.Connection

    Notes
    -----
    Every connection enables:

    - Foreign keys
    - WAL mode
    - Normal synchronous mode
    - In-memory temporary storage

    Row objects are returned as sqlite3.Row to provide dictionary-like
    access.

    Examples
    --------
    >>> conn = connect()
    >>> conn.execute("SELECT 1")
    """

    database_path = Path(settings.database.path)
    LOGGER.info("Repository database: %s", settings.database.path)

    database_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    connection = sqlite3.connect(
        database_path,
        detect_types=sqlite3.PARSE_DECLTYPES,
    )

    connection.row_factory = sqlite3.Row

    connection.execute("PRAGMA foreign_keys = ON;")
    connection.execute("PRAGMA journal_mode = WAL;")
    connection.execute("PRAGMA synchronous = NORMAL;")
    connection.execute("PRAGMA temp_store = MEMORY;")
    connection.execute("PRAGMA cache_size = -20000;")

    return connection


###############################################################################
# Transaction Management
###############################################################################


@contextmanager
def transaction(
    connection: sqlite3.Connection | None = None,
) -> Generator[sqlite3.Connection, None, None]:
    """
    Execute statements inside a transaction.

    If no connection is supplied one is created automatically.

    Parameters
    ----------
    connection
        Optional existing connection.

    Examples
    --------
    >>> with transaction() as conn:
    ...     conn.execute(...)
    """

    owns_connection = connection is None

    if owns_connection:
        connection = connect()

    try:

        yield connection

        connection.commit()

    except Exception:

        connection.rollback()

        LOGGER.exception("Database transaction rolled back.")

        raise

    finally:

        if owns_connection:
            connection.close()


###############################################################################
# Generic Execute Helpers
###############################################################################


def execute(
    sql: str,
    parameters: Sequence[Any] | None = None,
    *,
    connection: sqlite3.Connection | None = None,
) -> None:
    """
    Execute a SQL statement.

    Parameters
    ----------
    sql
        SQL statement.

    parameters
        SQL parameters.

    connection
        Optional existing connection.
    """

    parameters = parameters or ()

    with transaction(connection) as conn:

        conn.execute(sql, parameters)


def executemany(
    sql: str,
    rows: Iterable[Sequence[Any]],
    *,
    connection: sqlite3.Connection | None = None,
) -> None:
    """
    Execute many SQL statements efficiently.

    Parameters
    ----------
    sql
        SQL statement.

    rows
        Iterable of parameter tuples.
    """

    with transaction(connection) as conn:

        conn.executemany(sql, rows)


def _execute_insert(
    sql: str,
    parameters: Sequence[Any],
    *,
    connection: sqlite3.Connection | None = None,
) -> int:
    owns_connection = connection is None

    if owns_connection:
        connection = connect()

    try:

        cursor = connection.execute(sql, parameters)

        if owns_connection:
            connection.commit()

        return int(cursor.lastrowid)

    finally:

        if owns_connection:
            connection.close()


###############################################################################
# Query Helpers
###############################################################################


def fetch_one(
    sql: str,
    parameters: Sequence[Any] | None = None,
    *,
    connection: sqlite3.Connection | None = None,
) -> sqlite3.Row | None:
    """
    Fetch a single row.
    """

    parameters = parameters or ()

    owns_connection = connection is None

    if owns_connection:
        connection = connect()

    try:

        cursor = connection.execute(sql, parameters)

        return cursor.fetchone()

    finally:

        if owns_connection:
            connection.close()


def fetch_all(
    sql: str,
    parameters: Sequence[Any] | None = None,
    *,
    connection: sqlite3.Connection | None = None,
) -> list[sqlite3.Row]:
    """
    Fetch every row returned by a query.
    """

    parameters = parameters or ()

    owns_connection = connection is None

    if owns_connection:
        connection = connect()

    try:

        cursor = connection.execute(sql, parameters)

        return list(cursor.fetchall())

    finally:

        if owns_connection:
            connection.close()


def fetch_scalar(
    sql: str,
    parameters: Sequence[Any] | None = None,
    *,
    connection: sqlite3.Connection | None = None,
) -> Any:
    """
    Return the first column of the first row.
    """

    row = fetch_one(
        sql,
        parameters,
        connection=connection,
    )

    if row is None:
        return None

    return row[0]


###############################################################################
# Connection Utilities
###############################################################################


def close(connection: sqlite3.Connection) -> None:
    """
    Close a database connection.
    """

    connection.close()


###############################################################################
# FTS Verification
###############################################################################


def paragraph_count(
    connection: sqlite3.Connection | None = None,
) -> int:
    """
    Number of paragraphs.
    """

    return int(
        fetch_scalar(
            """
            SELECT COUNT(*)
            FROM paragraphs
            """,
            connection=connection,
        )
        or 0
    )


def count_paragraphs(
    *,
    fts_query: str,
    filters: Any = None,
    connection: sqlite3.Connection | None = None,
) -> int:
    """
    Count paragraphs matching an FTS query and optional filters.
    """
    source = getattr(filters, "source", None)
    year = getattr(filters, "year", None)
    document_id = getattr(filters, "document", None)
    glossary_lists = getattr(filters, "glossary_lists", None)

    joins = ""
    where = ["paragraphs_fts MATCH ?"]
    parameters: list[Any] = [fts_query]

    if glossary_lists:
        joins = """
            JOIN paragraph_terms AS pt ON pt.paragraph_id = p.id
            JOIN terms AS t ON t.id = pt.term_id
        """
        placeholders = ",".join("?" for _ in glossary_lists)
        where.append(f"t.list_name IN ({placeholders})")
        parameters.extend(glossary_lists)

    if source is not None:
        where.append("d.source = ?")
        parameters.append(source)

    if year is not None:
        year_min, year_max = year
        where.append("d.year BETWEEN ? AND ?")
        parameters.extend([year_min, year_max])

    if document_id is not None:
        where.append("d.id = ?")
        parameters.append(document_id)

    sql = f"""
        SELECT COUNT(DISTINCT p.id)
        FROM paragraphs_fts
        JOIN paragraphs AS p ON p.id = paragraphs_fts.rowid
        JOIN documents AS d ON d.id = p.document_id
        {joins}
        WHERE {' AND '.join(where)}
    """

    return int(fetch_scalar(sql, parameters, connection=connection) or 0)


def fts_row_count(
    connection: sqlite3.Connection | None = None,
) -> int:
    """
    Number of indexed FTS rows.
    """

    return int(
        fetch_scalar(
            """
            SELECT COUNT(*)
            FROM paragraphs_fts
            """,
            connection=connection,
        )
        or 0
    )


def verify_fts_sync(
    connection: sqlite3.Connection | None = None,
) -> bool:
    """
    Verify the FTS index contains the same number of rows as
    the paragraphs table.

    Returns
    -------
    bool
    """

    return (
        paragraph_count(connection)
        == fts_row_count(connection)
    )


def rebuild_fts(
    connection: sqlite3.Connection | None = None,
) -> None:
    """
    Rebuild the complete FTS index.

    Safe to call at any time.
    """

    execute(
        """
        INSERT INTO paragraphs_fts(paragraphs_fts)
        VALUES('rebuild');
        """,
        connection=connection,
    )


###############################################################################
# Database Statistics
###############################################################################


def table_row_count(
    table: str,
    *,
    connection: sqlite3.Connection | None = None,
) -> int:
    """
    Return the row count for a table.

    Parameters
    ----------
    table
        Table name.
    """

    allowed = {
        "documents",
        "paragraphs",
        "terms",
        "paragraph_terms",
        "anchors",
        "paragraph_anchors",
        "embeddings",
    }

    if table not in allowed:
        raise ValueError(f"Unknown table: {table}")

    sql = f"SELECT COUNT(*) FROM {table}"

    return int(
        fetch_scalar(
            sql,
            connection=connection,
        )
        or 0
    )


###############################################################################
# Documents Repository
###############################################################################

def create_document(
    filename: str,
    title: str | None,
    doi: str | None,
    plenary_session: str | None,
    year: int | None,
    date: str | None,
    location: str | None,
    source: str | None,
    source_hash: str | None,
    page_count: int,
    *,
    connection: sqlite3.Connection | None = None,
) -> int:

    return _execute_insert(
        """
        INSERT INTO documents (
            filename,
            title,
            doi,
            plenary_session,
            year,
            date,
            location,
            source,
            source_hash,
            page_count
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            filename,
            title,
            doi,
            plenary_session,
            year,
            date,
            location,
            source,
            source_hash,
            page_count,
        ),
        connection=connection,
    )


def get_document_by_filename(
    filename: str,
    *,
    connection: sqlite3.Connection | None = None,
) -> sqlite3.Row | None:
    """
    Retrieve a document by filename.
    """

    return fetch_one(
        """
        SELECT *
        FROM documents
        WHERE filename = ?
        """,
        (filename,),
        connection=connection,
    )


def get_available_years(
    *,
    connection: sqlite3.Connection | None = None,
) -> list[int]:
    rows = fetch_all(
        """
        SELECT DISTINCT year
        FROM documents
        WHERE year IS NOT NULL
        ORDER BY year
        """,
        connection=connection,
    )

    return [row["year"] for row in rows]


def insert_metadata_provenance(
    connection: sqlite3.Connection,
    document_id: int,
    fields: Mapping[
        str,
        tuple[str | int | None, str | None],
    ],
) -> None:
    """
    Store metadata extraction provenance.

    Parameters
    ----------
    connection:
        SQLite database connection.

    document_id:
        Parent document identifier.

    fields:
        Mapping of metadata field names to:
            (extracted value, extraction source)

        Example:
            {
                "title": ("Annual Report", "pymupdf"),
                "year": (2024, "llm"),
            }
    """

    for field_name, (value, source) in fields.items():

        if value is None:
            continue

        connection.execute(
            """
            INSERT INTO metadata_provenance(
                document_id,
                field_name,
                extraction_source,
                field_value
            )
            VALUES (?, ?, ?, ?)

            ON CONFLICT(
                document_id,
                field_name
            )
            DO UPDATE SET

                extraction_source = excluded.extraction_source,

                field_value = excluded.field_value
            """,
            (
                document_id,
                field_name,
                source,
                str(value),
            ),
        )


def delete_document(
    document_id: int,
    *,
    connection: sqlite3.Connection | None = None,
) -> None:
    """
    Delete a document.

    Cascades automatically to paragraphs, glossary
    matches, anchors and embeddings.
    """

    execute(
        """
        DELETE
        FROM documents
        WHERE id = ?
        """,
        (document_id,),
        connection=connection,
    )


###############################################################################
# Paragraph Repository
###############################################################################


def bulk_insert_paragraphs(
    rows: Iterable[Sequence[Any]],
    *,
    return_ids: bool = False,
    connection: sqlite3.Connection | None = None,
) -> list[tuple[int, str]] | None:
    """
    Bulk insert paragraph records.

    Parameters
    ----------
    rows:
        Iterable of tuples:

        (
            document_id,
            page_number,
            paragraph_number,
            text,
            chunk_method,
        )

    return_ids:
        If True, return generated paragraph IDs with text.

    Returns
    -------
    None
        When return_ids=False.

    list[tuple[int, str]]
        When return_ids=True:

        (
            paragraph_id,
            paragraph_text,
        )
    """

    rows = list(rows)

    if not return_ids:

        executemany(
            """
            INSERT INTO paragraphs (
                document_id,
                page_number,
                paragraph_number,
                text,
                chunk_method
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            rows,
            connection=connection,
        )

        return None


    conn = connection or connect()

    cursor = conn.cursor()

    inserted: list[tuple[int, str]] = []

    for row in rows:

        cursor.execute(
            """
            INSERT INTO paragraphs (
                document_id,
                page_number,
                paragraph_number,
                text,
                chunk_method
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            row,
        )

        inserted.append(
            (
                cursor.lastrowid,
                row[3],   
            )
        )

    conn.commit()

    return inserted


def get_all_paragraphs_for_glossary(
    *,
    connection: sqlite3.Connection | None = None,
) -> list[tuple[int, str]]:
    """
    Return every paragraph as (paragraph_id, text) pairs, for glossary
    re-matching independent of the ingestion pipeline.
    """
    rows = fetch_all(
        "SELECT id, text FROM paragraphs",
        connection=connection,
    )
    return [(row["id"], row["text"]) for row in rows]


###############################################################################
# Full-Text Search
###############################################################################

def search_paragraphs(
    fts_query: str,
    *,
    source: str | None = None,
    year: tuple[int, int] | None = None,
    document_id: int | None = None,
    glossary_lists: tuple[str, ...] | None = None,
    limit: int,
    offset: int,
    connection: sqlite3.Connection | None = None,
) -> list[sqlite3.Row]:
    if limit < 1:
        raise ValueError("limit must be >= 1")
    if offset < 0:
        raise ValueError("offset must be >= 0")

    where = ["paragraphs_fts MATCH ?"]
    parameters: list[Any] = [fts_query]

    if glossary_lists:
        placeholders = ",".join("?" for _ in glossary_lists)
        where.append(f"""
            p.id IN (
                SELECT pt.paragraph_id
                FROM paragraph_terms AS pt
                JOIN terms AS t ON t.id = pt.term_id
                WHERE t.list_name IN ({placeholders})
            )
        """)
        parameters.extend(glossary_lists)

    if source is not None:
        where.append("d.source = ?")
        parameters.append(source)

    if year is not None:
        year_min, year_max = year
        where.append("d.year BETWEEN ? AND ?")
        parameters.extend([year_min, year_max])

    if document_id is not None:
        where.append("d.id = ?")
        parameters.append(document_id)

    sql = f"""
        SELECT
            p.id AS paragraph_id,
            p.document_id,
            d.title AS document_title,
            d.doi,
            d.filename,
            d.source,
            d.year,
            d.plenary_session,
            d.location,
            p.page_number,
            p.paragraph_number,
            p.text AS paragraph_text,
            p.chunk_method,
            bm25(paragraphs_fts) AS bm25_score
        FROM paragraphs_fts
        JOIN paragraphs AS p ON p.id = paragraphs_fts.rowid
        JOIN documents AS d ON d.id = p.document_id
        WHERE {' AND '.join(where)}
        ORDER BY bm25_score
        LIMIT ?
        OFFSET ?
    """

    parameters.extend([limit, offset])

    return fetch_all(sql, parameters, connection=connection)


###############################################################################
# Terms Repository
###############################################################################


def bulk_insert_terms(
    rows: Iterable[Sequence[Any]],
    *,
    connection: sqlite3.Connection | None = None,
) -> None:
    """
    Bulk insert glossary terms.

    If a term already exists, no update is performed.

    Parameters
    ----------
    rows
        Iterable of:

        (
            term
        )
    """

    executemany(
        """
        INSERT INTO terms (
            term
        )
        VALUES (?)

        ON CONFLICT(term)
        DO NOTHING
        """,
        rows,
        connection=connection,
    )


def list_terms(
    *,
    list_names: tuple[str,...] | None = None,
    connection: sqlite3.Connection | None = None,
) -> list[sqlite3.Row]:
    """
    Return every glossary term.
    """
    if not list_names:
        return fetch_all(
            "SELECT * FROM terms ORDER BY term COLLATE NOCASE",
            connection=connection,
        )

    placeholders = ",".join("?" for _ in list_names)
    
    return fetch_all(
        f"""
        SELECT * FROM terms
        WHERE list_name in ({placeholders})
        ORDER BY term COLLATE NOCASE
        """,
        list_names,
        connection=connection,
    )


###############################################################################
# Paragraph Terms Repository
###############################################################################


def get_paragraph_terms(
    paragraph_id: int,
    *,
    connection: sqlite3.Connection | None = None,
) -> list[sqlite3.Row]:
    """
    Return every glossary term associated with a paragraph.

    Used by the UI to build hyperlinks.
    """

    return fetch_all(
        """
        SELECT

            t.id,

            t.term,

            pt.occurrence_count

        FROM paragraph_terms pt

        JOIN terms t

            ON t.id = pt.term_id

        WHERE pt.paragraph_id = ?

        ORDER BY t.term COLLATE NOCASE
        """,
        (paragraph_id,),
        connection=connection,
    )


###############################################################################
# Embeddings Repository
###############################################################################

# def create_embedding(
#     paragraph_id: int,
#     model_name: str,
#     vector: bytes,
#     *,
#     connection: sqlite3.Connection | None = None,
# ) -> None:
#     """
#     Store an embedding vector.

#     Parameters
#     ----------
#     paragraph_id
#         Paragraph identifier.

#     model_name
#         Embedding model name.

#     vector
#         Serialized embedding bytes.
#     """

#     execute(
#         """
#         INSERT INTO embeddings (

#             paragraph_id,

#             model_name,

#             vector

#         )
#         VALUES (?, ?, ?)
#         """,
#         (
#             paragraph_id,
#             model_name,
#             vector,
#         ),
#         connection=connection,
#     )


# def bulk_insert_embeddings(
#     rows: Iterable[Sequence[Any]],
#     *,
#     connection: sqlite3.Connection | None = None,
# ) -> None:
#     """
#     Bulk insert embedding vectors.

#     Parameters
#     ----------
#     rows
#         Iterable of:

#         (
#             paragraph_id,
#             model_name,
#             vector
#         )
#     """

#     executemany(
#         """
#         INSERT INTO embeddings (

#             paragraph_id,

#             model_name,

#             vector

#         )
#         VALUES (?, ?, ?)

#         ON CONFLICT(paragraph_id, model_name)
#         DO UPDATE SET
#             vector = excluded.vector
#         """,
#         rows,
#         connection=connection,
#     )


# def get_embedding(
#     paragraph_id: int,
#     model_name: str,
#     *,
#     connection: sqlite3.Connection | None = None,
# ) -> sqlite3.Row | None:
#     """
#     Retrieve one embedding.
#     """

#     return fetch_one(
#         """
#         SELECT *
#         FROM embeddings
#         WHERE
#             paragraph_id = ?
#             AND model_name = ?
#         """,
#         (
#             paragraph_id,
#             model_name,
#         ),
#         connection=connection,
#     )


# def delete_embedding(
#     paragraph_id: int,
#     model_name: str,
#     *,
#     connection: sqlite3.Connection | None = None,
# ) -> None:
#     """
#     Delete a stored embedding.
#     """

#     execute(
#         """
#         DELETE
#         FROM embeddings
#         WHERE
#             paragraph_id = ?
#             AND model_name = ?
#         """,
#         (
#             paragraph_id,
#             model_name,
#         ),
#         connection=connection,
#     )


# def delete_embeddings_for_paragraph(
#     paragraph_id: int,
#     *,
#     connection: sqlite3.Connection | None = None,
# ) -> None:
#     """
#     Delete all embeddings belonging to a paragraph.
#     """

#     execute(
#         """
#         DELETE
#         FROM embeddings
#         WHERE paragraph_id = ?
#         """,
#         (paragraph_id,),
#         connection=connection,
#     )