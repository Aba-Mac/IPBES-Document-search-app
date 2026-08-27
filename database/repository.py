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


# def database_exists() -> bool:
#     """
#     Return True if the configured database file exists.
#     """

#     return Path(settings.database.path).exists()


def close(connection: sqlite3.Connection) -> None:
    """
    Close a database connection.
    """

    connection.close()


###############################################################################
# Integrity Checks
###############################################################################


# def foreign_key_check(
#     connection: sqlite3.Connection | None = None,
# ) -> list[sqlite3.Row]:
#     """
#     Run PRAGMA foreign_key_check.

#     Returns
#     -------
#     list[sqlite3.Row]

#     Empty list means success.
#     """

#     return fetch_all(
#         "PRAGMA foreign_key_check;",
#         connection=connection,
#     )


# def integrity_check(
#     connection: sqlite3.Connection | None = None,
# ) -> bool:
#     """
#     Run SQLite integrity check.

#     Returns
#     -------
#     bool
#     """

#     result = fetch_scalar(
#         "PRAGMA integrity_check;",
#         connection=connection,
#     )

#     return result == "ok"


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

    # DISTINCT p.id because joining paragraph_terms/terms can produce
    # multiple rows per paragraph when it matches more than one term
    # within the selected list(s).
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


# def get_document(
#     document_id: int,
#     *,
#     connection: sqlite3.Connection | None = None,
# ) -> sqlite3.Row | None:
#     """
#     Retrieve a document by ID.
#     """

#     return fetch_one(
#         """
#         SELECT *
#         FROM documents
#         WHERE id = ?
#         """,
#         (document_id,),
#         connection=connection,
#     )


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


# def get_available_documents(
#     *,
#     connection: sqlite3.Connection | None = None,
# ) -> list[sqlite3.Row]:
#     return list_documents(
#         connection=connection,
#     )


# def list_documents(
#     *,
#     connection: sqlite3.Connection | None = None,
# ) -> list[sqlite3.Row]:
#     """
#     Return all documents ordered by year then title.
#     """

#     return fetch_all(
#         """
#         SELECT *
#         FROM documents
#         ORDER BY
#             year,
#             title
#         """,
#         connection=connection,
#     )


# def update_document_metadata(
#     document_id: int,
#     *,
#     title: str | None,
#     plenary_session: str | None,
#     year: int | None,
#     date: str | None,
#     location: str | None,
#     source: str | None,
#     page_count: int,
#     connection: sqlite3.Connection | None = None,
# ) -> None:
#     """
#     Update document metadata.
#     """

#     execute(
#         """
#         UPDATE documents
#         SET
#             title = ?,
#             plenary_session = ?,
#             year = ?,
#             date = ?,
#             location = ?,
#             source = ?,
#             page_count = ?
#         WHERE id = ?
#         """,
#         (
#             title,
#             plenary_session,
#             year,
#             date,
#             location,
#             source,
#             page_count,
#             document_id,
#         ),
#         connection=connection,
#     )


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


# def get_metadata_provenance(
#     connection: sqlite3.Connection,
#     document_id: int,
# ) -> dict[str, dict[str, str | None]]:
#     """
#     Retrieve metadata provenance for a document.

#     Returns:
#         {
#             "title": {
#                 "value": "Annual Report",
#                 "source": "pymupdf",
#             }
#         }
#     """

#     rows = connection.execute(
#         """
#         SELECT
#             field_name,
#             field_value,
#             extraction_source
#         FROM metadata_provenance
#         WHERE document_id = ?
#         """,
#         (document_id,),
#     ).fetchall()

#     return {
#         row["field_name"]: {
#             "value": row["field_value"],
#             "source": row["extraction_source"],
#         }
#         for row in rows
#     }


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

# def create_paragraph(
#     document_id: int,
#     page_number: int,
#     paragraph_number: int,
#     text: str,
#     chunk_method: str,
#     *,
#     connection: sqlite3.Connection | None = None,
# ) -> int:
#     """
#     Insert a paragraph.

#     Returns
#     -------
#     int
#         Paragraph ID.
#     """

#     return _execute_insert(
#         """
#         INSERT INTO paragraphs (
#             document_id,
#             page_number,
#             paragraph_number,
#             text,
#             chunk_method
#         )
#         VALUES (?, ?, ?, ?, ?)
#         """,
#         (
#             document_id,
#             page_number,
#             paragraph_number,
#             text,
#             chunk_method,
#         ),
#         connection=connection,
#     )


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
                row[3],   # paragraph text
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


