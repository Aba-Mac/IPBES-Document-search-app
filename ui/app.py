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

from shiny import App, reactive, ui, render
from search.service import get_glossary_terms

from search.service import (
    SearchServiceError,
    get_available_years,
    search,
    configure
)

from ui.cards import register_card_renderer
from ui.layouts import build_page, build_about_modal
from ui.search import (
    build_search_controls,
    search_query,
    selected_glossary_lists,
)
from ui.styles import app_css

from database import repository

configure(repository)

logger = logging.getLogger(__name__)


_GLOSSARY_CLICK_JS = """
document.addEventListener('click', function (e) {
    var link = e.target.closest('.glossary-link');
    if (!link) return;

    e.preventDefault();

    var term = link.dataset.term;

    var box = document.getElementById('search_query');
    if (box) box.value = term;

    Shiny.setInputValue('search_query', term, {priority: 'event'});

    var btn = document.getElementById('search_button');
    if (btn) btn.click();
});
"""

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

    page = build_page(
        search_controls=build_search_controls(
            years=years,
        ),
        css=app_css(),
    )

    return ui.TagList(
        ui.head_content(ui.tags.script(_GLOSSARY_CLICK_JS)),
        page,
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

    available_years = reactive.value(_load_years())

    current_page = reactive.value(1)

    submitted_query = reactive.value("")

    # ---------------------------------------------------------------
    # About section
    # ---------------------------------------------------------------

    @reactive.effect
    @reactive.event(input.about_button)
    def _show_about_modal():
        ui.modal_show(build_about_modal())

    # ---------------------------------------------------------------
    # Reset pagination when a new search is submitted
    # ---------------------------------------------------------------

    @reactive.effect
    @reactive.event(input.search_button)
    def perform_search():
        query = search_query(input).strip()

        if not query:
            return

        submitted_query.set(query)
        current_page.set(1)

    # ---------------------------------------------------------------
    # Previous and next page
    # ---------------------------------------------------------------

    @reactive.effect
    @reactive.event(input.prev_page)
    def previous_page():
        if current_page.get() > 1:
            current_page.set(current_page.get() - 1)


    @reactive.effect
    @reactive.event(input.next_page)
    def next_page():
        current_page.set(current_page.get() + 1)

    # ---------------------------------------------------------------
    # Glossary
    # ---------------------------------------------------------------

    @reactive.effect
    async def _update_glossary_terms():
        lists = selected_glossary_lists(input)
        terms = get_glossary_terms(list_names=lists or None)

        logger.info(
            "Loaded glossary terms for autocomplete: %s",
            len(terms),
        )

        await session.send_custom_message(
            "glossary_terms",
            {"terms": terms},
        )

    # ---------------------------------------------------------------
    # Search
    # ---------------------------------------------------------------

    @reactive.calc
    def search_results():
        query = submitted_query.get()

        if not query:
            return None

        filters: dict[str, object] = {}

        lists = selected_glossary_lists(input)
        if lists:
            filters["glossary_lists"] = lists

        page = current_page.get()

        logger.info(
            "Executing search (query=%r, page=%s)",
            query,
            page,
        )

        try:
            return search(
                query=query,
                filters=filters or None,
                page=page,
            )

        except SearchServiceError:
            logger.exception("Search failed.")
            raise


    # ---------------------------------------------------------------
    # Pagination display
    # ---------------------------------------------------------------

    @output
    @render.text
    def page_info():
        response = search_results()

        if response is None:
            return ""

        return (
            f"Page {response.page} "
            f"of {response.total_pages}"
        )

    # ---------------------------------------------------------------
    # Previous button state
    # ---------------------------------------------------------------

    @reactive.effect
    def update_previous_button():
        response = search_results()

        if response is None:
            ui.update_action_button(
                "prev_page",
                disabled=True,
            )
            return

        ui.update_action_button(
            "prev_page",
            disabled=not response.has_previous,
        )

    # ---------------------------------------------------------------
    # Next button state
    # ---------------------------------------------------------------

    @reactive.effect
    def update_next_button():
        response = search_results()

        if response is None:
            ui.update_action_button(
                "next_page",
                disabled=True,
            )
            return

        ui.update_action_button(
            "next_page",
            disabled=not response.has_next,
        )

    # ---------------------------------------------------------------
    # Results renderer
    # ---------------------------------------------------------------

    register_card_renderer(
        output=output,
        results=search_results,
    )

    _ = available_years


###############################################################################
# Application
###############################################################################

app = App(
    ui=build_app_ui(),
    server=server,
)