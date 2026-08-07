"""
Tests for database.repository.

This file covers:

- connection management
- transactions
- generic execute/fetch helpers
- integrity helpers
- database statistics
- document repository

Later sections cover paragraphs, FTS, glossary terms, anchors,
embeddings and remaining CRUD functions.
"""

from __future__ import annotations

import sqlite3

import pytest

from database import repository
from database.schema import iter_schema


###############################################################################
# Fixtures
###############################################################################


@pytest.fixture
def connection():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")

    for ddl in iter_schema():
        conn.executescript(ddl)

    yield conn

    conn.close()


###############################################################################
# Helpers
###############################################################################


def create_document(connection) -> int:
    return repository.create_document(
        filename="sample.pdf",
        title="Sample",
        plenary_session="2024-A",
        year=2024,
        date="2024-01-01",
        location="Berlin",
        source="pytest",
        page_count=5,
        connection=connection,
    )


###############################################################################
# Generic Execute Helpers
###############################################################################


def test_execute_insert(connection):
    repository.execute(
        """
        INSERT INTO terms(term, category)
        VALUES(?, ?)
        """,
        ("Budget", "Finance"),
        connection=connection,
    )

    row = repository.fetch_one(
        "SELECT term FROM terms",
        connection=connection,
    )

    assert row["term"] == "Budget"


def test_executemany(connection):
    repository.executemany(
        """
        INSERT INTO terms(term, category)
        VALUES(?, ?)
        """,
        [
            ("Budget", "Finance"),
            ("Tax", "Finance"),
            ("Climate", "Environment"),
        ],
        connection=connection,
    )

    assert repository.table_row_count(
        "terms",
        connection=connection,
    ) == 3


def test_fetch_one(connection):
    repository.execute(
        "INSERT INTO terms(term, category) VALUES(?,?)",
        ("Energy", "Policy"),
        connection=connection,
    )

    row = repository.fetch_one(
        "SELECT * FROM terms",
        connection=connection,
    )

    assert row["term"] == "Energy"


def test_fetch_all(connection):
    repository.executemany(
        "INSERT INTO terms(term, category) VALUES(?,?)",
        [
            ("A", "x"),
            ("B", "x"),
            ("C", "x"),
        ],
        connection=connection,
    )

    rows = repository.fetch_all(
        "SELECT * FROM terms",
        connection=connection,
    )

    assert len(rows) == 3


def test_fetch_scalar(connection):
    repository.executemany(
        "INSERT INTO terms(term, category) VALUES(?,?)",
        [
            ("A", "x"),
            ("B", "x"),
        ],
        connection=connection,
    )

    assert (
        repository.fetch_scalar(
            "SELECT COUNT(*) FROM terms",
            connection=connection,
        )
        == 2
    )


###############################################################################
# Transaction Handling
###############################################################################


def test_transaction_commit(connection):
    with repository.transaction(connection) as conn:
        conn.execute(
            """
            INSERT INTO terms(term, category)
            VALUES('Budget','Finance')
            """
        )

    assert repository.table_row_count(
        "terms",
        connection=connection,
    ) == 1


def test_transaction_rolls_back(connection):
    with pytest.raises(RuntimeError):

        with repository.transaction(connection) as conn:
            conn.execute(
                """
                INSERT INTO terms(term, category)
                VALUES('Budget','Finance')
                """
            )

            raise RuntimeError("boom")

    assert repository.table_row_count(
        "terms",
        connection=connection,
    ) == 0


###############################################################################
# Integrity Helpers
###############################################################################


def test_integrity_check(connection):
    assert repository.integrity_check(connection)


def test_foreign_key_check(connection):
    assert repository.foreign_key_check(connection) == []


###############################################################################
# Statistics
###############################################################################


def test_table_row_count(connection):
    create_document(connection)

    assert (
        repository.table_row_count(
            "documents",
            connection=connection,
        )
        == 1
    )


def test_table_row_count_invalid_table(connection):
    with pytest.raises(ValueError):
        repository.table_row_count(
            "bad_table",
            connection=connection,
        )


###############################################################################
# Documents
###############################################################################