# def get_paragraph(
#     paragraph_id: int,
#     *,
#     connection: sqlite3.Connection | None = None,
# ) -> sqlite3.Row | None:
#     """
#     Return one paragraph.
#     """

#     return fetch_one(
#         """
#         SELECT
#             p.id AS paragraph_id,
#             p.document_id,
#             p.page_number,
#             p.paragraph_number,
#             p.text AS paragraph_text,
#             p.chunk_method,

#             d.title AS document_title,
#             d.filename,
#             d.source,
#             d.year,
#             d.date,
#             d.location,
#             d.plenary_session
#         FROM paragraphs p
#         JOIN documents d
#             ON d.id = p.document_id
#         WHERE p.id = ?
#         """,
#         (paragraph_id,),
#         connection=connection,
#     )


# def get_document_paragraphs(
#     document_id: int,
#     *,
#     connection: sqlite3.Connection | None = None,
# ) -> list[sqlite3.Row]:
#     """
#     Return every paragraph for one document.
#     """

#     return fetch_all(
#         """
#         SELECT
#             p.id AS paragraph_id,
#             p.document_id,
#             p.page_number,
#             p.paragraph_number,
#             p.text AS paragraph_text,
#             p.chunk_method,

#             d.title AS document_title,
#             d.filename,
#             d.source,
#             d.year,
#             d.date,
#             d.location,
#             d.plenary_session
#         FROM paragraphs p
#         JOIN documents d
#             ON d.id = p.document_id

#         WHERE p.document_id = ?

#         ORDER BY
#             page_number,
#             paragraph_number
#         """,
#         (document_id,),
#         connection=connection,
#     )


# def update_paragraph(
#     paragraph_id: int,
#     text: str,
#     chunk_method: str,
#     *,
#     connection: sqlite3.Connection | None = None,
# ) -> None:
#     """
#     Update paragraph text.

#     The FTS trigger automatically updates the
#     search index.
#     """

#     execute(
#         """
#         UPDATE paragraphs
#         SET
#             text = ?,
#             chunk_method = ?
#         WHERE id = ?
#         """,
#         (
#             text,
#             chunk_method,
#             paragraph_id,
#         ),
#         connection=connection,
#     )


# def delete_paragraph(
#     paragraph_id: int,
#     *,
#     connection: sqlite3.Connection | None = None,
# ) -> None:
#     """
#     Delete one paragraph.
#     """

#     execute(
#         """
#         DELETE
#         FROM paragraphs
#         WHERE id = ?
#         """,
#         (paragraph_id,),
#         connection=connection,
#     )


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
    """
    Perform an FTS5 search with optional document filters.

    Pagination is expressed using SQL LIMIT/OFFSET.

    Parameters
    ----------
    fts_query
        SQLite FTS5 query.

    source
        Optional document source filter.

    year
        Optional inclusive year range.

    document_id
        Optional document filter.

    glossary_lists
        2 glossary lists.

    limit
        Number of results to return.

    offset
        Number of matching results to skip.

    Returns
    -------
    list[sqlite3.Row]
        Results for the requested page.
    """

    if limit < 1:
        raise ValueError("limit must be >= 1")

    if offset < 0:
        raise ValueError("offset must be >= 0")

    parameters: list[Any] = [fts_query]

    joins = ""
    if glossary_lists:
        joins = """
            JOIN paragraph_terms AS pt ON pt.paragraph_id = p.id
            JOIN terms AS t ON t.id = pt.term_id
        """

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
            MIN(bm25(paragraphs_fts)) AS bm25_score

        FROM paragraphs_fts

        JOIN paragraphs AS p
            ON p.id = paragraphs_fts.rowid

        JOIN documents AS d
            ON d.id = p.document_id

        {joins}

        WHERE paragraphs_fts MATCH ?
    """

    if glossary_lists:
        placeholders = ",".join("?" for _ in glossary_lists)
        sql += f"\nAND t.list_name IN ({placeholders})"
        parameters.extend(glossary_lists)

    if source is not None:
        sql += "\nAND d.source = ?"
        parameters.append(source)

    if year is not None:
        year_min, year_max = year

        sql += "\nAND d.year BETWEEN ? AND ?"
        parameters.extend([year_min, year_max])

    if document_id is not None:
        sql += "\nAND d.id = ?"
        parameters.append(document_id)

    if glossary_lists:
        sql += """
            GROUP BY p.id
        """

    sql += """
        ORDER BY bm25_score
        LIMIT ?
        OFFSET ?
    """

    parameters.extend([limit, offset])

    LOGGER.debug("search_paragraphs SQL:\n%s\nparams: %s", sql, parameters)

    return fetch_all(
        sql,
        parameters,
        connection=connection,
    )


# def search_document(
#     document_id: int,
#     query: str,
#     *,
#     limit: int = 100,
#     connection: sqlite3.Connection | None = None,
# ) -> list[sqlite3.Row]:
#     """
#     Perform an FTS search restricted to one
#     document.
#     """

