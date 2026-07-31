"""
Chunking module.

Primary strategy:
    Unstructured chunk_by_title

Fallback strategy:
    LangChain RecursiveCharacterTextSplitter

The module operates on cleaned, structure-aware extraction output.

The output objects are compatible with the paragraphs database table:

    paragraphs
    ----------
    document_id
    page_number
    paragraph_number
    text
    chunk_method

Section titles are preserved internally but are not persisted because the
current database schema does not include a section_title column.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

from langchain_text_splitters import RecursiveCharacterTextSplitter
from unstructured.chunking.title import chunk_by_title
from unstructured.documents.elements import Element


DEFAULT_MAX_CHUNK_CHARACTERS = 4000
DEFAULT_MAX_PAGES_PER_CHUNK = 5


@dataclass(frozen=True)
class ParagraphChunk:
    """
    Database-compatible chunk representation.

    Attributes
    ----------
    document_id:
        Parent document identifier.

    page_number:
        First page number covered by this chunk.

    paragraph_number:
        Sequential chunk number within the document.

    text:
        Chunk text content.

    chunk_method:
        Chunking strategy used.
    """

    document_id: int
    page_number: int
    paragraph_number: int
    text: str
    chunk_method: str


@dataclass(frozen=True)
class ChunkCandidate:
    """
    Internal representation before database mapping.

    Keeps section metadata available during processing.
    """

    text: str
    page_numbers: tuple[int, ...]
    section_title: str | None


def chunk_document(
    *,
    document_id: int,
    elements: Sequence[Element],
    max_chunk_characters: int = DEFAULT_MAX_CHUNK_CHARACTERS,
    max_pages_per_chunk: int = DEFAULT_MAX_PAGES_PER_CHUNK,
) -> list[ParagraphChunk]:
    """
    Chunk extracted document elements.

    Parameters
    ----------
    document_id:
        Database id of source document.

    elements:
        Cleaned Unstructured elements.

    max_chunk_characters:
        Maximum acceptable chunk size before fallback.

    max_pages_per_chunk:
        Maximum acceptable page span before fallback.

    Returns
    -------
    list[ParagraphChunk]
        Database-compatible chunks.
    """

    title_chunks = _chunk_by_title(elements)

    final_candidates: list[tuple[ChunkCandidate, str]] = []

    for candidate in title_chunks:
        if _requires_fallback(
            candidate,
            max_chunk_characters=max_chunk_characters,
            max_pages_per_chunk=max_pages_per_chunk,
        ):
            fallback_chunks = _langchain_fallback(candidate)

            for fallback in fallback_chunks:
                final_candidates.append(
                    (
                        fallback,
                        "langchain_fallback",
                    )
                )

        else:
            final_candidates.append(
                (
                    candidate,
                    "chunk_by_title",
                )
            )

    return _to_paragraph_chunks(
        document_id=document_id,
        chunks=final_candidates,
    )


def _chunk_by_title(
    elements: Sequence[Element],
) -> list[ChunkCandidate]:
    """
    Apply Unstructured chunk_by_title.

    Returns internal candidates preserving page metadata.
    """

    chunks = chunk_by_title(
        elements,
        max_characters=DEFAULT_MAX_CHUNK_CHARACTERS,
        combine_text_under_n_chars=500,
    )

    candidates: list[ChunkCandidate] = []

    for chunk in chunks:
        text = chunk.text.strip()

        if not text:
            continue

        pages = _extract_pages(chunk)

        candidates.append(
            ChunkCandidate(
                text=text,
                page_numbers=pages,
                section_title=_extract_section_title(chunk),
            )
        )

    return candidates


def _requires_fallback(
    candidate: ChunkCandidate,
    *,
    max_chunk_characters: int,
    max_pages_per_chunk: int,
) -> bool:
    """
    Determine whether chunk_by_title produced a poor result.
    """

    if len(candidate.text) > max_chunk_characters:
        return True

    if len(candidate.page_numbers) > max_pages_per_chunk:
        return True

    return False


def _langchain_fallback(
    candidate: ChunkCandidate,
) -> list[ChunkCandidate]:
    """
    Split oversized sections using LangChain.

    Recursive splitting preserves paragraph boundaries where possible.
    """

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=DEFAULT_MAX_CHUNK_CHARACTERS,
        chunk_overlap=200,
        separators=[
            "\n\n",
            "\n",
            ". ",
            " ",
        ],
    )

    pieces = splitter.split_text(candidate.text)

    return [
        ChunkCandidate(
            text=piece.strip(),
            page_numbers=candidate.page_numbers,
            section_title=candidate.section_title,
        )
        for piece in pieces
        if piece.strip()
    ]


def _to_paragraph_chunks(
    *,
    document_id: int,
    chunks: Iterable[tuple[ChunkCandidate, str]],
) -> list[ParagraphChunk]:
    """
    Convert internal candidates into database-compatible records.
    """

    output: list[ParagraphChunk] = []

    for number, (candidate, method) in enumerate(chunks, start=1):

        output.append(
            ParagraphChunk(
                document_id=document_id,
                page_number=min(candidate.page_numbers)
                if candidate.page_numbers
                else 1,
                paragraph_number=number,
                text=candidate.text,
                chunk_method=method,
            )
        )

    return output


def _extract_pages(element: Element) -> tuple[int, ...]:
    """
    Extract page numbers from Unstructured metadata.
    """

    page_number = getattr(
        element.metadata,
        "page_number",
        None,
    )

    if page_number is None:
        return ()

    return (page_number,)


def _extract_section_title(
    element: Element,
) -> str | None:
    """
    Extract section title metadata when available.
    """

    return getattr(
        element.metadata,
        "section_title",
        None,
    )