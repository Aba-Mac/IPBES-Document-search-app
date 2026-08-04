"""
Tests for glossary exact-match indexing.
"""

from pathlib import Path
import sqlite3

import pytest

from glossary import (
    GlossaryMatcher,
    GlossaryTerm,
    index_paragraph_glossary_terms,
    load_terms_csv,
)


@pytest.fixture
def glossary_csv(tmp_path: Path) -> Path:
    """
    Create temporary glossary CSV.
    """

    path = tmp_path / "terms.csv"

    path.write_text(
        """
term,category
Data Governance,GOVERNANCE
Licensing,POLICY
Metadata,DATA
""".strip(),
        encoding="utf-8",
    )

    return path


@pytest.fixture
def database() -> sqlite3.Connection:
    """
    Create temporary SQLite database.
    """

    connection = sqlite3.connect(":memory:")

    connection.executescript(
        """
        CREATE TABLE glossary_terms (
            id INTEGER PRIMARY KEY,
            term TEXT NOT NULL UNIQUE,
            category TEXT NOT NULL
        );

        CREATE TABLE paragraphs (
            id INTEGER PRIMARY KEY,
            text TEXT NOT NULL
        );

        CREATE TABLE paragraph_terms (
            paragraph_id INTEGER NOT NULL,
            term_id INTEGER NOT NULL,
            occurrence_count INTEGER NOT NULL
        );
        """
    )

    return connection


def test_load_terms_csv(glossary_csv: Path):
    terms = load_terms_csv(glossary_csv)

    assert len(terms) == 3
    assert terms[0].term == "Data Governance"


def test_exact_matching_is_case_insensitive():

    matcher = GlossaryMatcher(
        [
            GlossaryTerm(
                term_id=1,
                term="Metadata",
                category="DATA",
            )
        ]
    )

    results = matcher.find_matches(
        paragraph_id=10,
        text="Metadata and metadata appear.",
    )

    assert results[0].occurrence_count == 2


def test_word_boundaries_prevent_partial_matches():

    matcher = GlossaryMatcher(
        [
            GlossaryTerm(
                term_id=1,
                term="Data",
                category="DATA",
            )
        ]
    )

    results = matcher.find_matches(
        paragraph_id=1,
        text="Database contains data.",
    )

    assert len(results) == 1
    assert results[0].occurrence_count == 1


def test_indexing_stores_matches(
    database,
    glossary_csv,
):

    inserted = index_paragraph_glossary_terms(
        database,
        [
            (
                1,
                "Data Governance and Licensing are important.",
            )
        ],
        glossary_csv,
    )

    assert inserted == 2

    rows = database.execute(
        """
        SELECT occurrence_count
        FROM paragraph_terms
        ORDER BY term_id
        """
    ).fetchall()

    assert rows == [
        (1,),
        (1,),
    ]


def test_indexing_is_idempotent(
    database,
    glossary_csv,
):

    paragraphs = [
        (
            1,
            "Metadata metadata",
        )
    ]

    index_paragraph_glossary_terms(
        database,
        paragraphs,
        glossary_csv,
    )

    index_paragraph_glossary_terms(
        database,
        paragraphs,
        glossary_csv,
    )

    count = database.execute(
        """
        SELECT COUNT(*)
        FROM paragraph_terms
        """
    ).fetchone()[0]

    assert count == 1