#     return fetch_all(
#         """
#         SELECT
#             p.id AS paragraph_id,
#             p.document_id,
#             p.page_number,
#             p.paragraph_number,
#             p.text AS paragraph_text,
#             p.chunk_method,

#             d.title AS document_title,
#             d.filename,
#             d.source,
#             d.year,
#             d.date,
#             d.location,
#             d.plenary_session,

#             bm25(paragraphs_fts) AS score

#         FROM paragraphs_fts

#         JOIN paragraphs p
        
#                     ON p.id = paragraphs_fts.rowid

#         JOIN documents d
#                     ON d.id = p.document_id

#         WHERE

#             paragraphs_fts MATCH ?

#             AND

#             p.document_id = ?

#         ORDER BY score

#         LIMIT ?
#         """,
#         (
#             query,
#             document_id,
#             limit,
#         ),
#         connection=connection,
#     )


# def search_phrase(
#     phrase: str,
#     *,
#     limit: int = 100,
#     connection: sqlite3.Connection | None = None,
# ) -> list[sqlite3.Row]:
#     """
#     Convenience wrapper for exact phrase search.
#     """

#     return search_paragraphs(
#         f'"{phrase}"',
#         limit=limit,
#         connection=connection,
#     )


###############################################################################
# Terms Repository
###############################################################################

# def create_term(
#     term: str,
#     *,
#     connection: sqlite3.Connection | None = None,
# ) -> int:
#     """
#     Insert a glossary term.

#     Parameters
#     ----------
#     term
#         Glossary term.

#     Returns
#     -------
#     int
#         Newly created term ID.

#     Notes
#     -----
#     Terms are expected to be loaded from terms.txt during ingestion.
#     """

#     return _execute_insert(
#         """
#         INSERT INTO terms (
#             term
#         )
#         VALUES (?)
#         """,
#         (
#             term,
#         ),
#         connection=connection,
#     )


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


# def get_term(
#     term_id: int,
#     *,
#     connection: sqlite3.Connection | None = None,
# ) -> sqlite3.Row | None:
#     """
#     Retrieve a glossary term by ID.
#     """

#     return fetch_one(
#         """
#         SELECT *
#         FROM terms
#         WHERE id = ?
#         """,
#         (term_id,),
#         connection=connection,
#     )


# def get_term_by_name(
#     term: str,
#     *,
#     connection: sqlite3.Connection | None = None,
# ) -> sqlite3.Row | None:
#     """
#     Retrieve a glossary term by its text.
#     """

#     return fetch_one(
#         """
#         SELECT *
#         FROM terms
#         WHERE term = ?
#         """,
#         (term,),
#         connection=connection,
#     )


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


# def update_term(
#     term_id: int,
#     term: str,
#     *,
#     connection: sqlite3.Connection | None = None,
# ) -> None:
#     """
#     Update a glossary term.
#     """

#     execute(
#         """
#         UPDATE terms
#         SET
#             term = ?
#         WHERE id = ?
#         """,
#         (
#             term,
#             term_id,
#         ),
#         connection=connection,
#     )


# def delete_term(
#     term_id: int,
#     *,
#     connection: sqlite3.Connection | None = None,
# ) -> None:
#     """
#     Delete a glossary term.

#     Associated paragraph_term rows are automatically removed.
#     """

#     execute(
#         """
#         DELETE
#         FROM terms
#         WHERE id = ?
#         """,
#         (term_id,),
#         connection=connection,
#     )


###############################################################################
# Paragraph Terms Repository
###############################################################################

# def create_paragraph_term(
#     paragraph_id: int,
#     term_id: int,
#     occurrence_count: int,
#     *,
#     connection: sqlite3.Connection | None = None,
# ) -> None:
#     """
#     Store one exact glossary match.
#     """

#     execute(
#         """
#         INSERT INTO paragraph_terms (

#             paragraph_id,

#             term_id,