def test_create_document(connection):
    doc_id = create_document(connection)

    assert isinstance(doc_id, int)
    assert doc_id > 0


def test_get_document(connection):
    doc_id = create_document(connection)

    row = repository.get_document(
        doc_id,
        connection=connection,
    )

    assert row["filename"] == "sample.pdf"
    assert row["title"] == "Sample"


def test_get_document_missing(connection):
    assert (
        repository.get_document(
            999,
            connection=connection,
        )
        is None
    )


def test_get_document_by_filename(connection):
    create_document(connection)

    row = repository.get_document_by_filename(
        "sample.pdf",
        connection=connection,
    )

    assert row["year"] == 2024


def test_list_documents(connection):
    create_document(connection)

    repository.create_document(
        filename="b.pdf",
        title="Another",
        plenary_session=None,
        year=2023,
        date=None,
        location=None,
        source=None,
        page_count=1,
        connection=connection,
    )

    docs = repository.list_documents(connection=connection)

    assert len(docs) == 2
    assert docs[0]["year"] <= docs[1]["year"]


def test_update_document_metadata(connection):
    doc_id = create_document(connection)

    repository.update_document_metadata(
        doc_id,
        title="Updated",
        plenary_session="Session X",
        year=2025,
        date="2025-05-01",
        location="Bonn",
        source="Updated",
        page_count=8,
        connection=connection,
    )

    row = repository.get_document(
        doc_id,
        connection=connection,
    )

    assert row["title"] == "Updated"
    assert row["year"] == 2025
    assert row["location"] == "Bonn"
    assert row["page_count"] == 8


def test_delete_document(connection):
    doc_id = create_document(connection)

    repository.delete_document(
        doc_id,
        connection=connection,
    )

    assert (
        repository.get_document(
            doc_id,
            connection=connection,
        )
        is None
    )


###############################################################################
# Metadata Provenance
###############################################################################


def test_insert_and_get_metadata_provenance(connection):
    doc_id = create_document(connection)

    repository.insert_metadata_provenance(
        connection,
        doc_id,
        {
            "title": ("Sample", "pdf"),
            "year": (2024, "llm"),
        },
    )

    provenance = repository.get_metadata_provenance(
        connection,
        doc_id,
    )

    assert provenance["title"]["value"] == "Sample"
    assert provenance["title"]["source"] == "pdf"
    assert provenance["year"]["value"] == "2024"
    assert provenance["year"]["source"] == "llm"


def test_insert_metadata_provenance_skips_none(connection):
    doc_id = create_document(connection)

    repository.insert_metadata_provenance(
        connection,
        doc_id,
        {
            "title": (None, "pdf"),
        },
    )

    provenance = repository.get_metadata_provenance(
        connection,
        doc_id,
    )

    assert provenance == {}


# ---------------------------------------------------------------------
# Paragraph repository
# ---------------------------------------------------------------------


def test_create_and_get_paragraph(connection):
    document_id = repository.create_document(
        filename="doc.pdf",
        title="Title",
        plenary_session=None,
        year=2024,
        date=None,
        location=None,
        source=None,
        page_count=1,
        connection=connection,
    )

    paragraph_id = repository.create_paragraph(
        document_id=document_id,
        page_number=1,
        paragraph_number=1,
        text="Hello world",
        chunk_method="default",
        connection=connection,
    )

    row = repository.get_paragraph(paragraph_id, connection=connection)

    assert row is not None
    assert row["text"] == "Hello world"


def test_get_document_paragraphs(connection):
    document_id = repository.create_document(
        filename="ordered.pdf",
        title=None,
        plenary_session=None,
        year=None,
        date=None,
        location=None,
        source=None,
        page_count=2,
        connection=connection,
    )

    repository.bulk_insert_paragraphs(
        [
            (document_id, 2, 1, "Second page", "a"),
            (document_id, 1, 2, "First page second", "a"),
            (document_id, 1, 1, "First page first", "a"),
        ],
        connection=connection,
    )

    rows = repository.get_document_paragraphs(
        document_id,
        connection=connection,
    )

    assert [r["paragraph_number"] for r in rows[:2]] == [1, 2]
    assert rows[0]["page_number"] == 1
    assert rows[-1]["page_number"] == 2


