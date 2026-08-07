"""
ui.layouts
==========

Overall page layout for the Shiny application.

This module defines the high-level page structure only. It intentionally
contains no search logic, rendering logic or business rules.

Responsibilities
----------------
* Build the overall page layout.
* Arrange the search controls and results area.
* Provide a typography-first single-column layout.
* Remain responsive.
* Keep presentation separate from application logic.

The actual result cards are rendered by ``ui.cards``.

The search controls are provided by ``ui.search``.
"""

from __future__ import annotations

from typing import Any

from shiny import ui

###############################################################################
# IDs
###############################################################################

RESULTS_CONTAINER_ID = "results_container"

###############################################################################
# Layout builders
###############################################################################


def build_page(
    *,
    search_controls: Any,
    css: Any,
):
    """
    Construct the complete application UI.

    Parameters
    ----------
    search_controls
        UI component returned by ``ui.search``.

    css
        CSS dependency returned by ``ui.styles``.

    Returns
    -------
    shiny.ui.Tag
        Complete page UI.
    """

    return ui.page_fluid(
        css,

        #
        # Main application container
        #
        ui.div(
            #
            # Header
            #
            build_header(),

            #
            # Search controls
            #
            ui.div(
                search_controls,
                class_="search-section",
            ),

            #
            # Results
            #
            ui.div(
                build_results_container(),
                class_="results-section",
            ),

            class_="app-container",
        ),
    )


###############################################################################
# Header
###############################################################################


def build_header():
    """
    Build the page header.

    Returns
    -------
    shiny.ui.Tag
    """

    return ui.div(
        ui.h1(
            "Document Search",
            class_="app-title",
        ),
        ui.p(
            (
                "Search plenary documents using full-text and Boolean "
                "queries. Results are returned at paragraph level with "
                "highlighted search terms and linked glossary entries."
            ),
            class_="app-subtitle",
        ),
        class_="header-section",
    )


###############################################################################
# Results container
###############################################################################


def build_results_container():
    """
    Placeholder container for search results.

    ui.cards populates this output.

    Returns
    -------
    shiny.ui.Tag
    """

    return ui.output_ui(
        RESULTS_CONTAINER_ID,
    )