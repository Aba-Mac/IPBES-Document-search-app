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

from typing import Iterable

from shiny import ui

###############################################################################
# Input IDs
###############################################################################

SEARCH_QUERY_ID = "search_query"

YEAR_FILTER_ID = "year_filter"

PAGE_ID = "result_page"
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

    Parameters
    ----------
    years
        Available document years.

    Returns
    -------
    shiny.ui.Tag
        Search control layout.
    """

    return ui.div(
        #
        # Main search input
        #
        ui.input_selectize(
            id=SEARCH_QUERY_ID,
            label="Search documents. Supports AND, OR, NOT, NOR and parentheses",
            choices=[],
            selected=None,
            multiple=False,
            options={
                "create": True,
                "createOnBlur": False,
                "placeholder": "Example: (data OR information) AND governance",
            },
            width="100%",
        ),

        #
        # Filters
        #
        ui.div(
            ui.div(
                ui.input_select(
                    id=YEAR_FILTER_ID,
                    label="Year",
                    choices=["", *map(str, years)],
                    selected="",
                ),
                class_="search-filters",
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


def selected_year(input) -> int | None:
    """
    Return the selected year filter.
    """

    value = input[YEAR_FILTER_ID]()

    if not value:
        return None

    return int(value)


def page_size(input) -> int:
    """
    Return requested page size.
    """

    value = input[PAGE_SIZE_ID]()

    if not value:
        return 20

    return int(value)


def current_page(input) -> int:
    """
    Return current results page.

    Pagination buttons can update this value later.
    The initial implementation starts on page one.
    """

    value = getattr(input, PAGE_ID)()

    if value is None:
        return 1

    return int(value())