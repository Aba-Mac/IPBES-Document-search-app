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
    list_name: str = "general"


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

        self._term_lookup: dict[str, list[GlossaryTerm]] = {}
        for term in self._terms:
            key = self._normalise_pattern_value(term.term).lower()
            self._term_lookup.setdefault(key, []).append(term)

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

            glossary_terms = self._term_lookup.get(
                matched_text.lower(), []
            )

            for glossary_term in glossary_terms:
                counts[glossary_term.term_id] = counts.get(glossary_term.term_id, 0) + 1

        return [
            GlossaryMatch(
                paragraph_id=paragraph_id,
                term_id=term_id,
                occurrence_count=count,
            )
            for term_id, count in counts.items()
        ]


def load_terms_txt(path: Path, list_name: str = "general") -> list[GlossaryTerm]:
    """
    Load glossary terms from a plain text file.

    Each line contains one glossary term.

    Example:
        biodiversity
        ecosystem services
        climate change
    """

    terms: list[GlossaryTerm] = []
    with path.open("r", encoding="utf-8-sig") as file:
        for index, line in enumerate(file, start=1):
            term = line.strip()
            if not term:
                continue
            terms.append(GlossaryTerm(term_id=index, term=term, list_name=list_name))
    return terms


def upsert_glossary_terms(
    connection: sqlite3.Connection,
    terms: Iterable[GlossaryTerm],
) -> dict[tuple[str, str], int]:
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
            INSERT INTO terms(term, list_name)
            VALUES (?, ?)
            ON CONFLICT(term, list_name) DO NOTHING
            """,
            (term.term, term.list_name),
        )
    rows = cursor.execute("SELECT id, term, list_name FROM terms").fetchall()
    return {(row[1].lower(), row[2]): row[0] for row in rows}


def index_paragraph_glossary_terms(
    connection: sqlite3.Connection,
    paragraphs: Iterable[tuple[int, str]],
    glossary_sources: dict[str, Path],
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

        glossary_sources:
            Glossary term lists

    Returns:
        Number of stored matches.
    """
    paragraphs = list(paragraphs)

    all_loaded_terms: list[GlossaryTerm] = []
    for list_name, path in glossary_sources.items():
        all_loaded_terms.extend(load_terms_txt(path, list_name=list_name))

    database_ids = upsert_glossary_terms(connection, all_loaded_terms)

    database_terms = [
        GlossaryTerm(
            term_id=database_ids[(t.term.lower(), t.list_name)],
            term=t.term,
            list_name=t.list_name,
        )
        for t in all_loaded_terms
    ]

    matcher = GlossaryMatcher(database_terms)

    cursor = connection.cursor()

    paragraph_ids = [paragraph_id for paragraph_id, _ in paragraphs]

    if paragraph_ids:
        placeholders = ",".join("?" for _ in paragraph_ids)
        cursor.execute(
            f"""
            DELETE FROM paragraph_terms
            WHERE paragraph_id IN ({placeholders})
            """,
            paragraph_ids,
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

    return inserted

def reindex_all_glossary_matches(
    connection: sqlite3.Connection,
    glossary_sources: dict[str, Path],
) -> int:
    """
    Recompute glossary matches for every paragraph currently in the
    database, without touching OCR/extraction/chunking.

    Use this after editing a glossary .txt file, instead of
    re-running the full ingestion pipeline.
    """
    from database import repository  # local import avoids a cycle at module load

    paragraphs = repository.get_all_paragraphs_for_glossary(connection=connection)

    return index_paragraph_glossary_terms(
        connection,
        paragraphs,
        glossary_sources,
    )