def test_update_paragraph(connection):
    document_id = repository.create_document(
        filename="update_para.pdf",
        title=None,
        plenary_session=None,
        year=None,
        date=None,
        location=None,
        source=None,
        page_count=1,
        connection=connection,
    )

    pid = repository.create_paragraph(
        document_id,
        1,
        1,
        "Old",
        "chunk",
        connection=connection,
    )

    repository.update_paragraph(
        pid,
        "New text",
        "updated",
        connection=connection,
    )

    row = repository.get_paragraph(pid, connection=connection)

    assert row["text"] == "New text"
    assert row["chunk_method"] == "updated"


def test_delete_paragraph(connection):
    document_id = repository.create_document(
        filename="delete_para.pdf",
        title=None,
        plenary_session=None,
        year=None,
        date=None,
        location=None,
        source=None,
        page_count=1,
        connection=connection,
    )

    pid = repository.create_paragraph(
        document_id,
        1,
        1,
        "Delete me",
        "chunk",
        connection=connection,
    )

    repository.delete_paragraph(pid, connection=connection)

    assert repository.get_paragraph(
        pid,
        connection=connection,
    ) is None


# ---------------------------------------------------------------------
# Full-text search
# ---------------------------------------------------------------------


def test_search_paragraphs(connection):
    doc = repository.create_document(
        filename="fts.pdf",
        title=None,
        plenary_session=None,
        year=None,
        date=None,
        location=None,
        source=None,
        page_count=1,
        connection=connection,
    )

    repository.bulk_insert_paragraphs(
        [
            (doc, 1, 1, "renewable energy policy", "chunk"),
            (doc, 1, 2, "health care reform", "chunk"),
            (doc, 1, 3, "energy transition plan", "chunk"),
        ],
        connection=connection,
    )

    rows = repository.search_paragraphs(
        "energy",
        connection=connection,
    )

    assert len(rows) == 2
    assert all("energy" in row["text"] for row in rows)


def test_search_phrase(connection):
    doc = repository.create_document(
        filename="phrase.pdf",
        title=None,
        plenary_session=None,
        year=None,
        date=None,
        location=None,
        source=None,
        page_count=1,
        connection=connection,
    )

    repository.bulk_insert_paragraphs(
        [
            (doc, 1, 1, "renewable energy policy", "chunk"),
            (doc, 1, 2, "renewable policy", "chunk"),
        ],
        connection=connection,
    )

    rows = repository.search_phrase(
        "renewable energy",
        connection=connection,
    )

    assert len(rows) == 1
    assert rows[0]["text"] == "renewable energy policy"


def test_search_document(connection):
    doc1 = repository.create_document(
        filename="a.pdf",
        title=None,
        plenary_session=None,
        year=None,
        date=None,
        location=None,
        source=None,
        page_count=1,
        connection=connection,
    )

    doc2 = repository.create_document(
        filename="b.pdf",
        title=None,
        plenary_session=None,
        year=None,
        date=None,
        location=None,
        source=None,
        page_count=1,
        connection=connection,
    )

    repository.create_paragraph(
        doc1,
        1,
        1,
        "energy policy",
        "chunk",
        connection=connection,
    )

    repository.create_paragraph(
        doc2,
        1,
        1,
        "energy policy",
        "chunk",
        connection=connection,
    )

    rows = repository.search_document(
        doc1,
        "energy",
        connection=connection,
    )

    assert len(rows) == 1
    assert rows[0]["document_id"] == doc1


# ---------------------------------------------------------------------
# Terms repository
# ---------------------------------------------------------------------


def test_create_and_get_term(connection):
    term_id = repository.create_term(
        "Inflation",
        "Economics",
        connection=connection,
    )

    row = repository.get_term(
        term_id,
        connection=connection,
    )

    assert row["term"] == "Inflation"
    assert row["category"] == "Economics"


