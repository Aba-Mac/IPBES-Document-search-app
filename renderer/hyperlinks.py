"""
renderer/hyperlinks.py
======================

Render glossary terms as hyperlinks.

This module converts glossary terms that were identified during the
ingestion pipeline (stored in ``paragraph_terms``) into hyperlinks
within paragraph text.

Unlike the ingestion pipeline, this module NEVER performs glossary
matching itself. It only receives precomputed matches and renders them.

The expected rendering pipeline is::

    raw paragraph
        │
        ▼
    renderer.html.escape_html()
        │
        ▼
    hyperlink_glossary_terms()
        │
        ▼
    highlighting.highlight_search_terms()
        │
        ▼
    final HTML

The module operates only on HTML-escaped text.

No untrusted HTML is ever inserted.

Highlights
----------

* Works on already-escaped text.
* Avoids wrapping text already inside hyperlinks.
* Longest glossary terms are processed first.
* Case-insensitive matching.
* Word-boundary matching.
* Produces stable HTML.
* Independent from Shiny.

"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from typing import Iterable
from urllib.parse import quote

from renderer.html import HTMLToken, TokenType, split_html

__all__ = [
    "GlossaryMatch",
    "hyperlink_glossary_terms",
]


###############################################################################
# Data model
###############################################################################


@dataclass(slots=True, frozen=True)
class GlossaryMatch:
    """
    One glossary occurrence already computed during ingestion.

    Parameters
    ----------
    term:
        Canonical glossary term.

    category:
        Optional glossary category.

    Notes
    -----
    Offsets are intentionally not required.

    Rendering is performed using the glossary term itself against the
    escaped paragraph text.

    Matching has already been determined by the ingestion pipeline.
    """

    term: str
    category: str | None = None


###############################################################################
# Helpers
###############################################################################


def _build_href(term: str) -> str:
    """
    Build hyperlink target.

    Parameters
    ----------
    term
        Glossary term.

    Returns
    -------
    str
    """
    url_encoded = quote(term, safe="")
    return f"?q={html.escape(url_encoded, quote=True)}"


def _compile_pattern(term: str) -> re.Pattern[str]:
    """
    Compile a whole-word case-insensitive regex.

    Parameters
    ----------
    term

    Returns
    -------
    Pattern
    """
    escaped = re.escape(html.escape(term))

    return re.compile(
        rf"(?<!\w)({escaped})(?!\w)",
        flags=re.IGNORECASE,
    )


def _replace_in_text(
    text: str,
    matches: Iterable[GlossaryMatch],
) -> str:
    """
    Replace glossary terms within one HTML text node.

    Parameters
    ----------
    text
        Escaped HTML text.

    matches
        Precomputed glossary matches.

    Returns
    -------
    str
    """
    ordered = sorted(matches, key=lambda m: len(m.term), reverse=True)

    spans: list[tuple[int, int, GlossaryMatch]] = []
    claimed = [False] * len(text)

    for match in ordered:
        pattern = _compile_pattern(match.term)
        for m in pattern.finditer(text):
            start, end = m.start(), m.end()
            if any(claimed[start:end]):
                continue  # overlaps a longer term already placed
            spans.append((start, end, match))
            for i in range(start, end):
                claimed[i] = True

    if not spans:
        return text

    spans.sort(key=lambda s: s[0])

    pieces: list[str] = []
    cursor = 0
    for start, end, match in spans:
        pieces.append(text[cursor:start])
        href = _build_href(match.term)
        pieces.append(
            f'<a class="glossary-link" '
            f'data-term="{html.escape(match.term, quote=True)}" '
            f'href="{href}">'
            f"{text[start:end]}"
            "</a>"
        )
        cursor = end
    pieces.append(text[cursor:])

    return "".join(pieces)


###############################################################################
# Public API
###############################################################################


def hyperlink_glossary_terms(
    escaped_html: str,
    glossary_matches: Iterable[GlossaryMatch],
    exclude_terms: Iterable[str] | None = None,
) -> str:
    """
    Convert glossary terms into hyperlinks.

    Parameters
    ----------
    escaped_html
        HTML-escaped paragraph.

    glossary_matches
        Iterable of glossary matches already computed during ingestion.

    exclude_terms
        Terms that should never be hyperlinked (e.g. the active search
        query), so they remain plain text for the highlighter to wrap.

    Returns
    -------
    str
        HTML fragment.

    Notes
    -----
    Existing hyperlinks are preserved.

    Terms already inside hyperlinks are never wrapped again.
    """
    if not escaped_html:
        return escaped_html

    glossary_matches = list(glossary_matches)

    if exclude_terms:
        excluded = {t.casefold() for t in exclude_terms}
        glossary_matches = [
            m for m in glossary_matches
            if m.term.casefold() not in excluded
        ]

    if not glossary_matches:
        return escaped_html

    tokens = split_html(escaped_html)

    rendered: list[str] = []

    inside_anchor = False

    for token in tokens:

        if token.type is TokenType.TAG:

            tag_lower = token.value.lower()

            if tag_lower.startswith("<a "):
                inside_anchor = True

            elif tag_lower.startswith("</a"):
                inside_anchor = False

            rendered.append(token.value)
            continue

        if inside_anchor:
            rendered.append(token.value)
            continue

        rendered.append(
            _replace_in_text(
                token.value,
                glossary_matches,
            )
        )

    return "".join(rendered)