"""
ui.cards
========

Render paragraph search results as expandable cards.

Responsibilities
----------------
* Render one card per returned paragraph.
* Delegate paragraph HTML generation to ``renderer.renderer``.
* Display document metadata.
* Display search metadata.
* Register the Shiny output used by the results container.

This module intentionally contains no search logic and no hyperlinking
or highlighting logic.

The rendered paragraph HTML is produced entirely by
``renderer.renderer``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from shiny import render, ui

from renderer.renderer import render_paragraph

logger = logging.getLogger(__name__)

__all__ = [
    "RESULTS_OUTPUT_ID",
    "register_card_renderer",
]

###############################################################################
# Constants
###############################################################################

RESULTS_OUTPUT_ID = "results_container"

###############################################################################
# Public API
###############################################################################


def register_card_renderer(
    *,
    output,
    results: Callable[[], Any],
) -> None:
    """
    Register the Shiny renderer responsible for displaying search
    results.

    Parameters
    ----------
    output
        Shiny output object.

    results
        Reactive expression returning a SearchResponse.
    """

    @output
    @render.ui
    def results_container():
        response = results()

        #
        # No results
        #
        if response.total_results == 0:
            return _empty_results()

        return ui.TagList(
            _results_summary(response),
            *[
                _result_card(result)
                for result in response.results
            ],
        )


###############################################################################
# Internal helpers
###############################################################################


def _results_summary(response):
    """
    Render the search summary shown above the cards.
    """

    first = ((response.page - 1) * response.page_size) + 1
    last = min(
        response.page * response.page_size,
        response.total_results,
    )

    return ui.div(
        ui.p(
            (
                f"Showing {first:,}–{last:,} "
                f"of {response.total_results:,} "
                "matching paragraphs."
            ),
            class_="results-summary",
        )
    )


def _empty_results():
    """
    Display an empty-state message.
    """

    return ui.div(
        ui.h4("No matching paragraphs found."),
        ui.p(
            "Try broadening your search or adjusting the filters."
        ),
        class_="empty-results",
    )


def _result_card(result):
    """
    Build a single expandable result card.

    Parameters
    ----------
    result
        Ranked search result object.

    Returns
    -------
    shiny.ui.Tag
    """

    #
    # renderer.renderer owns all HTML generation including:
    #
    # * highlighting
    # * glossary hyperlinks
    # * paragraph markup
    #

    paragraph_html = render_paragraph(
                        paragraph=result.text,
                        glossary_terms=result.matched_terms,
                        #search_query=result.query,
                    )

    metadata = ui.div(
        ui.span(
            result.document_title,
            class_="metadata-title",
        ),
        ui.span(
            result.plenary_session,
            class_="metadata-item",
        ),
        ui.span(
            str(result.year),
            class_="metadata-item",
        ),
        ui.span(
            result.location,
            class_="metadata-item",
        ),
        ui.span(
            (
                f"Page {result.page_number} · "
                f"Paragraph {result.paragraph_number}"
            ),
            class_="metadata-item",
        ),
        class_="result-metadata",
    )

    body = ui.div(
        ui.HTML(paragraph_html),
        class_="paragraph-body",
    )

    #
    # Use an HTML <details> element for accessibility and
    # progressive enhancement.
    #

    return ui.tags.details(
        ui.tags.summary(
            metadata,
            class_="result-summary",
        ),
        body,
        class_="result-card",
    )