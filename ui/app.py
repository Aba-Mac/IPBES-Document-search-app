"""
ui.app
======

Assemble the Shiny for Python application.

This module composes the user interface and server logic while
delegating all business logic to the project's service modules.

Responsibilities
----------------
* Assemble the application UI.
* Wire together the layout, search controls, glossary panel and
  result cards.
* Coordinate reactive search execution.
* Populate filter controls from the search service.
* Delegate search execution to ``search.service``.
* Delegate paragraph rendering to ``ui.cards`` (which in turn uses
  ``renderer.renderer``).

This module intentionally contains no SQL, Boolean parsing,
highlighting logic or HTML rendering.
"""

from __future__ import annotations

import logging

from shiny import App, reactive

from search.service import (
    SearchServiceError,
    get_available_sources,
    get_available_years,
    search,
)

from ui.cards import register_card_renderer
from ui.glossary import build_glossary_panel
from ui.glossary import GLOSSARY_SEARCH_ID
from ui.layouts import build_page
from ui.search import (
    build_search_controls,
    boolean_query,
    current_page,
    page_size,
    search_query,
    selected_source,
    selected_year,
    SEARCH_QUERY_ID,
)
from ui.styles import app_css

logger = logging.getLogger(__name__)


###############################################################################
# Static application data
###############################################################################

def _load_sources() -> tuple[str, ...]:
    """
    Load available document sources.

    Loaded lazily after the application has started.
    """
    return tuple(get_available_sources())


def _load_years() -> tuple[int, ...]:
    """
    Load available document years.

    Loaded lazily after the application has started.
    """
    return tuple(get_available_years())


###############################################################################
# User interface
###############################################################################

def build_app_ui():
    """
    Build the Shiny UI after services are configured.
    """

    sources = _load_sources()
    years = _load_years()

    return build_page(
        search_controls=build_search_controls(
            sources=sources,
            years=years,
        ),
        glossary_panel=build_glossary_panel(),
        css=app_css(),
    )


###############################################################################
# Server
###############################################################################

def server(input, output, session) -> None:
    """
    Main Shiny server.

    The server coordinates reactive state only. All searching is
    delegated to ``search.service``.
    """

    #
    # Static lookup values exposed reactively for future use.
    #

    available_sources = reactive.value(_load_sources())
    available_years = reactive.value(_load_years())

    @reactive.effect
    def _update_glossary_terms():

        terms = [
            row["term"]
            for row in repository.list_terms()
        ]

        ui.update_selectize(
            GLOSSARY_SEARCH_ID,
            choices=terms,
            server=True,
        )

    @reactive.calc
    def search_results():
        """
        Execute a search using the public search service API.

        Returns
        -------
        SearchResponse
            Search results from the service layer.
        """
        filters: dict[str, object] = {}

        if selected_source(input):
            filters["source"] = selected_source(input)

        if selected_year(input):
            filters["year"] = selected_year(input)

        query = boolean_query(input).strip()

        #
        # If no Boolean query is supplied, fall back to the simple
        # search box.
        #
        if not query:
            query = search_query(input).strip()

        logger.info(
            "Executing search "
            "(query=%r, page=%s)",
            query,
            current_page(input),
        )

        try:
            return search(
                query=query,
                filters=filters or None,
                page=current_page(input),
                page_size=page_size(input),
            )

        except SearchServiceError:
            logger.exception("Search failed.")
            raise

    #
    # Register output renderers.
    #
    # ui.cards owns presentation logic. It will call
    # renderer.renderer internally.
    #

    register_card_renderer(
        output=output,
        results=search_results,
    )

    #
    # Future extension points
    #
    # * search statistics
    # * search duration
    # * saved searches
    # * semantic search toggle
    # * topic filter panel
    #

    _ = available_sources
    _ = available_years


###############################################################################
# Application
###############################################################################

app = App(
    ui=build_app_ui(),
    server=server,
)