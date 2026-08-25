"""
DOI lookup.

DOIs cannot be extracted from the source PDFs, so they are supplied
externally via a flat filename -> DOI mapping file (CSV: filename,doi).
"""
from __future__ import annotations

import csv
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def load_doi_map(path: Path) -> dict[str, str]:
    """
    Load a filename -> DOI mapping.

    Missing file is treated as "no DOIs available" rather than an
    error, so ingestion can proceed without DOIs during early testing.
    """
    if not path.exists():
        logger.warning("DOI mapping file not found: %s", path)
        return {}

    mapping: dict[str, str] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            filename = (row.get("filename") or "").strip()
            doi = (row.get("doi") or "").strip()
            if filename and doi:
                mapping[filename] = doi

    logger.info("Loaded %d DOI mappings.", len(mapping))
    return mapping