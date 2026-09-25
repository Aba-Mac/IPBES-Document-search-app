"""
metadata.py.

DOIs cannot be extracted from the source PDFs, so they are supplied
externally via a flat filename -> DOI mapping file (CSV: filename,doi).
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path
import logging
from typing import Any

logger = logging.getLogger(__name__)


_TRAILING_FOOTNOTE = re.compile(r"(?<=\D)\s*\d{1,3}\s*$")
_META_FIELDS = ("title", "year", "date", "location")


def load_document_metadata(path: str | Path) -> dict[str, dict[str, Any]]:
    documents: dict[str, dict[str, Any]] = {}
    with Path(path).open(newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file, delimiter=";")
        missing = {"filename", *_META_FIELDS} - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"{path} is missing columns: {sorted(missing)}")
        for row in reader:
            filename = (row["filename"] or "").strip()
            if not filename:
                continue
            record = {f: (row[f] or "").strip() or None for f in _META_FIELDS}
            if record["year"] is not None:
                record["year"] = int(record["year"])
            documents[filename] = record
    return documents


def heading_key(value: str) -> str:
    """Normalise headings only for lookup matching."""
    value = " ".join(value.split())
    value = _TRAILING_FOOTNOTE.sub("", value)
    return value.casefold().strip()


def as_bool(value: str | None) -> bool:
    return (value or "").strip().casefold() in {"1", "true", "yes"}


@dataclass(frozen=True)
class SectionLookup:
    dois: dict[str, str]
    headings: dict[str, frozenset[str]]
    include_all: frozenset[str]
    documents: dict[str, dict[str,Any]]

    def metadata_for(self, filename: str) -> dict[str, Any] | None:
        return self.documents.get(filename)

    def doi_for(self, filename: str) -> str | None:
        return self.dois.get(filename)

    def includes_all(self, filename: str) -> bool:
        return filename in self.include_all

    def matches_heading(self, filename: str, heading: str) -> bool:
        return heading_key(heading) in self.headings.get(filename, frozenset())


def load_section_lookup(path: str | Path, metadata_path: str | Path) -> SectionLookup:
    path = Path(path)

    dois: dict[str, str] = {}
    headings: dict[str, set[str]] = {}
    include_all: set[str] = set()

    with path.open(newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file, delimiter=";")

        required = {"filename", "doi", "section_heading"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"{path} is missing required columns: {sorted(missing)}")

        for row in reader:
            status = (row.get("status") or "confirmed").strip().casefold()
            if status not in {"", "confirmed"}:
                continue

            filename = (row["filename"] or "").strip()
            doi = (row["doi"] or "").strip()
            section_heading = (row["section_heading"] or "").strip()

            if not filename:
                continue

            if doi:
                existing_doi = dois.get(filename)
                if existing_doi and existing_doi != doi:
                    raise ValueError(f"Conflicting DOI values for {filename}")
                dois[filename] = doi

            if as_bool(row.get("include_all")):
                include_all.add(filename)
                continue

            if section_heading:
                headings.setdefault(filename, set()).add(heading_key(section_heading))

    logger.info("Loaded %d DOI mappings.", len(dois))

    return SectionLookup(
        dois=dois,
        headings={f: frozenset(v) for f, v in headings.items()},
        include_all=frozenset(include_all),
        documents=load_document_metadata(metadata_path),
    )