#             occurrence_count

#         )
#         VALUES (?, ?, ?)
#         """,
#         (
#             paragraph_id,
#             term_id,
#             occurrence_count,
#         ),
#         connection=connection,
#     )


# def get_paragraph_terms(
#     paragraph_id: int,
#     *,
#     connection: sqlite3.Connection | None = None,
# ) -> list[sqlite3.Row]:
#     """
#     Return every glossary term associated with a paragraph.

#     Used by the UI to build hyperlinks.
#     """

#     return fetch_all(
#         """
#         SELECT

#             t.id,

#             t.term,

#             pt.occurrence_count

#         FROM paragraph_terms pt

#         JOIN terms t

#             ON t.id = pt.term_id

#         WHERE pt.paragraph_id = ?

#         ORDER BY t.term COLLATE NOCASE
#         """,
#         (paragraph_id,),
#         connection=connection,
#     )


# def get_term_paragraphs(
#     term_id: int,
#     *,
#     connection: sqlite3.Connection | None = None,
# ) -> list[sqlite3.Row]:
#     """
#     Return all paragraphs containing one glossary term.

#     This supports hyperlink navigation from glossary terms.
#     """

#     return fetch_all(
#         """
#         SELECT
#             p.id AS paragraph_id,
#             p.document_id,
#             p.page_number,
#             p.paragraph_number,
#             p.text AS paragraph_text,
#             p.chunk_method,

#             d.title AS document_title,
#             d.filename,
#             d.source,
#             d.year,
#             d.date,
#             d.location,
#             d.plenary_session,

#             pt.occurrence_count

#         FROM paragraph_terms pt

#         JOIN paragraphs p
#             ON p.id = pt.paragraph_id

#         JOIN documents d
#             ON d.id = p.document_id

#         WHERE pt.term_id = ?

#         ORDER BY
#             p.document_id,
#             p.page_number,
#             p.paragraph_number
#         """,
#         (term_id,),
#         connection=connection,
#     )


# def delete_paragraph_terms(
#     paragraph_id: int,
#     *,
#     connection: sqlite3.Connection | None = None,
# ) -> None:
#     """
#     Delete all glossary matches belonging to a paragraph.

#     Intended for paragraph reprocessing during ingestion.
#     """

#     execute(
#         """
#         DELETE
#         FROM paragraph_terms
#         WHERE paragraph_id = ?
#         """,
#         (paragraph_id,),
#         connection=connection,
#     )


# def glossary_statistics(
#     *,
#     connection: sqlite3.Connection | None = None,
# ) -> list[sqlite3.Row]:
#     """
#     Return glossary usage statistics.

#     Results include:

#     - term
#     - number of paragraphs containing the term
#     - total occurrences

#     Useful for diagnostics and future reporting.
#     """

#     return fetch_all(
#         """
#         SELECT

#             t.term,

#             COUNT(DISTINCT pt.paragraph_id)
#                 AS paragraph_count,

#             SUM(pt.occurrence_count)
#                 AS total_occurrences

#         FROM terms t

#         LEFT JOIN paragraph_terms pt

#             ON pt.term_id = t.id

#         GROUP BY

#             t.id,
#             t.term

#         ORDER BY

#             total_occurrences DESC,

#             t.term COLLATE NOCASE
#         """,
#         connection=connection,
#     )


###############################################################################
# Anchors Repository
###############################################################################

# def create_anchor(
#     anchor_label: str,
#     description: str | None = None,
#     *,
#     connection: sqlite3.Connection | None = None,
# ) -> int:
#     """
#     Insert a topic anchor.

#     Parameters
#     ----------
#     anchor_label
#         Name of the topic anchor.

#     description
#         Optional description.

#     Returns
#     -------
#     int
#         Newly created anchor ID.
#     """

#     return _execute_insert(
#         """
#         INSERT INTO anchors (
#             anchor_label,
#             description
#         )
#         VALUES (?, ?)
#         """,
#         (
#             anchor_label,
#             description,
#         ),
#         connection=connection,
#     )


# def bulk_insert_anchors(
#     rows: Iterable[Sequence[Any]],
#     *,
#     connection: sqlite3.Connection | None = None,
# ) -> None:
#     """
#     Bulk insert topic anchors.

#     Parameters
#     ----------
#     rows
#         Iterable of:

#         (
#             anchor_label,
#             description
#         )
#     """

#     executemany(
#         """
#         INSERT INTO anchors (
#             anchor_label,
#             description
#         )
#         VALUES (?, ?)

