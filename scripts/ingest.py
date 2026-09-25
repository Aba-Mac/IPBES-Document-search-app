"""
Populate the document database.

Run manually:

    python scripts/ingest.py
"""

import logging

from database import repository
from database.migrations import migrate
from ingestion.pipeline import ingest_directory
from core.paths import DOCX_DIR, GLOSSARY_DIR, SECTION_DOI_DIR

logging.basicConfig(level=logging.INFO)

LOGGER = logging.getLogger(__name__)

LOGGER.info("Running migrations...")
migrate()

LOGGER.info("DOCX directory: %s", DOCX_DIR.resolve())

if not DOCX_DIR.exists():
    raise FileNotFoundError(DOCX_DIR)

LOGGER.info(
    "Found %d DOCX files",
    len(list(DOCX_DIR.glob("*.docx")))
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
    directory=DOCX_DIR,
    glossary_sources=glossary_sources,
    lookup_path=SECTION_DOI_DIR,
    metadata_path=SECTION_DOI_DIR.with_name("document_metadata.csv"),
)

LOGGER.info(
    "Documents: %d",
    repository.table_row_count("documents"),
)

LOGGER.info("Finished.")