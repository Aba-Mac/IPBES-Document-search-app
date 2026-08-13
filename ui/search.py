"""
ui.search
=========

Search controls for the Shiny application.

Responsibilities
----------------
* Define search input widgets.
* Define Boolean search controls.
* Define document year filter.
* Define pagination controls.
* Expose helper functions for reading reactive input values.

This module intentionally contains no search execution logic.

Actual searching is delegated to:

    search.service.search()

The UI only collects user input and passes it to the service layer.
"""

from __future__ import annotations

from datetime import date
from typing import Iterable

from shiny import ui

###############################################################################
# Input IDs
###############################################################################

SEARCH_QUERY_ID = "search_query"

YEAR_FILTER_ID = "year_filter"

PAGE_SIZE_ID = "page_size"

###############################################################################
# UI construction
###############################################################################


def build_search_controls(
    *,
    years: Iterable[int] = (),
):
    """
    Build the complete search control panel.

    The search field is a normal free-text input.
    Glossary autocomplete is attached separately by JavaScript.
    """

    years = tuple(years) or (2019, date.today().year)

    y_min, y_max = min(years), max(years)

    return ui.div(

        #
        # Main search input
        #
        ui.div(
            ui.input_text(
                id=SEARCH_QUERY_ID,
                label=(
                    "Currently, only terms from the dropdown glossary list are searchable. "
                    "Use AND, OR, NOT, NOR and parentheses."
                ),
                value="",
                placeholder=(
                    "Example: biodiversity AND "
                    "(climate OR environment)"
                ),
                width="100%",
            ),

            # Container populated by the autocomplete JavaScript.
            ui.div(
                id="glossary-autocomplete",
                class_="glossary-autocomplete",
            ),

            class_="search-input-container",

        ),
            
        #
        # Filters
        #
        ui.div(
            ui.input_slider(
                id=YEAR_FILTER_ID,
                label="Year range",
                min=y_min,
                max=y_max,
                value=(y_min, y_max),
                step=1,
                sep="",
            ),
        ),

        #
        # Pagination
        #

        ui.div(
            ui.input_numeric(
                id=PAGE_SIZE_ID,
                label="Results per page",
                value=20,
                min=5,
                max=100,
                step=5,
            ),
            class_="pagination-controls",
        ),

        ui.div(
            ui.input_action_button(
                "prev_page",
                "‹ Previous",
            ),
            ui.span(
                ui.output_text("page_info"),
            ),
            ui.input_action_button(
                "next_page",
                "Next ›",
            ),
            class_="pagination-controls d-flex align-items-center gap-2",
        ),

        #
        # Search button
        #
        ui.div(
            ui.input_action_button(
                id="search_button",
                label="Search",
                class_="search-button",
            ),
        ),

        class_="search-controls",

    )


###############################################################################
# Input accessors
###############################################################################

#
# These helper functions isolate the rest of the application from
# Shiny input IDs.
#


def search_query(input) -> str:
    """
    Return the simple search query.
    """

    value = input[SEARCH_QUERY_ID]()
    return value or ""


def selected_year_range(
    input,
    full_range: tuple[int, int] | None = None,
) -> tuple[int, int] | None:

    value = input[YEAR_FILTER_ID]()

    if not value:
        return None

    value = tuple(value)

    if full_range is not None and value == full_range:
        return None

    return value


def page_size(input) -> int:
    """
    Return requested page size.
    """

    value = input[PAGE_SIZE_ID]()

    if not value:
        return 20

    return int(value)