def test_bulk_insert_terms_updates_existing(connection):
    repository.bulk_insert_terms(
        [
            ("GDP", "Economics"),
        ],
        connection=connection,
    )

    repository.bulk_insert_terms(
        [
            ("GDP", "Finance"),
        ],
        connection=connection,
    )

    row = repository.get_term_by_name(
        "GDP",
        connection=connection,
    )

    assert row["category"] == "Finance"


def test_list_terms(connection):
    repository.bulk_insert_terms(
        [
            ("Zoo", "A"),
            ("apple", "B"),
        ],
        connection=connection,
    )

    rows = repository.list_terms(connection=connection)

    assert [r["term"] for r in rows] == [
        "apple",
        "Zoo",
    ]


def test_list_terms_by_category(connection):
    repository.bulk_insert_terms(
        [
            ("GDP", "Economics"),
            ("Inflation", "Economics"),
            ("Tree", "Nature"),
        ],
        connection=connection,
    )

    rows = repository.list_terms_by_category(
        "Economics",
        connection=connection,
    )

    assert len(rows) == 2


def test_update_term(connection):
    term_id = repository.create_term(
        "GDP",
        "Old",
        connection=connection,
    )

    repository.update_term(
        term_id,
        "GDP Revised",
        "New",
        connection=connection,
    )

    row = repository.get_term(
        term_id,
        connection=connection,
    )

    assert row["term"] == "GDP Revised"
    assert row["category"] == "New"


def test_delete_term(connection):
    term_id = repository.create_term(
        "Delete",
        "Cat",
        connection=connection,
    )

    repository.delete_term(
        term_id,
        connection=connection,
    )

    assert repository.get_term(
        term_id,
        connection=connection,
    ) is None


# ---------------------------------------------------------------------
# Paragraph terms repository
# ---------------------------------------------------------------------


def test_create_and_get_paragraph_term(connection):
    document_id = repository.create_document(
        filename="terms.pdf",
        title=None,
        plenary_session=None,
        year=None,
        date=None,
        location=None,
        source=None,
        page_count=1,
        connection=connection,
    )

    paragraph_id = repository.create_paragraph(
        document_id,
        1,
        1,
        "GDP appears here",
        "chunk",
        connection=connection,
    )

    term_id = repository.create_term(
        "GDP",
        "Economics",
        connection=connection,
    )

    repository.create_paragraph_term(
        paragraph_id,
        term_id,
        3,
        connection=connection,
    )

    rows = repository.get_paragraph_terms(
        paragraph_id,
        connection=connection,
    )

    assert len(rows) == 1
    assert rows[0]["term"] == "GDP"
    assert rows[0]["occurrence_count"] == 3


def test_get_term_paragraphs(connection):
    document_id = repository.create_document(
        filename="term_paragraphs.pdf",
        title=None,
        plenary_session=None,
        year=None,
        date=None,
        location=None,
        source=None,
        page_count=1,
        connection=connection,
    )

    paragraph_id = repository.create_paragraph(
        document_id,
        1,
        1,
        "Inflation example",
        "chunk",
        connection=connection,
    )

    term_id = repository.create_term(
        "Inflation",
        "Economics",
        connection=connection,
    )

    repository.create_paragraph_term(
        paragraph_id,
        term_id,
        1,
        connection=connection,
    )

    rows = repository.get_term_paragraphs(
        term_id,
        connection=connection,
    )

    assert len(rows) == 1
    assert rows[0]["id"] == paragraph_id


def test_delete_paragraph_terms(connection):
    document_id = repository.create_document(
        filename="delete_terms.pdf",
        title=None,
        plenary_session=None,
        year=None,
        date=None,
        location=None,
        source=None,
        page_count=1,
        connection=connection,
    )

    paragraph_id = repository.create_paragraph(
        document_id,
        1,
        1,
        "Text",
        "chunk",
        connection=connection,
    )

    term_id = repository.create_term(
        "Term",
        "Category",
        connection=connection,
    )

    repository.create_paragraph_term(
        paragraph_id,
        term_id,
        1,
        connection=connection,
    )

    repository.delete_paragraph_terms(
        paragraph_id,
        connection=connection,
    )

    assert repository.get_paragraph_terms(
        paragraph_id,
        connection=connection,
    ) == []


