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
from typing import List

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