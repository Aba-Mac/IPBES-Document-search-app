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
    return f"?q={html.escape(term, quote=True)}"


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
    result = text

    ordered = sorted(
        matches,
        key=lambda m: len(m.term),
        reverse=True,
    )

    for match in ordered:

        pattern = _compile_pattern(match.term)

        href = _build_href(match.term)

        replacement = (
            f'<a class="glossary-term" '
            f'data-term="{html.escape(match.term, quote=True)}" '
            f'href="{href}">'
            r"\1"
            "</a>"
        )

        result = pattern.sub(replacement, result)

    return result


###############################################################################
# Public API
###############################################################################


def hyperlink_glossary_terms(
    escaped_html: str,
    glossary_matches: Iterable[GlossaryMatch],
) -> str:
    """
    Convert glossary terms into hyperlinks.

    Parameters
    ----------
    escaped_html
        HTML-escaped paragraph.

    glossary_matches
        Iterable of glossary matches already computed during ingestion.

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