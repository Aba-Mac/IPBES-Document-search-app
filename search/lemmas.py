"""
search.lemmas
=============

Lemma helpers shared by term validation and FTS query compilation.

Both the stored paragraph text (``paragraphs.lemmas``) and the user's
search terms go through the SAME spaCy pipeline
(``ingestion.glossary.lemmatise_many``), so singular/plural and other
inflected forms compare equal:

    "biocultural approaches to conservation"
    "biocultural approach to conservation"
        -> ("biocultural", "approach", "to", "conservation")

Punctuation is dropped by the pipeline, so curly vs straight apostrophes,
en-dashes vs hyphens, non-breaking spaces etc. normalise automatically.
"""

from __future__ import annotations

from functools import lru_cache

from ingestion.glossary import lemmatise_many

__all__ = ["lemma_tokens", "lemma_phrase", "glossary_lemma_keys"]


def lemma_tokens(text: str) -> tuple[str, ...]:
    """Lemmas of ``text`` as a tuple (empty if it has no word tokens)."""
    return tuple(lemmatise_many([text])[0])


def lemma_phrase(text: str) -> str:
    """Lemmas of ``text`` joined by spaces, as stored in paragraphs.lemmas."""
    return " ".join(lemma_tokens(text))


@lru_cache(maxsize=16)
def glossary_lemma_keys(terms: tuple[str, ...]) -> frozenset[tuple[str, ...]]:
    """
    Lemma keys of a set of glossary terms.

    Cached on the tuple of term strings, so the glossary is only
    lemmatised once per distinct glossary and the cache invalidates
    itself automatically when the glossary changes.
    """
    return frozenset(
        tuple(lemmas) for lemmas in lemmatise_many(terms) if lemmas
    )