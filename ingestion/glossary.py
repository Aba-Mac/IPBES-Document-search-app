"""
Glossary exact-match indexing module.

This module performs the glossary matching used by the live search system.

Design principles:
- Matching is performed once during ingestion.
- Search/UI layers only read stored paragraph_terms rows.
- Exact matching only.
- Independent from topic tagging and embeddings.
- Uses compiled regex patterns for efficient repeated matching.

Expected database schema:

terms
--------------
id INTEGER PRIMARY KEY
term TEXT NOT NULL UNIQUE


paragraph_terms
---------------
paragraph_id INTEGER NOT NULL
term_id INTEGER NOT NULL
occurrence_count INTEGER NOT NULL

FOREIGN KEY(paragraph_id) REFERENCES paragraphs(id)
FOREIGN KEY(term_id) REFERENCES terms(id)
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class GlossaryTerm:
    """
    Represents a glossary term loaded from a text file.
    """

    term_id: int
    term: str


@dataclass(frozen=True)
class GlossaryMatch:
    """
    Represents an exact glossary match in a paragraph.
    """

    paragraph_id: int
    term_id: int
    occurrence_count: int


class GlossaryMatcher:
    """
    Compiled exact glossary matcher.

    A single combined regex is created for all glossary terms to avoid
    repeatedly scanning paragraphs once per term.
    """

    def __init__(self, terms: Iterable[GlossaryTerm]) -> None:
        self._terms = list(terms)

        if not self._terms:
            raise ValueError("Glossary matcher requires at least one term.")

        self._term_lookup = {
            self._normalise_pattern_value(term.term): term
            for term in self._terms
        }

        escaped_terms = sorted(
            (
                re.escape(self._normalise_pattern_value(term.term))
                for term in self._terms
            ),
            key=len,
            reverse=True,
        )

        pattern = r"\b(" + "|".join(escaped_terms) + r")\b"

        self._regex = re.compile(
            pattern,
            flags=re.IGNORECASE,
        )

    @staticmethod
    def _normalise_pattern_value(value: str) -> str:
        """
        Normalise glossary terms before matching.
        """

        return re.sub(r"\s+", " ", value.strip())

    def find_matches(self, paragraph_id: int, text: str) -> list[GlossaryMatch]:
        """
        Find all exact glossary matches in a paragraph.

        Returns:
            List of GlossaryMatch objects.
        """

        if not text.strip():
            return []

        counts: dict[int, int] = {}

        for match in self._regex.finditer(text):
            matched_text = self._normalise_pattern_value(match.group(1))

            glossary_term = self._term_lookup.get(
                matched_text.lower()
            )

            if glossary_term is None:
                continue

            counts[glossary_term.term_id] = (
                counts.get(glossary_term.term_id, 0) + 1
            )

        return [
            GlossaryMatch(
                paragraph_id=paragraph_id,
                term_id=term_id,
                occurrence_count=count,
            )
            for term_id, count in counts.items()
        ]


def load_terms_txt(path: Path) -> list[GlossaryTerm]:
    """
    Load glossary terms from a plain text file.

    Each line contains one glossary term.

    Example:
        biodiversity
        ecosystem services
        climate change
    """

    terms: list[GlossaryTerm] = []

    with path.open(
        "r",
        encoding="utf-8-sig",
    ) as file:

        for index, line in enumerate(file, start=1):

            term = line.strip()

            if not term:
                continue

            terms.append(
                GlossaryTerm(
                    term_id=index,
                    term=term,
                )
            )

    return terms


def upsert_glossary_terms(
    connection: sqlite3.Connection,
    terms: Iterable[GlossaryTerm],
) -> dict[str, int]:
    """
    Insert glossary terms into the database.

    Returns:
        Mapping:
            normalised term -> database id
    """

    cursor = connection.cursor()

    for term in terms:
        cursor.execute(
            """
            INSERT INTO terms(term)
            VALUES (?)
            ON CONFLICT(term)
            DO NOTHING
            """,
            (
                term.term,
            ),
        )

    connection.commit()

    rows = cursor.execute(
        """
        SELECT id, term
        FROM terms
        """
    ).fetchall()

    return {
        row[1].lower(): row[0]
        for row in rows
    }


def index_paragraph_glossary_terms(
    connection: sqlite3.Connection,
    paragraphs: Iterable[tuple[int, str]],
    terms_txt: Path,
) -> int:
    """
    Compute glossary matches for paragraphs and store them.

    Existing paragraph_terms rows are removed first so ingestion is
    idempotent.

    Args:
        connection:
            SQLite connection.

        paragraphs:
            Iterable of:
                (paragraph_id, paragraph_text)

        terms_txt:
            Path to terms.txt.

    Returns:
        Number of stored matches.
    """

    loaded_terms = load_terms_txt(terms_txt)

    database_ids = upsert_glossary_terms(
        connection,
        loaded_terms,
    )

    database_terms = [
        GlossaryTerm(
            term_id=database_ids[term.term.lower()],
            term=term.term,
        )
        for term in loaded_terms
    ]

    matcher = GlossaryMatcher(database_terms)

    cursor = connection.cursor()

    cursor.execute(
        """
        DELETE FROM paragraph_terms
        """
    )

    inserted = 0

    for paragraph_id, text in paragraphs:
        matches = matcher.find_matches(
            paragraph_id,
            text,
        )

        for match in matches:
            cursor.execute(
                """
                INSERT INTO paragraph_terms(
                    paragraph_id,
                    term_id,
                    occurrence_count
                )
                VALUES (?, ?, ?)
                """,
                (
                    match.paragraph_id,
                    match.term_id,
                    match.occurrence_count,
                ),
            )

            inserted += 1

    connection.commit()

    return inserted