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
from renderer.hyperlinks import GlossaryMatch

logger = logging.getLogger(__name__)

__all__ = [
    "RESULTS_OUTPUT_ID",
    "register_card_renderer",
]

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
        # No query has been submitted yet (search_results() returns
        # None until the user submits a search). This is the normal
        # initial state, not a failure, so no warning is shown.
        #
        if response is None:
            return ui.div()

        #
        # No results
        #
        if response.total_results == 0:
            return _empty_results()

        return ui.TagList(
            _results_summary(response),
            *[
                _result_card(result, query=response.query)
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


def _result_card(result, *, query: str):
    """
    Build a single result card: paragraph text with a metadata
    footer, no expand/collapse.
    """

    paragraph_html = render_paragraph(
        paragraph=result.text,
        glossary_terms=[
            GlossaryMatch(term=term) for term in result.matched_terms
        ],
        search_query=query,
    )

    body = ui.div(
        ui.HTML(paragraph_html),
        class_="paragraph-body",
    )

    doi = getattr(result, "doi", None)

    title_element = (
        ui.a(
            result.document_title,
            href=f"https://doi.org/{doi}",
            target="_blank",
            rel="noopener noreferrer",
            class_="result-doi-link",
        )
        if doi
        else ui.span(result.document_title, class_="result-doi-link")
    )

    footer = ui.div(
        ui.span("Referenced from:", class_="result-footer-label"),
        title_element,
        ui.span(f" · {result.year}" if result.year else ""),
        ui.span(
            f" · Page {result.page_number} · Paragraph {result.paragraph_number}"
        ),
        class_="result-footer",
    )

    return ui.div(
        body,
        footer,
        class_="result-card",
    )