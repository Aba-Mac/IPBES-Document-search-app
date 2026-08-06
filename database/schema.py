"""
Database schema definitions.

This module contains the complete SQLite schema for the application as
executable DDL statements.

The schema is intentionally dependency-light (sqlite3 only) so that it can
be imported by migrations.py and tested independently.

Features
--------
- Foreign key constraints
- FTS5 full-text search
- Trigger-based FTS synchronization
- Appropriate indexes
- Idempotent CREATE statements

The schema supports:

- documents
- paragraphs
- terms
- paragraph_terms
- anchors
- paragraph_anchors
- embeddings
- paragraphs_fts (FTS5)

The FTS table indexes paragraph text and is automatically maintained via
SQLite triggers.
"""

from __future__ import annotations

from textwrap import dedent

###############################################################################
# Core Tables
###############################################################################

DOCUMENTS_TABLE = dedent(
    """
    CREATE TABLE IF NOT EXISTS documents (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,

        filename            TEXT NOT NULL UNIQUE,

        title               TEXT,
        plenary_session     TEXT,

        year                INTEGER,
        date                TEXT,
        location            TEXT,

        source              TEXT,

        page_count          INTEGER NOT NULL,

        created_at          TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
"""
)

PARAGRAPHS_TABLE = dedent(
    """
    CREATE TABLE IF NOT EXISTS paragraphs (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,

        document_id         INTEGER NOT NULL,

        page_number         INTEGER NOT NULL,

        paragraph_number    INTEGER NOT NULL,

        text                TEXT NOT NULL,

        chunk_method        TEXT NOT NULL,

        FOREIGN KEY(document_id)
            REFERENCES documents(id)
            ON DELETE CASCADE,

        UNIQUE (
            document_id,
            page_number,
            paragraph_number
        )
    );
"""
)


METADATA_PROVENANCE_TABLE = dedent(
    """
    CREATE TABLE IF NOT EXISTS metadata_provenance (

        id INTEGER PRIMARY KEY AUTOINCREMENT,

        document_id INTEGER NOT NULL,

        field_name TEXT NOT NULL,

        field_value TEXT,

        extraction_source TEXT NOT NULL,

        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

        UNIQUE(document_id, field_name),

        FOREIGN KEY(document_id)
            REFERENCES documents(id)
            ON DELETE CASCADE
    );
    """
)


TERMS_TABLE = dedent(
    """
    CREATE TABLE IF NOT EXISTS terms (

        id INTEGER PRIMARY KEY AUTOINCREMENT,

        term TEXT NOT NULL UNIQUE COLLATE NOCASE
    );
"""
)

PARAGRAPH_TERMS_TABLE = dedent(
    """
    CREATE TABLE IF NOT EXISTS paragraph_terms (

        paragraph_id        INTEGER NOT NULL,

        term_id             INTEGER NOT NULL,

        occurrence_count    INTEGER NOT NULL CHECK(occurrence_count >= 0),

        PRIMARY KEY (
            paragraph_id,
            term_id
        ),

        FOREIGN KEY(paragraph_id)
            REFERENCES paragraphs(id)
            ON DELETE CASCADE,

        FOREIGN KEY(term_id)
            REFERENCES terms(id)
            ON DELETE CASCADE
    );
"""
)

ANCHORS_TABLE = dedent(
    """
    CREATE TABLE IF NOT EXISTS anchors (

        id              INTEGER PRIMARY KEY AUTOINCREMENT,

        anchor_label    TEXT NOT NULL UNIQUE,

        description     TEXT
    );
"""
)

PARAGRAPH_ANCHORS_TABLE = dedent(
    """
    CREATE TABLE IF NOT EXISTS paragraph_anchors (

        paragraph_id        INTEGER NOT NULL,

        anchor_id           INTEGER NOT NULL,

        method              TEXT NOT NULL,

        confidence          REAL NOT NULL
            CHECK(confidence >= 0.0 AND confidence <= 1.0),

        embedding_model     TEXT,

        PRIMARY KEY (
            paragraph_id,
            anchor_id
        ),

        FOREIGN KEY(paragraph_id)
            REFERENCES paragraphs(id)
            ON DELETE CASCADE,

        FOREIGN KEY(anchor_id)
            REFERENCES anchors(id)
            ON DELETE CASCADE
    );
"""
)

EMBEDDINGS_TABLE = dedent(
    """
    CREATE TABLE IF NOT EXISTS embeddings (

        paragraph_id    INTEGER NOT NULL,

        model_name      TEXT NOT NULL,

        vector          BLOB NOT NULL,

        PRIMARY KEY (
            paragraph_id,
            model_name
        ),

        FOREIGN KEY(paragraph_id)
            REFERENCES paragraphs(id)
            ON DELETE CASCADE
    );
"""
)

