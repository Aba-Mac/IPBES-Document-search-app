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

APP_VERSION = "1.0.0 (21 August 2026)"

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
                Shiny.addCustomMessageHandler("glossary_terms", function (message) {
                    glossaryTerms = Array.isArray(message.terms) ? message.terms : [];
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

            #
            # Footer
            #
            build_footer(),

            class_="app-container",
        ),
    )


###############################################################################
# Header and Footer
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
            "IPBES Document Search",
            class_="app-title",
        ),

        ui.div(
            ui.span(
                f"Version {APP_VERSION}",
                class_="app-version",
            ),

            ui.input_action_link(
                    "about_button",
                    "About",
                    class_="about-link",
                ),

            class_="app-meta",
        ),

        ui.p(
            (
                "Search workshop documents using Boolean "
                "queries. Results are returned at paragraph level with "
                "highlighted search terms and linked glossary entries."
            ),
            class_="app-subtitle",
        ),

        class_="app-header",
    )

def build_about_modal():
    """
    Build the About dialog shown when the user clicks the About link.
    """
    return ui.modal(
        ui.p(
            "IPBES Document Search provides a search platform to find "
            "IPBES glossary and ILK terms in workshop documents using Boolean queries, with results returned at the "
            "paragraph level and linked IPBES glossary entries. This tool is supposed "
            "to simplify and speed up the process of finding information " 
            "and increase accessibility to IPBES knowledge resources."
        ),
        ui.p(
            "The idea for the search platform was conceptualised "
            "by Aidin Niamir, Head of the IPBES Technical Support Unit " \
            "on Data and Knowledge Management, and implemented and maintained " \
            "by Annabell Macphee at the Senckenberg Biodiversity and Climate Research Centre."
        ),
        ui.p(
            "The IPBES glossary (and ILK terms) are derived from the respective location on" \
            "the IPBES website while IPBES workshop documents were retrieved " \
            "from the IPBES Intergovernmental Science-Policy Platform on Biodiversity and Ecosystem Services (IPBES) " \
            "Zenodo community."
        ),
        ui.p(
            "While this tool may be helpful for exploratory searches and utmost " \
            "care was invested to ensure accuracy, returned results may be incomplete or " \
            "otherwise faulty. For formal use, users should always refer to relevant IPBES workshop documents directly." \
        ),
        title="About: IPBES Document Search",
        easy_close=True,
        footer=ui.modal_button("Close"),
    )


def build_footer():
    """
    Build the application footer.
    """

    return ui.tags.footer(
        ui.div(
            ui.div(
                ui.span("Data: ", class_="footer-label"),
                ui.a(
                    "IPBES ILK Reports",
                    href="https://www.ipbes.net/ilk-dialogue-reports",
                    class_="footer-link",
                ),
                ui.span(" | ", class_="footer-separator"),
                ui.a(
                    "IPBES Glossary",
                    href="https://www.ipbes.net/glossary",
                    class_="footer-link",
                ),
                ui.span(" | ", class_="footer-separator"),
                ui.a(
                    "IPBES ILK terms",
                    href="#",
                    class_="footer-link",
                ),
            ),
            ui.div(
                ui.span("Issues: ", class_="footer-label"),
                ui.a(
                    "Github issues",
                    href="https://github.com/Aba-Mac/IPBES-Document-search-app/issues",
                    class_="footer-link",
                ),
            ),
            ui.div(
                ui.span("Developed by ", class_="footer-label"),
                ui.a(
                    "Annabell Macphee",
                    href="mailto:annabell.macphee@senckenberg.de?subject=IPBES%20document%20search%20app",
                    class_="footer-link",
                ),
                ui.span(" | ", class_="footer-separator"),
                ui.a(
                    "Senckenberg Biodiversity and Climate Research Institute",
                    href="https://www.senckenberg.de/en/research/institutes-overview/sbikf-institut/",
                    class_="footer-link",
                    ),
                class_="footer-inner",
            ),

            class_="app-footer",
        )
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