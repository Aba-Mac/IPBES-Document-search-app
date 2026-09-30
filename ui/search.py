"""
ui.search
=========

Search controls for the Shiny application.

Responsibilities
----------------
* Define search input widgets.
* Define Boolean search controls.
* Define pagination controls.
* Expose helper functions for reading reactive input values.

This module intentionally contains no search execution logic.

Actual searching is delegated to:

    search.service.search()

The UI only collects user input and passes it to the service layer.
"""

from __future__ import annotations

from shiny import ui

###############################################################################
# Input IDs
###############################################################################

SEARCH_QUERY_ID = "search_query"

###############################################################################
# UI construction
###############################################################################


def build_search_controls():
    """
    Build the complete search control panel.
    """

    return ui.div(

        #
        # Disclaimer
        #
        ui.div(
            ui.tags.label("Disclaimer: for official use, always consult original documents. This explorer does not return report figures.", class_="control-title"),
        ),

        #
        # Main search input
        #
        ui.div(
            ui.tags.label("Search:", class_="control-title"),

            ui.p(
                (
                    "Use AND, OR, NOT and square brackets, for example:\n"
                    "Biodiversity AND [Climate OR Environment] -> returns all sections containing "
                    "either Biodiversity and Climate or Biodiversity and Environment\n"
                    "Biodiversity NOT [Conceptual Framework OR Frameworks] -> "
                    "returns all sections including Biodiversity but excluding Conceptual Framework or Frameworks\n" 
                    "Climate NOT [Climate Change] -> returns all sections containing Climate but excluding Climate Change"
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


def search_query(input) -> str:
    """
    Return the simple search query.
    """

    value = input[SEARCH_QUERY_ID]()
    return value or ""