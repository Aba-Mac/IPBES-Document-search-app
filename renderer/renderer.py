"""
renderer/renderer.py
====================

Public rendering entry point.

This module is the **only** renderer module that should be imported by the
Shiny UI. It composes the lower-level renderer components into a single,
well-defined rendering pipeline that converts raw paragraph text into safe
HTML suitable for insertion into result cards.

Rendering pipeline
------------------

The pipeline is intentionally fixed:

    raw paragraph text
            │
            ▼
    escape_html()
            │
            ▼
    hyperlink_glossary_terms()
            │
            ▼
    highlight_search_terms()
            │
            ▼
        Safe HTML

This ordering is critical:

1. Escape raw document text before any markup is introduced.
2. Insert glossary hyperlinks into escaped text.
3. Highlight search terms while respecting existing hyperlinks.
4. Return a final HTML fragment that is safe to render in the UI.

The renderer never performs glossary matching. It consumes the glossary
matches that were precomputed during ingestion and retrieved from the
database via ``database.repository``.

The returned HTML is intended for trusted insertion into the Shiny UI
(e.g. ``ui.HTML(...)``).
"""

from __future__ import annotations

from collections.abc import Iterable

from renderer.highlighting import highlight_search_terms
from renderer.html import escape_html
from renderer.hyperlinks import GlossaryMatch, hyperlink_glossary_terms

__all__ = [
    "render_paragraph",
]


def render_paragraph(
    paragraph: str | None,
    glossary_terms: Iterable[GlossaryMatch] | None = None,
    search_query: str | None = None,
) -> str:
    """
    Render a paragraph as safe HTML.

    Parameters
    ----------
    paragraph
        Raw paragraph text extracted from the document.

    glossary_terms
        Iterable of glossary matches that were precomputed during
        ingestion and retrieved from the database.

    search_query
        The active search query entered by the user.

    Returns
    -------
    str
        Fully rendered HTML fragment suitable for insertion into the
        Shiny UI.

    Notes
    -----
    This function intentionally performs no database access and no
    glossary matching. It is a pure rendering function.

    The returned HTML contains only application-generated markup:

    * ``<a>`` elements for glossary hyperlinks
    * ``<span>`` elements for highlighted search terms

    All document text has already been HTML-escaped before either of
    these tags are inserted.
    """
    if not paragraph:
        return ""

    matches = list(glossary_terms or ())

    # Step 1: Escape all document text.
    rendered = escape_html(paragraph)

    # Step 2: Convert glossary terms into hyperlinks.
    if matches:
        rendered = hyperlink_glossary_terms(
            escaped_html=rendered,
            glossary_matches=matches,
        )

    # Step 3: Highlight active search terms without disturbing existing
    # hyperlinks.
    if search_query:
        rendered = highlight_search_terms(
            html_fragment=rendered,
            search_query=search_query,
        )

    return rendered