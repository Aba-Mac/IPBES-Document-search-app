"""
search.service
==============

Public search API used by the Shiny application.

This module is the only entry point that should be called by the UI.
It composes the search pipeline:

    UI
      │
      ▼
parse_search_request()
      │
      ▼
search.boolean.parse_boolean_expression()
      │
      ▼
search.boolean.to_fts5_query()
      │
      ▼
execute_ranked_search()
      │
      ▼
SearchResponse

Responsibilities
----------------
* Parse incoming search requests.
* Delegate Boolean parsing.
* Execute ranked FTS5 searches.
* Expose metadata lookup functions.
* Provide a stable API for the UI.
* Reserve an extension point for future semantic ranking.

This module intentionally contains no SQL and no HTML rendering.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

from search.boolean import (
    BooleanParseError,
    parse_boolean_expression,
    to_fts5_query,
)

from search.parser import (
    SearchParserError,
    SearchRequest,
    parse_search_request,
)

from search.ranking import (
    RankingError,
    SearchResponse,
    execute_ranked_search,
)

logger = logging.getLogger(__name__)

__all__ = [
    "SearchService",
    "SearchServiceError",
    "search",
    "get_document",
    "get_available_sources",
    "get_available_years",
    "get_available_documents",
]

###############################################################################
# Exceptions
###############################################################################


class SearchServiceError(RuntimeError):
    """
    Raised when execution of the search service fails.
    """


###############################################################################
# Repository protocol
###############################################################################


class RepositoryProtocol(Protocol):
    """
    Repository interface required by SearchService.

    The concrete implementation is supplied by
    database.repository.DatabaseRepository.
    """

    #
    # Search methods
    #

    def search_paragraphs(self, **kwargs):
        ...

    def count_paragraphs(self, **kwargs):
        ...

    def get_paragraph_terms(self, paragraph_ids: list[int]):
        ...

    #
    # Metadata methods
    #

    def get_document(
        self,
        document_id: int,
    ) -> dict[str, Any] | None:
        ...

    def get_available_sources(self) -> list[str]:
        ...

    def get_available_years(self) -> list[int]:
        ...

    def get_available_documents(self) -> list[dict[str, Any]]:
        ...


###############################################################################
# Search service
###############################################################################


class SearchService:
    """
    Public search service.

    This class coordinates request parsing, Boolean parsing,
    FTS query generation and ranked retrieval.

    It intentionally performs no SQL itself.
    """

    def __init__(
        self,
        repository: RepositoryProtocol,
    ) -> None:
        self._repository = repository

    ###########################################################################
    # Public API
    ###########################################################################

    def search(
        self,
        query: str,
        filters: dict[str, Any] | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> SearchResponse:
        """
        Execute a paragraph search.

        Parameters
        ----------
        query
            Raw search string from the UI.

        filters
            Search filters.

        page
            Page number (1-based).

        page_size
            Results per page.

        Returns
        -------
        SearchResponse
        """
        logger.info(
            "Search request received."
        )

        request = self._parse_request(
            query=query,
            filters=filters,
            page=page,
            page_size=page_size,
        )

        fts_query = self._build_fts_query(
            request
        )

        response = execute_ranked_search(
            repository=self._repository,
            request=request,
            fts_query=fts_query,
        )

        #
        # ----------------------------------------------------------
        # Future semantic extension point.
        #
        # Later releases may inject a semantic re-ranking stage
        # here without altering the public interface.
        # ----------------------------------------------------------
        #

        response = self._postprocess_response(
            response
        )

        logger.info(
            "Search completed successfully."
        )

        return response

    ###########################################################################
    # Internal pipeline
    ###########################################################################

    def _parse_request(
        self,
        *,
        query: str,
        filters: dict[str, Any] | None,
        page: int,
        page_size: int,
    ) -> SearchRequest:
        """
        Parse UI request.
        """
        try:
            return parse_search_request(
                query=query,
                filters=filters,
                page=page,
                page_size=page_size,
            )

        except SearchParserError as exc:
            logger.warning(
                "Invalid search request."
            )
            raise SearchServiceError(
                str(exc)
            ) from exc

    def _build_fts_query(
        self,
        request: SearchRequest,
    ) -> str:
        """
        Convert Boolean syntax into an SQLite FTS5 query.
        """
        try:
            ast = parse_boolean_expression(
                request.query
            )

            return to_fts5_query(ast)

        except BooleanParseError as exc:
            logger.warning(
                "Boolean parser rejected query."
            )

            raise SearchServiceError(
                str(exc)
            ) from exc

        except Exception as exc:
            logger.exception(
                "Unexpected Boolean parser failure."
            )

            raise SearchServiceError(
                "Unable to process search query."
            ) from exc

    def _postprocess_response(
        self,
        response: SearchResponse,
    ) -> SearchResponse:
        """
        Extension point.

        Current implementation returns the
        response unchanged.

        Future releases may:

        * blend semantic ranking
        * boost topic-anchor matches
        * filter low-confidence semantic hits
        """
        return response


###############################################################################
# Module-level convenience API
###############################################################################

#
# The Shiny application can either instantiate SearchService
# directly or call these convenience wrappers.
#
# The wrappers keep the UI code concise while remaining fully
# testable through dependency injection.
#

_repository: RepositoryProtocol | None = None


def configure(
    repository: RepositoryProtocol,
) -> None:
    """
    Configure the module-level repository.

    Typically called once during application startup.
    """
    global _repository

    _repository = repository

    logger.info(
        "Search service configured."
    )


def _service() -> SearchService:
    """
    Return the configured service.
    """
    if _repository is None:
        raise SearchServiceError(
            "Search service has not been configured."
        )

    return SearchService(
        repository=_repository,
    )


def search(
    query: str,
    filters: dict[str, Any] | None = None,
    page: int = 1,
    page_size: int = 20,
) -> SearchResponse:
    """
    Execute a search.

    This is the primary entry point used by the
    Shiny application.
    """
    return _service().search(
        query=query,
        filters=filters,
        page=page,
        page_size=page_size,
    )


###############################################################################
# Metadata API
###############################################################################


def get_document(
    document_id: int,
) -> dict[str, Any] | None:
    """
    Return metadata for a single document.

    Parameters
    ----------
    document_id
        Internal document identifier.

    Returns
    -------
    dict[str, Any] | None
        Document metadata if found, otherwise ``None``.

    Raises
    ------
    SearchServiceError
        If the repository operation fails.
    """
    try:
        return _service()._repository.get_document(document_id)
    except Exception as exc:
        logger.exception(
            "Failed to retrieve document metadata "
            "(document_id=%s).",
            document_id,
        )
        raise SearchServiceError(
            "Unable to retrieve document."
        ) from exc


def get_available_sources() -> list[str]:
    """
    Return all available document sources.

    Returns
    -------
    list[str]
        Distinct sources ordered by the repository.

    Raises
    ------
    SearchServiceError
        If retrieval fails.
    """
    try:
        return _service()._repository.get_available_sources()
    except Exception as exc:
        logger.exception(
            "Failed to retrieve available sources."
        )
        raise SearchServiceError(
            "Unable to retrieve sources."
        ) from exc


def get_available_years() -> list[int]:
    """
    Return all available publication years.

    Returns
    -------
    list[int]
        Sorted publication years.

    Raises
    ------
    SearchServiceError
        If retrieval fails.
    """
    try:
        return _service()._repository.get_available_years()
    except Exception as exc:
        logger.exception(
            "Failed to retrieve available years."
        )
        raise SearchServiceError(
            "Unable to retrieve years."
        ) from exc


def get_available_documents() -> list[dict[str, Any]]:
    """
    Return document metadata for populating UI selectors.

    Each returned dictionary should contain sufficient information
    for display, typically including:

    - document_id
    - title
    - filename
    - source
    - year
    - plenary_session
    - location

    Returns
    -------
    list[dict[str, Any]]

    Raises
    ------
    SearchServiceError
        If retrieval fails.
    """
    try:
        return _service()._repository.get_available_documents()
    except Exception as exc:
        logger.exception(
            "Failed to retrieve available documents."
        )
        raise SearchServiceError(
            "Unable to retrieve document list."
        ) from exc


###############################################################################
# Design notes
###############################################################################

#
# Layer responsibilities
# ----------------------
#
# search.parser
#     Validate and normalise incoming UI requests.
#
# search.boolean
#     Parse Boolean syntax and generate an SQLite FTS5 query.
#
# search.ranking
#     Execute repository searches and construct typed result models.
#
# search.service
#     Compose the search pipeline and expose a stable API to the UI.
#
#
# Future semantic search
# ----------------------
#
# The current implementation intentionally performs exact-match
# glossary search backed by SQLite FTS5 BM25 ranking only.
#
# Although the ingestion pipeline stores topic-anchor tags and
# embeddings, they are NOT consulted here.
#
# A future implementation can extend the pipeline after
# execute_ranked_search() by replacing or enhancing
# _postprocess_response() without changing:
#
#     search(...)
#     get_document(...)
#     get_available_sources(...)
#     get_available_years(...)
#     get_available_documents(...)
#
# This preserves a stable API for the Shiny application while allowing
# semantic re-ranking, topic filtering, or hybrid retrieval to be added
# later.
#

###############################################################################
# End of module
###############################################################################