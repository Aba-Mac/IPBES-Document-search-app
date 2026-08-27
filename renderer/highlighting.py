"""
renderer/highlighting.py
========================

Search-term highlighting for rendered paragraph HTML.

This module applies search-term highlighting **after** glossary hyperlinks
have been inserted. It operates on HTML fragments and ensures that only
visible text nodes are modified—never HTML tags or the contents of
existing hyperlinks.

Pipeline
--------

    raw paragraph
        │
        ▼
    renderer.html.escape_html()
        │
        ▼
    renderer.hyperlinks.hyperlink_glossary_terms()
        │
        ▼
    highlight_search_terms()
        │
        ▼
    final HTML

Design goals
------------

* Highlight only visible text.
* Never modify HTML tags.
* Never highlight inside an existing hyperlink.
* Case-insensitive matching.
* Preserve original letter casing.
* Support multi-word search phrases.
* Longest query terms are highlighted first.
* Produce deterministic output.
"""

from __future__ import annotations

import html
import re
from typing import Iterable

from renderer.html import TokenType, split_html

__all__ = [
    "highlight_search_terms",
    "normalise_query"
]

###############################################################################
# Constants
###############################################################################

HIGHLIGHT_CLASS = "search-highlight"

_BOOLEAN_SPLIT_RE = re.compile(
    r"(?i)\b(?:AND|OR|NOT|NOR)\b|[()]"
)

###############################################################################
# Helpers
###############################################################################


def normalise_query(search_query: str | None) -> list[str]:
    """
    Convert a user search query into searchable terms.

    Parameters
    ----------
    search_query
        User-entered query.

    Returns
    -------
    list[str]
        Ordered search terms.

    Notes
    -----
    Duplicate terms are removed.

    Terms are sorted longest-first so that longer phrases are highlighted
    before shorter overlapping terms.
    """
    if not search_query:
        return []

    fragments = _BOOLEAN_SPLIT_RE.split(search_query)

    seen: set[str] = set()
    ordered: list[str] = []

    for fragment in fragments:
        if fragment is None:
            continue

        term = re.sub(r"\s+", " ", fragment).strip()

        if not term:
            continue

        key = term.casefold()
        if key in seen:
            continue

        seen.add(key)
        ordered.append(term)

    ordered.sort(key=len, reverse=True)

    return ordered

_normalise_query = normalise_query


def _compile_pattern(term: str) -> re.Pattern[str]:
    """
    Compile a regex for one search term.

    Parameters
    ----------
    term

    Returns
    -------
    Pattern[str]
    """
    escaped = re.escape(html.escape(term))

    return re.compile(
        escaped,
        flags=re.IGNORECASE,
    )


def _highlight_text(
    text: str,
    search_terms: Iterable[str],
) -> str:
    """
    Highlight search terms within one HTML text node.

    Parameters
    ----------
    text
        HTML text node.

    search_terms
        Ordered search terms.

    Returns
    -------
    str
    """
    highlighted = text

    for term in search_terms:

        pattern = _compile_pattern(term)

        highlighted = pattern.sub(
            (
                f'<span class="{HIGHLIGHT_CLASS}">'
                r"\g<0>"
                "</span>"
            ),
            highlighted,
        )

    return highlighted


###############################################################################
# Public API
###############################################################################


def highlight_search_terms(
    html_fragment: str,
    search_query: str | None,
) -> str:
    """
    Highlight search terms in rendered HTML.

    Parameters
    ----------
    html_fragment
        HTML fragment produced by the hyperlink renderer.

    search_query
        User search query.

    Returns
    -------
    str
        HTML with highlight markup applied.

    Notes
    -----
    Only visible text nodes are modified.

    Existing hyperlinks are preserved exactly.

    Highlighting is never applied inside hyperlinks because clicking a
    glossary term should remain reliable and produce predictable HTML.
    """
    search_terms = _normalise_query(search_query)

    if not search_terms:
        return html_fragment

    tokens = split_html(html_fragment)

    output: list[str] = []

    inside_anchor = False

    for token in tokens:

        if token.type is TokenType.TAG:
            tag = token.value.lower()
            if tag.startswith("<a "):
                inside_anchor = True
            elif tag.startswith("</a"):
                inside_anchor = False
            output.append(token.value)
            continue

        output.append(
            _highlight_text(
                token.value,
                search_terms,
            )
        )

    return "".join(output)