###############################################################################
# FTS5
###############################################################################

FTS_TABLE = dedent(
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS paragraphs_fts
    USING fts5(

        text,

        content='paragraphs',
        content_rowid='id',

        tokenize='unicode61 remove_diacritics 2'
    );
"""
)

###############################################################################
# Triggers
###############################################################################

FTS_INSERT_TRIGGER = dedent(
    """
    CREATE TRIGGER IF NOT EXISTS paragraphs_ai
    AFTER INSERT ON paragraphs
    BEGIN

        INSERT INTO paragraphs_fts (
            rowid,
            text
        )
        VALUES (
            NEW.id,
            NEW.text
        );

    END;
"""
)

FTS_DELETE_TRIGGER = dedent(
    """
    CREATE TRIGGER IF NOT EXISTS paragraphs_ad
    AFTER DELETE ON paragraphs
    BEGIN

        INSERT INTO paragraphs_fts(
            paragraphs_fts,
            rowid,
            text
        )
        VALUES(
            'delete',
            OLD.id,
            OLD.text
        );

    END;
"""
)

FTS_UPDATE_TRIGGER = dedent(
    """
    CREATE TRIGGER IF NOT EXISTS paragraphs_au
    AFTER UPDATE OF text
    ON paragraphs
    BEGIN

        INSERT INTO paragraphs_fts(
            paragraphs_fts,
            rowid,
            text
        )
        VALUES(
            'delete',
            OLD.id,
            OLD.text
        );

        INSERT INTO paragraphs_fts(
            rowid,
            text
        )
        VALUES(
            NEW.id,
            NEW.text
        );

    END;
"""
)

###############################################################################
# Indexes
###############################################################################

INDEXES = [

    dedent(
        """
        CREATE INDEX IF NOT EXISTS idx_documents_year
        ON documents(year);
        """
    ),

    dedent(
        """
        CREATE INDEX IF NOT EXISTS idx_documents_title
        ON documents(title);
        """
    ),

    dedent(
        """
        CREATE INDEX IF NOT EXISTS idx_paragraph_document
        ON paragraphs(document_id);
        """
    ),

    dedent(
        """
        CREATE INDEX IF NOT EXISTS idx_paragraph_page
        ON paragraphs(document_id, page_number);
        """
    ),

    dedent(
        """
        CREATE INDEX IF NOT EXISTS idx_terms_term
        ON terms(term);
        """
    ),

    dedent(
        """
        CREATE INDEX IF NOT EXISTS idx_paragraph_terms_term
        ON paragraph_terms(term_id);
        """
    ),

    dedent(
        """
        CREATE INDEX IF NOT EXISTS idx_paragraph_terms_para
        ON paragraph_terms(paragraph_id);
        """
    ),

    dedent(
        """
        CREATE INDEX IF NOT EXISTS idx_anchor_label
        ON anchors(anchor_label);
        """
    ),

    dedent(
        """
        CREATE INDEX IF NOT EXISTS idx_paragraph_anchor_anchor
        ON paragraph_anchors(anchor_id);
        """
    ),

    dedent(
        """
        CREATE INDEX IF NOT EXISTS idx_paragraph_anchor_para
        ON paragraph_anchors(paragraph_id);
        """
    ),

    dedent(
        """
        CREATE INDEX IF NOT EXISTS idx_embeddings_model
        ON embeddings(model_name);
        """
    ),

    dedent(
    """
    CREATE INDEX IF NOT EXISTS idx_metadata_provenance_document
    ON metadata_provenance(document_id);
    """
    ),
]

###############################################################################
# Ordered schema
###############################################################################

SCHEMA = [

    DOCUMENTS_TABLE,

    METADATA_PROVENANCE_TABLE,

    PARAGRAPHS_TABLE,

    TERMS_TABLE,

    PARAGRAPH_TERMS_TABLE,

    ANCHORS_TABLE,

    PARAGRAPH_ANCHORS_TABLE,

    EMBEDDINGS_TABLE,

    FTS_TABLE,

    FTS_INSERT_TRIGGER,

    FTS_DELETE_TRIGGER,

    FTS_UPDATE_TRIGGER,

    *INDEXES,
]


def iter_schema() -> list[str]:
    """
    Return the ordered schema DDL.

    The order is important:

    1. Tables
    2. Virtual tables
    3. Triggers
    4. Indexes

    Returns
    -------
    list[str]
        Ordered SQL statements.
    """
    return list(SCHEMA)