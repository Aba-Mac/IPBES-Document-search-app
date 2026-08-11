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

from shiny import App, reactive, ui
from search.service import get_glossary_terms

from search.service import (
    SearchServiceError,
    get_available_years,
    search,
    configure
)

from ui.cards import register_card_renderer
from ui.layouts import build_page
from ui.search import (
    build_search_controls,
    current_page,
    page_size,
    search_query,
    selected_year_range,
    SEARCH_QUERY_ID,
    YEAR_FILTER_ID,
)
from ui.styles import app_css

from database import repository

configure(repository)

logger = logging.getLogger(__name__)


###############################################################################
# Static application data
###############################################################################

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
    years = _load_years()

    return build_page(
        search_controls=build_search_controls(
            years=years,
        ),
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

    available_years = reactive.value(_load_years())
    
    current_page = reactive.value(1)

    @reactive.effect
    async def _update_glossary_terms():
        terms = get_glossary_terms()

        logger.info("Loaded glossary terms for autocomplete: %s", len(terms))

        await session.send_custom_message(
            "glossary_terms",
            {"terms": terms},
        )

    @reactive.effect
    def _update_year_choices():
        years = _load_years()

        logger.info("Loaded years: %s", years)

        ui.update_slider(
            YEAR_FILTER_ID,
            min=min(years),
            max=max(years),
            value=(min(years), max(years)),
            step=1,
        )

    @reactive.effect
    @reactive.event(input.search_button)
    def reset_page():
        current_page.set(1)
        
    @reactive.calc
    @reactive.event(input.search_button)
    def search_results():
        filters: dict[str, object] = {}

        years = available_years()
        full_range = (min(years), max(years))

        year_range = selected_year_range(input, full_range=full_range)

        if year_range:
            filters["year"] = year_range

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
                page=current_page(),
                page_size=page_size(20),
            )

        except SearchServiceError:
            logger.exception("Search failed.")
            raise

    @output
    @render.text
    def page_info():
        response = search_results()

        return (
            f"Page {response.page} "
            f"of {response.total_pages}"
        )

    @reactive.effect
    def update_previous_button():
        response = search_results()

        ui.update_action_button(
            "prev_page",
            disabled=not response.has_previous,
        )

    @reactive.effect
    def update_next_button():
        response = search_results()

        ui.update_action_button(
            "next_page",
            disabled=not response.has_next,
        )

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

    _ = available_years


###############################################################################
# Application
###############################################################################

app = App(
    ui=build_app_ui(),
    server=server,
)