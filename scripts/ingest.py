"""
Populate the document database.

Run manually:

    python scripts/ingest.py
"""

import logging

from database import repository
from database.migrations import migrate
from ingestion.pipeline import ingest_directory
from core.paths import PDF_DIR, GLOSSARY_DIR, DOI_DIR

logging.basicConfig(level=logging.INFO)

LOGGER = logging.getLogger(__name__)

LOGGER.info("Running migrations...")
migrate()

LOGGER.info("PDF directory: %s", PDF_DIR.resolve())

if not PDF_DIR.exists():
    raise FileNotFoundError(PDF_DIR)

LOGGER.info(
    "Found %d PDFs",
    len(list(PDF_DIR.glob("*.pdf")))
)

glossary_sources = {
    "ILK": GLOSSARY_DIR / "ilk.txt",
    "Glossary": GLOSSARY_DIR / "glossary.txt",
}

missing = [name for name, path in glossary_sources.items() if not path.exists()]
if missing:
    raise FileNotFoundError(
        f"Missing glossary file(s) for: {', '.join(missing)} "
        f"(looked in {GLOSSARY_DIR.resolve()})"
    )

ingest_directory(
    directory=PDF_DIR,
    glossary_sources=glossary_sources,
    doi_map=DOI_DIR,
)

LOGGER.info(
    "Documents: %d",
    repository.table_row_count("documents"),
)

LOGGER.info("Finished.")