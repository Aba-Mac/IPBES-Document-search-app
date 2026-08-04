"""
tests/search/test_service.py

Tests for search.service.

Covers:

- SearchService orchestration
- request parsing
- Boolean query conversion
- ranking delegation
- response passthrough
- repository metadata helpers
- configuration errors
"""

from __future__ import annotations

from unittest.mock import Mock, patch

import pytest

import search.service as service

from search.service import (
    SearchService,
    SearchServiceError,
)


# ---------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------


class DummyResponse:
    """Minimal stand-in for SearchResponse."""

    def __init__(self):
        self.results = []


class DummyRepository:
    """
    Minimal repository implementation
    satisfying RepositoryProtocol.
    """

    def search_paragraphs(self, **kwargs):
        return []

    def count_paragraphs(self, **kwargs):
        return 0

    def get_paragraph_terms(self, paragraph_ids):
        return {}

    def get_document(self, document_id):
        return {
            "id": document_id,
            "title": "Test document",
        }

    def get_available_sources(self):
        return [
            "source-a",
            "source-b",
        ]

    def get_available_years(self):
        return [
            2023,
            2024,
        ]

    def get_available_documents(self):
        return [
            {
                "id": 1,
                "title": "Document",
            }
        ]


@pytest.fixture
def repository():
    return DummyRepository()


@pytest.fixture
def search_service(repository):
    return SearchService(repository)


# ---------------------------------------------------------------------
# SearchService construction
# ---------------------------------------------------------------------


class TestSearchServiceInit:

    def test_initialises_with_repository(
        self,
        repository,
    ):
        svc = SearchService(repository)

        assert svc._repository is repository


# ---------------------------------------------------------------------
# Search pipeline
# ---------------------------------------------------------------------


class TestSearchPipeline:

    @patch(
        "search.service.execute_ranked_search"
    )
    @patch(
        "search.service.parse_search_request"
    )
    @patch(
        "search.service.parse_boolean_expression"
    )
    @patch(
        "search.service.to_fts5_query"
    )
    def test_search_executes_pipeline(
        self,
        mock_to_fts,
        mock_parse_boolean,
        mock_parse_request,
        mock_rank,
        search_service,
    ):
        request = Mock()

        mock_parse_request.return_value = request

        ast = Mock()

        mock_parse_boolean.return_value = ast

        mock_to_fts.return_value = (
            "climate"
        )

        response = DummyResponse()

        mock_rank.return_value = response

        result = search_service.search(
            query="climate",
        )

        assert result is response

        mock_parse_request.assert_called_once()

        mock_parse_boolean.assert_called_once()

        mock_to_fts.assert_called_once_with(
            ast
        )

        mock_rank.assert_called_once_with(
            repository=search_service._repository,
            request=request,
            fts_query="climate",
        )

    def test_postprocess_returns_same_response(
        self,
        search_service,
    ):
        response = DummyResponse()

        assert (
            search_service._postprocess_response(
                response
            )
            is response
        )


# ---------------------------------------------------------------------
# Request parsing failures
# ---------------------------------------------------------------------


class TestRequestErrors:

    @patch(
        "search.service.parse_search_request"
    )
    def test_parser_error_becomes_service_error(
        self,
        mock_parser,
        search_service,
    ):
        mock_parser.side_effect = (
            service.SearchParserError(
                "invalid"
            )
        )

        with pytest.raises(
            SearchServiceError
        ):
            search_service.search(
                "bad query"
            )


# ---------------------------------------------------------------------
# Boolean failures
# ---------------------------------------------------------------------


class TestBooleanErrors:

    @patch(
        "search.service.parse_search_request"
    )
    @patch(
        "search.service.parse_boolean_expression"
    )
    def test_boolean_error_becomes_service_error(
        self,
        mock_boolean,
        mock_request,
        search_service,
    ):
        mock_request.return_value = Mock()

        mock_boolean.side_effect = (
            service.BooleanSyntaxError(
                "bad syntax"
            )
        )

        with pytest.raises(
            SearchServiceError
        ):
            search_service.search(
                "A AND"
            )


# ---------------------------------------------------------------------
# Ranking failures
# ---------------------------------------------------------------------


class TestRankingErrors:

    @patch(
        "search.service.execute_ranked_search"
    )
    @patch(
        "search.service.parse_search_request"
    )
    @patch(
        "search.service.parse_boolean_expression"
    )
    @patch(
        "search.service.to_fts5_query"
    )
    def test_ranking_failure_is_propagated(
        self,
        mock_to_fts,
        mock_boolean,
        mock_request,
        mock_rank,
        search_service,
    ):
        mock_request.return_value = Mock()

        mock_boolean.return_value = Mock()

        mock_to_fts.return_value = (
            "query"
        )

        mock_rank.side_effect = (
            service.RankingError(
                "failed"
            )
        )

        with pytest.raises(
            service.RankingError
        ):
            search_service.search(
                "climate"
            )


# ---------------------------------------------------------------------
# Module-level configuration
# ---------------------------------------------------------------------


class TestModuleAPI:

    def teardown_method(self):
        service._repository = None

    def test_unconfigured_service_raises(self):

        with pytest.raises(
            SearchServiceError
        ):
            service.search(
                "climate"
            )

    def test_configure_sets_repository(
        self,
        repository,
    ):
        service.configure(
            repository
        )

        assert service._repository is repository

    @patch.object(
        SearchService,
        "search",
    )
    def test_module_search_delegates(
        self,
        mock_search,
        repository,
    ):
        service.configure(
            repository
        )

        expected = DummyResponse()

        mock_search.return_value = expected

        result = service.search(
            "climate"
        )

        assert result is expected

        mock_search.assert_called_once()


# ---------------------------------------------------------------------
# Metadata API
# ---------------------------------------------------------------------


class TestMetadataAPI:

    def setup_method(self):
        service._repository = None

    def teardown_method(self):
        service._repository = None

    def test_get_document(
        self,
        repository,
    ):
        service.configure(
            repository
        )

        result = service.get_document(
            1
        )

        assert result["id"] == 1

    def test_get_sources(
        self,
        repository,
    ):
        service.configure(
            repository
        )

        assert service.get_available_sources() == [
            "source-a",
            "source-b",
        ]

    def test_get_years(
        self,
        repository,
    ):
        service.configure(
            repository
        )

        assert service.get_available_years() == [
            2023,
            2024,
        ]

    def test_get_documents(
        self,
        repository,
    ):
        service.configure(
            repository
        )

        documents = (
            service.get_available_documents()
        )

        assert len(documents) == 1