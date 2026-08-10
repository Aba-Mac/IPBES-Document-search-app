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
        # JavaScript dependencies
        #
        ui.tags.script(
            """
        (function () {
            "use strict";

            let glossaryTerms = [];
            let autocompleteInitialised = false;

            function getInput() {
                return document.getElementById("search_query");
            }

            function getContainer() {
                return document.getElementById("glossary-autocomplete");
            }

            function closeSuggestions() {
                const container = getContainer();
                if (!container) return;
                container.innerHTML = "";
                container.style.display = "none";
            }

            function getCurrentToken(input) {
                const cursor = input.selectionStart;
                const textBeforeCursor = input.value.slice(0, cursor);
                const match = textBeforeCursor.match(/([^\\s()]+)$/);
                if (!match) {
                    return { token: "", start: cursor, end: cursor };
                }
                return {
                    token: match[1],
                    start: cursor - match[1].length,
                    end: cursor
                };
            }

            function showSuggestions(input) {
                const container = getContainer();
                if (!container) return;

                const current = getCurrentToken(input);
                const token = current.token.trim();

                if (!token) {
                    closeSuggestions();
                    return;
                }

                const lowerToken = token.toLowerCase();
                const matches = glossaryTerms
                    .filter(function (term) {
                        return term.toLowerCase().startsWith(lowerToken);
                    })
                    .slice(0, 10);

                if (matches.length === 0) {
                    closeSuggestions();
                    return;
                }

                container.innerHTML = "";

                matches.forEach(function (term) {
                    const item = document.createElement("div");
                    item.className = "glossary-autocomplete-item";
                    item.textContent = term;

                    item.addEventListener("mousedown", function (event) {
                        event.preventDefault();

                        const before = input.value.slice(0, current.start);
                        const after = input.value.slice(current.end);

                        input.value = before + term + after;

                        const newCursor = current.start + term.length;
                        input.setSelectionRange(newCursor, newCursor);

                        input.dispatchEvent(new Event("input", { bubbles: true }));

                        closeSuggestions();
                        input.focus();
                    });

                    container.appendChild(item);
                });

                container.style.display = "block";
            }

            function initialise() {
                if (autocompleteInitialised) return;

                const input = getInput();
                if (!input) return;

                autocompleteInitialised = true;

                input.addEventListener("input", function () {
                    showSuggestions(input);
                });

                input.addEventListener("keydown", function (event) {
                    if (event.key === "Escape") {
                        closeSuggestions();
                    }
                });

                input.addEventListener("blur", function () {
                    setTimeout(closeSuggestions, 150);
                });
            }

            document.addEventListener("DOMContentLoaded", function () {
                initialise();
            });

            if (window.Shiny) {
                Shiny.addCustomMessageHandler("glossary_terms", function (terms) {
                    glossaryTerms = Array.isArray(terms) ? terms : [];
                    console.log("Glossary autocomplete loaded:", glossaryTerms.length, "terms");
                    initialise();
                });
            }
        })();
            """
        ),

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