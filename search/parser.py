"""
search.parser
=============

Parses search requests received from the Shiny UI into a validated,
structured request object suitable for the search service.

This module is responsible only for request parsing and validation.
It does NOT parse Boolean expressions (handled by search.boolean) and
does NOT execute database queries.

Responsibilities
----------------
- Normalise and validate raw user input.
- Validate pagination settings.
- Validate filter selections.
- Produce immutable request models.
- Leave Boolean parsing to search.boolean.

Example
-------
>>> request = parse_search_request(
...     query="data AND governance",
...     filters={"year": 2024},
...     page=1,
...     page_size=20,
... )

>>> request.query
'data AND governance'

>>> request.filters.year
2024
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

__all__ = [
    "SearchFilters",
    "SearchRequest",
    "SearchParserError",
    "parse_search_request",
]

###############################################################################
# Constants
###############################################################################

_ALLOWED_PAGE_SIZES = frozenset({10, 20, 50})

_BOOLEAN_KEYWORDS = {
    "AND",
    "OR",
    "NOT",
    "NOR",
}

_WHITESPACE_RE = re.compile(r"\s+")

###############################################################################
# Exceptions
###############################################################################


class SearchParserError(ValueError):
    """Raised when a search request is invalid."""


###############################################################################
# Data models
###############################################################################


@dataclass(frozen=True, slots=True)
class SearchFilters:
    """
    Structured search filters.

    All fields are optional.

    Attributes
    ----------
    source
        Document source.

    year
        Publication year.

    document
        Internal document identifier.
    """

    source: str | None = None
    year: tuple[int, int] | None = None
    document: int | None = None


@dataclass(frozen=True, slots=True)
class SearchRequest:
    """
    Immutable parsed search request.

    Parameters
    ----------
    query
        Normalised Boolean search expression.

    filters
        Validated search filters.

    page
        1-based page number.

    page_size
        Number of results per page.
    """

    query: str
    filters: SearchFilters = field(default_factory=SearchFilters)
    page: int = 1
    page_size: int = 20

    @property
    def offset(self) -> int:
        """
        SQLite OFFSET corresponding to this request.
        """
        return (self.page - 1) * self.page_size

    @property
    def limit(self) -> int:
        """
        SQLite LIMIT corresponding to this request.
        """
        return self.page_size


###############################################################################
# Public API
###############################################################################


def parse_search_request(
    query: str,
    filters: dict[str, Any] | None = None,
    page: int = 1,
    page_size: int = 20,
) -> SearchRequest:
    """
    Parse and validate a search request.

    This function performs request validation only.

    It intentionally does not attempt to interpret Boolean syntax;
    parsing of Boolean expressions is delegated to
    ``search.boolean``.

    Parameters
    ----------
    query
        Raw search string from the UI.

    filters
        Optional dictionary containing UI filter selections.

        Supported keys:

        - source
        - year
        - document

    page
        1-based page number.

    page_size
        Allowed values are:

        - 10
        - 20
        - 50

    Returns
    -------
    SearchRequest

    Raises
    ------
    SearchParserError
        If any supplied values are invalid.
    """
    logger.debug("Parsing search request.")

    normalised_query = _normalise_query(query)

    parsed_filters = _parse_filters(filters)

    validated_page = _validate_page(page)

    validated_page_size = _validate_page_size(page_size)

    request = SearchRequest(
        query=normalised_query,
        filters=parsed_filters,
        page=validated_page,
        page_size=validated_page_size,
    )

    logger.debug("Search request parsed successfully: %s", request)

    return request


###############################################################################
# Query parsing
###############################################################################


def _normalise_query(query: str) -> str:
    """
    Normalise a user-entered search query.

    The parser deliberately performs only minimal
    transformations so that Boolean parsing
    remains the responsibility of search.boolean.

    Operations performed:

    - trim leading/trailing whitespace
    - collapse repeated whitespace
    - uppercase Boolean keywords
    - preserve quoted phrases
    - preserve parentheses
    """
    if query is None:
        raise SearchParserError("Search query cannot be None.")

    if not isinstance(query, str):
        raise SearchParserError("Search query must be a string.")

    query = query.strip()

    if not query:
        raise SearchParserError("Search query cannot be empty.")

    query = _WHITESPACE_RE.sub(" ", query)

    tokens = query.split(" ")

    normalised = []

    for token in tokens:
        upper = token.upper()

        if upper in _BOOLEAN_KEYWORDS:
            normalised.append(upper)
        else:
            normalised.append(token)

    query = " ".join(normalised)

    logger.debug("Normalised query: %s", query)

    return query


###############################################################################
# Filter parsing
###############################################################################


def _parse_filters(
    filters: dict[str, Any] |None,
) -> SearchFilters:
    """
    Parse UI filter selections.
    """
    if filters is None:
        return SearchFilters()

    if not isinstance(filters, dict):
        raise SearchParserError(
            "Filters must be supplied as a dictionary."
        )

    source = _parse_source(filters.get("source"))
    year = _parse_year(filters.get("year"))
    document = _parse_document(filters.get("document"))

    return SearchFilters(
        source=source,
        year=year,
        document=document,
    )


def _parse_source(value: Any) -> str | None:
    """
    Parse source filter.
    """
    if value in ("", None):
        return None

    if not isinstance(value, str):
        raise SearchParserError("Source filter must be a string.")

    value = value.strip()

    if not value:
        return None

    return value


def _parse_year(value: Any) -> tuple[int, int] | None:
    """
    Parse year range filter.

    Expects a 2-tuple/list of (min_year, max_year). A bare single
    year (int or numeric string) is also accepted for convenience
    and normalised to a one-year range.
    """
    if value in ("", None):
        return None

    if isinstance(value, (tuple, list)):
        if len(value) != 2:
            raise SearchParserError(
                "Year filter must contain exactly two values (min, max)."
            )
        raw_min, raw_max = value
    else:
        raw_min = raw_max = value

    try:
        year_min = int(raw_min)
        year_max = int(raw_max)
    except Exception as exc:
        raise SearchParserError(
            "Year filter values must be integers."
        ) from exc

    if year_min < 1900 or year_max > 3000:
        raise SearchParserError(
            "Year filter is outside the valid range."
        )

    if year_min > year_max:
        year_min, year_max = year_max, year_min

    return (year_min, year_max)


def _parse_document(value: Any) -> int | None:
    """
    Parse document filter.
    """
    if value in ("", None):
        return None

    try:
        document = int(value)
    except Exception as exc:
        raise SearchParserError(
            "Document filter must be an integer."
        ) from exc

    if document <= 0:
        raise SearchParserError(
            "Document identifier must be positive."
        )

    return document


###############################################################################
# Pagination validation
###############################################################################


def _validate_page(page: int) -> int:
    """
    Validate page number.
    """
    try:
        page = int(page)
    except Exception as exc:
        raise SearchParserError(
            "Page number must be an integer."
        ) from exc

    if page < 1:
        raise SearchParserError(
            "Page number must be at least 1."
        )

    return page


def _validate_page_size(page_size: int) -> int:
    """
    Validate page size.
    """
    try:
        page_size = int(page_size)
    except Exception as exc:
        raise SearchParserError(
            "Page size must be an integer."
        ) from exc

    if page_size not in _ALLOWED_PAGE_SIZES:
        raise SearchParserError(
            f"Unsupported page size: {page_size}. "
            f"Allowed values are "
            f"{sorted(_ALLOWED_PAGE_SIZES)}."
        )

    return page_size