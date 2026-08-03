"""
renderer/html.py
================

Low-level HTML safety utilities used by the rendering pipeline.

This module provides a small set of carefully designed helpers for
building HTML from trusted application-generated markup while ensuring
that document text originating from PDFs is always HTML-escaped before
any rendering tags are injected.

Design goals
------------

The rendering pipeline is:

    raw text
        │
        ▼
    escape_html()
        │
        ▼
    hyperlink renderer
        │
        ▼
    search highlighting
        │
        ▼
    final HTML

The UI never inserts HTML directly from document text.

Only renderer modules generate markup.

Functions in this module intentionally avoid any dependency on Shiny so
they are easy to test independently.

Public API
----------

escape_html()
    Escapes arbitrary document text.

is_html_escaped()
    Best-effort detection used defensively by callers.

safe_inject()
    Safely inserts trusted HTML fragments into already-escaped text.

split_html()
    Splits an HTML fragment into tags and text components while
    preserving ordering.

strip_tags()
    Removes HTML tags from markup.

HTMLToken
    Dataclass representing one parsed token.

"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Iterator, List

__all__ = [
    "HTMLToken",
    "TokenType",
    "escape_html",
    "is_html_escaped",
    "safe_inject",
    "split_html",
    "strip_tags",
]

###############################################################################
# Regular expressions
###############################################################################

_TAG_RE = re.compile(r"(<[^>]+>)")
_ANY_TAG_RE = re.compile(r"<[^>]+>")

###############################################################################
# Token model
###############################################################################


class TokenType(str, Enum):
    """Type of token produced by split_html()."""

    TEXT = "text"
    TAG = "tag"


@dataclass(slots=True, frozen=True)
class HTMLToken:
    """
    Represents one HTML fragment.

    Attributes
    ----------
    type:
        Token type.

    value:
        Original fragment.
    """

    type: TokenType
    value: str


###############################################################################
# Escaping
###############################################################################


def escape_html(text: str | None) -> str:
    """
    Escape arbitrary document text for safe HTML rendering.

    This must be called before any hyperlink or highlighting markup
    is introduced.

    Parameters
    ----------
    text:
        Raw document text.

    Returns
    -------
    str
        HTML-escaped text.

    Examples
    --------
    >>> escape_html("<hello>")
    '&lt;hello&gt;'
    """
    if text is None:
        return ""

    return html.escape(text, quote=True)


def is_html_escaped(text: str) -> bool:
    """
    Best-effort detection whether text already appears escaped.

    This function is intentionally conservative.

    It is used defensively to avoid accidental double escaping.

    Parameters
    ----------
    text:
        Candidate text.

    Returns
    -------
    bool
    """
    if not text:
        return True

    unescaped = html.unescape(text)
    return html.escape(unescaped, quote=True) == text


###############################################################################
# HTML tokenisation
###############################################################################


def split_html(html_fragment: str) -> List[HTMLToken]:
    """
    Split HTML into alternating text/tag tokens.

    Tags are preserved exactly.

    Text nodes remain escaped.

    Parameters
    ----------
    html_fragment:
        HTML fragment.

    Returns
    -------
    list[HTMLToken]
    """
    tokens: List[HTMLToken] = []

    for piece in _TAG_RE.split(html_fragment):
        if not piece:
            continue

        if piece.startswith("<") and piece.endswith(">"):
            tokens.append(
                HTMLToken(
                    TokenType.TAG,
                    piece,
                )
            )
        else:
            tokens.append(
                HTMLToken(
                    TokenType.TEXT,
                    piece,
                )
            )

    return tokens


###############################################################################
# Safe injection
###############################################################################


def safe_inject(
    escaped_text: str,
    replacements: Iterable[tuple[int, int, str]],
) -> str:
    """
    Inject trusted HTML into already-escaped text.

    Parameters
    ----------
    escaped_text:
        HTML-escaped text.

    replacements:
        Iterable of (start, end, replacement_html).

        Indices refer to positions within the escaped string.

        Replacement HTML is assumed to originate solely from trusted
        renderer code.

    Returns
    -------
    str

    Raises
    ------
    ValueError
        If replacement spans overlap or are invalid.
    """
    ordered = sorted(replacements, key=lambda item: item[0])

    if not ordered:
        return escaped_text

    output: list[str] = []
    cursor = 0

    for start, end, replacement in ordered:

        if start < cursor:
            raise ValueError(
                "Replacement spans overlap."
            )

        if start > end:
            raise ValueError(
                "Replacement start exceeds end."
            )

        output.append(escaped_text[cursor:start])
        output.append(replacement)

        cursor = end

    output.append(escaped_text[cursor:])

    return "".join(output)


###############################################################################
# Utilities
###############################################################################


def strip_tags(html_fragment: str) -> str:
    """
    Remove HTML tags.

    Parameters
    ----------
    html_fragment:
        HTML fragment.

    Returns
    -------
    str
    """
    return _ANY_TAG_RE.sub("", html_fragment)