def test_glossary_statistics(connection):
    document_id = repository.create_document(
        filename="stats.pdf",
        title=None,
        plenary_session=None,
        year=None,
        date=None,
        location=None,
        source=None,
        page_count=1,
        connection=connection,
    )

    paragraph_id = repository.create_paragraph(
        document_id,
        1,
        1,
        "Example",
        "chunk",
        connection=connection,
    )

    term_id = repository.create_term(
        "ExampleTerm",
        "Testing",
        connection=connection,
    )

    repository.create_paragraph_term(
        paragraph_id,
        term_id,
        5,
        connection=connection,
    )

    rows = repository.glossary_statistics(
        connection=connection,
    )

    assert len(rows) == 1
    assert rows[0]["paragraph_count"] == 1
    assert rows[0]["total_occurrences"] == 5


# ---------------------------------------------------------------------
# Anchors repository
# ---------------------------------------------------------------------


def test_create_and_get_anchor(connection):
    anchor_id = repository.create_anchor(
        "Climate",
        "Climate related topics",
        connection=connection,
    )

    row = repository.get_anchor(
        anchor_id,
        connection=connection,
    )

    assert row["anchor_label"] == "Climate"
    assert row["description"] == "Climate related topics"


def test_bulk_insert_anchors_updates(connection):
    repository.bulk_insert_anchors(
        [
            (
                "Economy",
                "Old description",
            )
        ],
        connection=connection,
    )

    repository.bulk_insert_anchors(
        [
            (
                "Economy",
                "New description",
            )
        ],
        connection=connection,
    )

    row = repository.get_anchor_by_label(
        "Economy",
        connection=connection,
    )

    assert row["description"] == "New description"


def test_list_anchors(connection):
    repository.bulk_insert_anchors(
        [
            ("Zoo", None),
            ("Apple", None),
        ],
        connection=connection,
    )

    rows = repository.list_anchors(
        connection=connection,
    )

    assert [
        row["anchor_label"]
        for row in rows
    ] == [
        "Apple",
        "Zoo",
    ]


# ---------------------------------------------------------------------
# Paragraph anchors repository
# ---------------------------------------------------------------------


def test_create_and_get_paragraph_anchor(connection):
    document_id = repository.create_document(
        filename="anchors.pdf",
        title=None,
        plenary_session=None,
        year=None,
        date=None,
        location=None,
        source=None,
        page_count=1,
        connection=connection,
    )

    paragraph_id = repository.create_paragraph(
        document_id,
        1,
        1,
        "Climate text",
        "chunk",
        connection=connection,
    )

    anchor_id = repository.create_anchor(
        "Climate",
        connection=connection,
    )

    repository.create_paragraph_anchor(
        paragraph_id,
        anchor_id,
        "embedding",
        0.9,
        "model-v1",
        connection=connection,
    )

    rows = repository.get_paragraph_anchors(
        paragraph_id,
        connection=connection,
    )

    assert len(rows) == 1
    assert rows[0]["anchor_label"] == "Climate"
    assert rows[0]["confidence"] == 0.9
    assert rows[0]["embedding_model"] == "model-v1"


def test_paragraph_anchor_upsert(connection):
    document_id = repository.create_document(
        filename="anchor_update.pdf",
        title=None,
        plenary_session=None,
        year=None,
        date=None,
        location=None,
        source=None,
        page_count=1,
        connection=connection,
    )

    paragraph_id = repository.create_paragraph(
        document_id,
        1,
        1,
        "Text",
        "chunk",
        connection=connection,
    )

    anchor_id = repository.create_anchor(
        "Topic",
        connection=connection,
    )

    repository.create_paragraph_anchor(
        paragraph_id,
        anchor_id,
        "manual",
        0.5,
        connection=connection,
    )

    repository.create_paragraph_anchor(
        paragraph_id,
        anchor_id,
        "embedding",
        0.8,
        "model",
        connection=connection,
    )

    rows = repository.get_paragraph_anchors(
        paragraph_id,
        connection=connection,
    )

    assert len(rows) == 1
    assert rows[0]["method"] == "embedding"
    assert rows[0]["confidence"] == 0.8


