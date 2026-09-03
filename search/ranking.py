"""
search.ranking
==============

Executes ranked SQLite FTS5 searches against the paragraph index.

This module is responsible for translating a parsed Boolean query into
database calls, applying SQLite FTS5 BM25 ranking, pagination, and
constructing strongly typed search results for consumption by the
search service.

Responsibilities
----------------
- Execute parameterised FTS5 searches via database.repository.
- Apply SQLite BM25 ranking.
- Apply document/source/year filtering.
- Apply pagination.
- Attach glossary term matches.
- Return paragraph-level results.
- Provide a clear extension point for future semantic re-ranking.

This module intentionally does NOT:

- Parse Boolean expressions (search.boolean).
- Parse raw UI requests (search.parser).
- Generate HTML.
- Generate glossary hyperlinks.
- Perform semantic search.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Iterable, Protocol

from search.parser import SearchFilters, SearchRequest

logger = logging.getLogger(__name__)

__all__ = [
    "SearchResult",
    "SearchResponse",
    "RankingError",
    "SearchRepositoryProtocol",
    "execute_ranked_search",
]

###############################################################################
# Exceptions
###############################################################################


class RankingError(RuntimeError):
    """
    Raised when ranking execution fails.
    """


###############################################################################
# Repository protocol
###############################################################################


class SearchRepositoryProtocol(Protocol):
    """
    Repository interface required by this module.

    The concrete implementation is provided by
    ``database.repository``.
    """
    def connect(self) -> Any:
        """
        Open a new database connection.
        """
        ...

    def count_paragraphs(
        self,
        *,
        fts_query: str,
        filters: SearchFilters | None = None,
        connection: Any = None,
    ) -> int:
        """
        Return total matching paragraph count.
        """
        ...

    def search_paragraphs(
        self,
        *,
        fts_query: str,
        source: str | None,
        year: tuple[int, int] | None,
        document_id: int | None,
        glossary_lists: tuple[str, ...] | None,
        limit: int,
        offset: int,
        connection: Any = None,
    ) -> list[Any]:
        """
        Return the paragraph rows for one page of ranked results.
        """
        ...

    def get_paragraph_terms(
        self,
        paragraph_id: int,
        *,
        connection: Any = None,
    ) -> list[Any]:
        """
        Return glossary term rows for a single paragraph.
        """
        ...


###############################################################################
# Result models
###############################################################################


@dataclass(frozen=True, slots=True)
class SearchResult:
    """
    Single ranked paragraph result.
    """

    paragraph_id: int

    document_id: int

    document_title: str

    doi: str | None

    filename: str

    source: str

    year: int | None

    plenary_session: str | None

    location: str | None

    page_number: int

    paragraph_number: int

    text: str

    matched_terms: list[str]

    bm25_score: float


@dataclass(frozen=True, slots=True)
class SearchResponse:
    """
    Paginated ranked search response.
    """

    query: str

    page: int

    page_size: int

    total_results: int

    total_pages: int

    results: list[SearchResult] = field(default_factory=list)

    @property
    def has_previous(self) -> bool:
        return self.page > 1

    @property
    def has_next(self) -> bool:
        return self.page < self.total_pages


@dataclass
class SearchPage:
    results: list[SearchResult]
    total_count: int
    page: int
    page_size: int

    @property
    def total_pages(self) -> int:
        if self.total_count == 0:
            return 1

        return (
            self.total_count + self.page_size - 1
        ) // self.page_size


###############################################################################
# Public API
###############################################################################


def execute_ranked_search(
    *,
    repository: SearchRepositoryProtocol,
    request: SearchRequest,
    fts_query: str,
) -> SearchResponse:
    """
    Execute a ranked paragraph search.

    Parameters
    ----------
    repository
        Database repository.

    request
        Parsed search request.

    fts_query
        SQLite FTS5 query produced from the Boolean parser.

    Returns
    -------
    SearchResponse

    Raises
    ------
    RankingError
    """
    logger.info(
        "Executing ranked search "
        "(page=%s page_size=%s).",
        request.page,
        request.page_size,
    )

    connection = repository.connect()

    try:
        try:
            total = repository.count_paragraphs(
                fts_query=fts_query,
                filters=request.filters,
                connection=connection,
            )

            rows = _validate_repository_rows(
                repository.search_paragraphs(
                    fts_query=fts_query,
                    source=request.filters.source,
                    year=request.filters.year,
                    document_id=request.filters.document,
                    glossary_lists=request.filters.glossary_lists, 
                    limit=request.limit,
                    offset=request.offset,
                    connection=connection,
                )
            )

        except Exception as exc:
            logger.exception("Database search failed.")
            raise RankingError("Search execution failed.") from exc

        logger.debug(
            "Repository returned %d rows (%d total).",
            len(rows),
            total,
        )

        results = _build_results(
            repository=repository,
            rows=rows,
            connection=connection,
        )
    finally:
        connection.close()

    #
    # ------------------------------------------------------------------
    # Future semantic ranking extension point.
    #
    # This hook intentionally does nothing in the current release.
    #
    # A future version may:
    #
    # - re-rank BM25 results
    # - filter using topic tags
    # - blend embedding similarity
    #
    # without changing the public API.
    # ------------------------------------------------------------------
    #
    results = _postprocess_results(results)

    return SearchResponse(
        query=request.query,
        page=request.page,
        page_size=request.page_size,
        total_results=total,
        total_pages=_calculate_total_pages(
            total,
            request.page_size,
        ),
        results=results,
    )


###############################################################################
# Result construction
###############################################################################


def _build_results(
    *,
    repository: SearchRepositoryProtocol,
    rows: list[dict[str, Any]],
    connection: Any = None,
) -> list[SearchResult]:
    """
    Construct typed search results.
    """
    if not rows:
        return []

    glossary_map: dict[int, list[str]] = {}

    for row in rows:
        paragraph_id = int(row["paragraph_id"])

        term_rows = repository.get_paragraph_terms(
            paragraph_id,
            connection=connection,
        )

        glossary_map[paragraph_id] = [
            term_row["term"]
            for term_row in term_rows
        ]

    results: list[SearchResult] = []

    for row in rows:
        paragraph_id = int(row["paragraph_id"])

        result = SearchResult(
            paragraph_id=paragraph_id,
            document_id=int(row["document_id"]),
            document_title=row["document_title"],
            doi=row["doi"],
            filename=row["filename"],
            source=row["source"],
            year=row["year"],
            plenary_session=row["plenary_session"],
            location=row["location"],
            page_number=int(row["page_number"]),
            paragraph_number=int(row["paragraph_number"]),
            text=row["paragraph_text"],
            matched_terms=sorted(
                glossary_map.get(paragraph_id, [])
            ),
            bm25_score=float(row["bm25_score"]),
        )

        results.append(result)

    logger.debug(
        "Constructed %d SearchResult objects.",
        len(results),
    )

    return results


###############################################################################
# Extension hook
###############################################################################


def _postprocess_results(
    results: list[SearchResult],
) -> list[SearchResult]:
    """
    Extension point for future ranking stages.

    Current implementation returns the BM25-ranked
    results unchanged.

    Future versions may optionally:

    - blend semantic similarity
    - boost topic-anchor matches
    - demote low-confidence results
    - personalise ranking

    without modifying callers.
    """
    return results


###############################################################################
# Pagination helpers
###############################################################################


def _calculate_total_pages(
    total_results: int,
    page_size: int,
) -> int:
    """
    Compute total page count.
    """
    if total_results == 0:
        return 0

    pages = total_results // page_size

    if total_results % page_size:
        pages += 1

    return pages


###############################################################################
# Row validation and conversion helpers
###############################################################################


_REQUIRED_COLUMNS: frozenset[str] = frozenset(
    {
        "paragraph_id",
        "document_id",
        "document_title",
        "filename",
        "source",
        "year",
        "plenary_session",
        "location",
        "page_number",
        "paragraph_number",
        "paragraph_text",
        "bm25_score",
    }
)


def _validate_repository_rows(
    rows: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Validate repository result rows.

    This function performs defensive validation of the repository
    output before result objects are constructed. It guards against
    schema drift or repository implementation errors.

    Parameters
    ----------
    rows
        Iterable of row dictionaries returned by the repository.

    Returns
    -------
    list[dict[str, Any]]
        Validated rows.

    Raises
    ------
    RankingError
        If a required column is missing.
    """
    validated: list[dict[str, Any]] = []

    for index, row in enumerate(rows):
        missing = _REQUIRED_COLUMNS.difference(row.keys())

        if missing:
            raise RankingError(
                "Repository row %d is missing required columns: %s"
                % (index, ", ".join(sorted(missing)))
            )

        validated.append(row)

    return validated