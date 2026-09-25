"""
glossary.py.

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
import ftfy
import logging

logger = logging.getLogger(__name__)


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

    @property
    def terms(self) -> list[GlossaryTerm]:
        return self._terms

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
    Load glossary terms from a plain text file, one term per line.
    Tolerates files saved in a non-UTF-8 encoding (e.g. Windows-1252)
    by repairing them with ftfy rather than failing ingestion.
    """
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        logger.warning(
            "%s is not valid UTF-8; repairing with ftfy. "
            "Re-save it as UTF-8 to remove this warning.",
            path,
        )
        text = ftfy.fix_text(raw.decode("latin-1"))

    terms: list[GlossaryTerm] = []
    for index, line in enumerate(text.splitlines(), start=1):
        term = line.strip()
        if term:
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


def build_matcher(
    connection: sqlite3.Connection,
    glossary_sources: dict[str, Path],
) -> GlossaryMatcher:
    """
    Load the glossary files, upsert the terms into the database and return
    a compiled matcher that uses the database term ids.
    """
    loaded = [
        term
        for list_name, path in glossary_sources.items()
        for term in load_terms_txt(path, list_name=list_name)
    ]
    database_ids = upsert_glossary_terms(connection, loaded)

    return GlossaryMatcher(
        GlossaryTerm(
            term_id=database_ids[(t.term.lower(), t.list_name)],
            term=t.term,
            list_name=t.list_name,
        )
        for t in loaded
    )


def index_paragraph_glossary_terms(
    connection: sqlite3.Connection,
    paragraphs: Iterable[tuple[int, str]],
    matcher: GlossaryMatcher,
) -> int:
    """
    Compute glossary matches for (paragraph_id, text) pairs and store them.
    Existing rows for these paragraphs are removed first, so it is idempotent.
    Returns the number of stored matches.
    """
    paragraphs = list(paragraphs)

    connection.executemany(
        "DELETE FROM paragraph_terms WHERE paragraph_id = ?",
        [(paragraph_id,) for paragraph_id, _ in paragraphs],
    )

    rows = [
        (m.paragraph_id, m.term_id, m.occurrence_count)
        for paragraph_id, text in paragraphs
        for m in matcher.find_matches(paragraph_id, text)
    ]
    connection.executemany(
        """
        INSERT INTO paragraph_terms(paragraph_id, term_id, occurrence_count)
        VALUES (?, ?, ?)
        """,
        rows,
    )
    return len(rows)


def reindex_all_glossary_matches(
    connection: sqlite3.Connection,
    glossary_sources: dict[str, Path],
) -> int:
    """
    Recompute glossary matches for every paragraph and remove terms that
    are no longer in any glossary file. Use after editing a glossary .txt.
    """
    from database import repository

    matcher = build_matcher(connection, glossary_sources)
    paragraphs = repository.get_all_paragraphs_for_glossary(connection=connection)
    inserted = index_paragraph_glossary_terms(connection, paragraphs, matcher)

    current_ids = {t.term_id for t in matcher.terms}
    stale = [
        (row[0],)
        for row in connection.execute("SELECT id FROM terms").fetchall()
        if row[0] not in current_ids
    ]
    connection.executemany("DELETE FROM terms WHERE id = ?", stale)

    return inserted