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

GLOSSARY_LIST_ID = "glossary_list_selection"

###############################################################################
# UI construction
###############################################################################


def build_search_controls(
    *,
    years: Iterable[int] = (),
):
    """
    Build the complete search control panel.
    """

    years = tuple(years) or (2019, date.today().year)
    y_min, y_max = min(years), max(years)

    return ui.div(

        #
        # Main search input
        #
        ui.div(
            ui.tags.label("Search:", class_="control-title"),

            ui.p(
                (
                    "Currently, only terms from the glossary list below are searchable. "
                    "Use AND, OR, NOT, NOR and parentheses, for example:\n"
                    "Biodiversity AND (Climate OR Environment)\n"
                    "Biodiversity AND (Conceptual Framework NOR Frameworks)\n" 
                    "Climate NOT Climate Change"
                ),
                class_="search-hint",
            ),

            ui.div(
                ui.input_text(
                    id=SEARCH_QUERY_ID,
                    label=None,
                    value="",
                    placeholder="Type to search terms...",
                    width="100%",
                ),

                ui.div(
                    id="glossary-autocomplete",
                    class_="glossary-autocomplete",
                ),

                class_="search-input-wrapper",
            ),

            class_="search-input-container",
        ),
        #
        # Glossary check box 
        #
        ui.div(
            ui.tags.label("Search term sources:", class_="control-title"),

            ui.input_checkbox_group(
                GLOSSARY_LIST_ID,
                label=None,
                choices={"ILK": "ILK terms", "Glossary": "IPBES Glossary"},
                selected=["ILK", "Glossary"],
                inline=True,
            ),

            class_="glossary-selector",
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


def selected_glossary_lists(input) -> tuple[str, ...]:
    value = input[GLOSSARY_LIST_ID]()
    return tuple(value) if value else ()


def search_query(input) -> str:
    """
    Return the simple search query.
    """

    value = input[SEARCH_QUERY_ID]()
    return value or ""