def test_delete_paragraph_anchors(connection):
    document_id = repository.create_document(
        filename="delete_anchor.pdf",
        title=None,
        plenary_session=None,
        year=None,
        date=None,
        location=None,
        source=None,
        page_count=1,
        connection=connection,
    )

    paragraph_id = repository.create_paragraph(
        document_id,
        1,
        1,
        "Text",
        "chunk",
        connection=connection,
    )

    anchor_id = repository.create_anchor(
        "Topic",
        connection=connection,
    )

    repository.create_paragraph_anchor(
        paragraph_id,
        anchor_id,
        "manual",
        1.0,
        connection=connection,
    )

    repository.delete_paragraph_anchors(
        paragraph_id,
        connection=connection,
    )

    assert repository.get_paragraph_anchors(
        paragraph_id,
        connection=connection,
    ) == []


# ---------------------------------------------------------------------
# Embeddings repository
# ---------------------------------------------------------------------


def test_create_and_get_embedding(connection):
    document_id = repository.create_document(
        filename="embedding.pdf",
        title=None,
        plenary_session=None,
        year=None,
        date=None,
        location=None,
        source=None,
        page_count=1,
        connection=connection,
    )

    paragraph_id = repository.create_paragraph(
        document_id,
        1,
        1,
        "Embedding text",
        "chunk",
        connection=connection,
    )

    vector = b"\x01\x02\x03"

    repository.create_embedding(
        paragraph_id,
        "model-test",
        vector,
        connection=connection,
    )

    row = repository.get_embedding(
        paragraph_id,
        "model-test",
        connection=connection,
    )

    assert row is not None
    assert row["vector"] == vector


def test_bulk_insert_embeddings(connection):
    document_id = repository.create_document(
        filename="bulk_embeddings.pdf",
        title=None,
        plenary_session=None,
        year=None,
        date=None,
        location=None,
        source=None,
        page_count=1,
        connection=connection,
    )

    paragraph_id = repository.create_paragraph(
        document_id,
        1,
        1,
        "Text",
        "chunk",
        connection=connection,
    )

    repository.bulk_insert_embeddings(
        [
            (
                paragraph_id,
                "model-a",
                b"abc",
            ),
            (
                paragraph_id,
                "model-b",
                b"xyz",
            ),
        ],
        connection=connection,
    )

    assert repository.get_embedding(
        paragraph_id,
        "model-a",
        connection=connection,
    )["vector"] == b"abc"

    assert repository.get_embedding(
        paragraph_id,
        "model-b",
        connection=connection,
    )["vector"] == b"xyz"


def test_bulk_insert_embeddings_updates_existing(connection):
    document_id = repository.create_document(
        filename="embedding_update.pdf",
        title=None,
        plenary_session=None,
        year=None,
        date=None,
        location=None,
        source=None,
        page_count=1,
        connection=connection,
    )

    paragraph_id = repository.create_paragraph(
        document_id,
        1,
        1,
        "Text",
        "chunk",
        connection=connection,
    )

    repository.bulk_insert_embeddings(
        [
            (
                paragraph_id,
                "model",
                b"old",
            )
        ],
        connection=connection,
    )

    repository.bulk_insert_embeddings(
        [
            (
                paragraph_id,
                "model",
                b"new",
            )
        ],
        connection=connection,
    )

    row = repository.get_embedding(
        paragraph_id,
        "model",
        connection=connection,
    )

    assert row["vector"] == b"new"


def test_delete_embedding(connection):
    document_id = repository.create_document(
        filename="delete_embedding.pdf",
        title=None,
        plenary_session=None,
        year=None,
        date=None,
        location=None,
        source=None,
        page_count=1,
        connection=connection,
    )

    paragraph_id = repository.create_paragraph(
        document_id,
        1,
        1,
        "Text",
        "chunk",
        connection=connection,
    )

    repository.create_embedding(
        paragraph_id,
        "model",
        b"vector",
        connection=connection,
    )

    repository.delete_embedding(
        paragraph_id,
        "model",
        connection=connection,
    )

    assert repository.get_embedding(
        paragraph_id,
        "model",
        connection=connection,
    ) is None