#         ON CONFLICT(anchor_label)
#         DO UPDATE SET
#             description = excluded.description
#         """,
#         rows,
#         connection=connection,
#     )


# def get_anchor(
#     anchor_id: int,
#     *,
#     connection: sqlite3.Connection | None = None,
# ) -> sqlite3.Row | None:
#     """
#     Retrieve an anchor by ID.
#     """

#     return fetch_one(
#         """
#         SELECT *
#         FROM anchors
#         WHERE id = ?
#         """,
#         (anchor_id,),
#         connection=connection,
#     )


# def get_anchor_by_label(
#     anchor_label: str,
#     *,
#     connection: sqlite3.Connection | None = None,
# ) -> sqlite3.Row | None:
#     """
#     Retrieve an anchor by label.
#     """

#     return fetch_one(
#         """
#         SELECT *
#         FROM anchors
#         WHERE anchor_label = ?
#         """,
#         (anchor_label,),
#         connection=connection,
#     )


# def list_anchors(
#     *,
#     connection: sqlite3.Connection | None = None,
# ) -> list[sqlite3.Row]:
#     """
#     Return every topic anchor.
#     """

#     return fetch_all(
#         """
#         SELECT *
#         FROM anchors
#         ORDER BY anchor_label COLLATE NOCASE
#         """,
#         connection=connection,
#     )


###############################################################################
# Paragraph Anchor Repository
###############################################################################

# def create_paragraph_anchor(
#     paragraph_id: int,
#     anchor_id: int,
#     method: str,
#     confidence: float,
#     embedding_model: str | None = None,
#     *,
#     connection: sqlite3.Connection | None = None,
# ) -> None:
#     """
#     Associate a paragraph with a topic anchor.
#     """

#     execute(
#         """
#         INSERT INTO paragraph_anchors (

#             paragraph_id,

#             anchor_id,

#             method,

#             confidence,

#             embedding_model

#         )
#         VALUES (?, ?, ?, ?, ?)

#         ON CONFLICT(paragraph_id, anchor_id)

#         DO UPDATE SET

#             method = excluded.method,

#             confidence = excluded.confidence,

#             embedding_model = excluded.embedding_model
#         """,
#         (
#             paragraph_id,
#             anchor_id,
#             method,
#             confidence,
#             embedding_model,
#         ),
#         connection=connection,
#     )


# def bulk_insert_paragraph_anchors(
#     rows: Iterable[Sequence[Any]],
#     *,
#     connection: sqlite3.Connection | None = None,
# ) -> None:
#     """
#     Bulk insert paragraph-anchor associations.

#     Parameters
#     ----------
#     rows
#         Iterable of:

#         (
#             paragraph_id,
#             anchor_id,
#             method,
#             confidence,
#             embedding_model
#         )
#     """

#     executemany(
#         """
#         INSERT INTO paragraph_anchors (

#             paragraph_id,

#             anchor_id,

#             method,

#             confidence,

#             embedding_model

#         )
#         VALUES (?, ?, ?, ?, ?)

#         ON CONFLICT(paragraph_id, anchor_id)

#         DO UPDATE SET

#             method = excluded.method,

#             confidence = excluded.confidence,

#             embedding_model = excluded.embedding_model
#         """,
#         rows,
#         connection=connection,
#     )


# def get_paragraph_anchors(
#     paragraph_id: int,
#     *,
#     connection: sqlite3.Connection | None = None,
# ) -> list[sqlite3.Row]:
#     """
#     Return all topic tags assigned to a paragraph.
#     """

#     return fetch_all(
#         """
#         SELECT

#             a.id,
#             a.anchor_label,
#             a.description,

#             pa.method,
#             pa.confidence,
#             pa.embedding_model

#         FROM paragraph_anchors pa

#         JOIN anchors a
#             ON a.id = pa.anchor_id

#         WHERE pa.paragraph_id = ?

#         ORDER BY
#             pa.confidence DESC,
#             a.anchor_label
#         """,
#         (paragraph_id,),
#         connection=connection,
#     )


# def delete_paragraph_anchors(
#     paragraph_id: int,
#     *,
#     connection: sqlite3.Connection | None = None,
# ) -> None:
#     """
#     Remove all topic tags from a paragraph.
#     """

#     execute(
#         """
#         DELETE
#         FROM paragraph_anchors
#         WHERE paragraph_id = ?
#         """,
#         (paragraph_id,),
#         connection=connection,
#     )


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