def test_delete_embeddings_for_paragraph(connection):
    document_id = repository.create_document(
        filename="delete_all_embeddings.pdf",
        title=None,
        plenary_session=None,
        year=None,
        date=None,
        location=None,
        source=None,
        page_count=1,
        connection=connection,
    )

    paragraph_id = repository.create_paragraph(
        document_id,
        1,
        1,
        "Text",
        "chunk",
        connection=connection,
    )

    repository.bulk_insert_embeddings(
        [
            (
                paragraph_id,
                "a",
                b"a",
            ),
            (
                paragraph_id,
                "b",
                b"b",
            ),
        ],
        connection=connection,
    )

    repository.delete_embeddings_for_paragraph(
        paragraph_id,
        connection=connection,
    )

    assert repository.get_embedding(
        paragraph_id,
        "a",
        connection=connection,
    ) is None

    assert repository.get_embedding(
        paragraph_id,
        "b",
        connection=connection,
    ) is None


# ---------------------------------------------------------------------
# Integrity and statistics helpers
# ---------------------------------------------------------------------


def test_table_row_count(connection):
    repository.create_document(
        filename="count.pdf",
        title=None,
        plenary_session=None,
        year=None,
        date=None,
        location=None,
        source=None,
        page_count=1,
        connection=connection,
    )

    assert repository.table_row_count(
        "documents",
        connection=connection,
    ) == 1


def test_database_integrity_check(connection):
    assert repository.integrity_check(
        connection=connection,
    )


def test_foreign_key_check(connection):
    result = repository.foreign_key_check(
        connection=connection,
    )

    assert result == []


def test_paragraph_count(connection):
    document_id = repository.create_document(
        filename="paragraph_count.pdf",
        title=None,
        plenary_session=None,
        year=None,
        date=None,
        location=None,
        source=None,
        page_count=1,
        connection=connection,
    )

    repository.create_paragraph(
        document_id,
        1,
        1,
        "One",
        "chunk",
        connection=connection,
    )

    repository.create_paragraph(
        document_id,
        1,
        2,
        "Two",
        "chunk",
        connection=connection,
    )

    assert repository.paragraph_count(
        connection=connection,
    ) == 2


def test_fts_row_count_matches_paragraph_count(connection):
    document_id = repository.create_document(
        filename="fts_count.pdf",
        title=None,
        plenary_session=None,
        year=None,
        date=None,
        location=None,
        source=None,
        page_count=1,
        connection=connection,
    )

    repository.bulk_insert_paragraphs(
        [
            (
                document_id,
                1,
                1,
                "First paragraph",
                "chunk",
            ),
            (
                document_id,
                1,
                2,
                "Second paragraph",
                "chunk",
            ),
        ],
        connection=connection,
    )

    assert repository.fts_row_count(
        connection=connection,
    ) == repository.paragraph_count(
        connection=connection,
    )


def test_verify_fts_sync(connection):
    document_id = repository.create_document(
        filename="fts_sync.pdf",
        title=None,
        plenary_session=None,
        year=None,
        date=None,
        location=None,
        source=None,
        page_count=1,
        connection=connection,
    )

    repository.create_paragraph(
        document_id,
        1,
        1,
        "Indexed paragraph",
        "chunk",
        connection=connection,
    )

    assert repository.verify_fts_sync(
        connection=connection,
    )


def test_rebuild_fts(connection):
    document_id = repository.create_document(
        filename="rebuild.pdf",
        title=None,
        plenary_session=None,
        year=None,
        date=None,
        location=None,
        source=None,
        page_count=1,
        connection=connection,
    )

    repository.create_paragraph(
        document_id,
        1,
        1,
        "Rebuild text",
        "chunk",
        connection=connection,
    )

    repository.rebuild_fts(
        connection=connection,
    )

    assert repository.verify_fts_sync(
        connection=connection,
    )


def test_database_exists(tmp_path, monkeypatch):
    from core.config import settings

    database_file = tmp_path / "test.db"

    monkeypatch.setattr(
        settings,
        "database_path",
        database_file,
    )

    assert repository.database_exists() is False

    connection = repository.connect()
    connection.close()

    assert repository.database_exists() is True