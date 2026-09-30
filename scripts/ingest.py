"""
Populate the document database.

Run manually:

    python scripts/ingest.py
"""

import logging

from database import repository
from database.migrations import migrate
from ingestion.pipeline import ingest_directory
from core.paths import DOCX_DIR, GLOSSARY_PATH, SECTION_DOI_DIR

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

if not GLOSSARY_PATH.exists():
    raise FileNotFoundError(
        f"Missing glossary file: {GLOSSARY_PATH.name} "
        f"(looked in {GLOSSARY_PATH.resolve()})"
    )

ingest_directory(
    directory=DOCX_DIR,
    glossary_path=GLOSSARY_PATH,
    lookup_path=SECTION_DOI_DIR,
    metadata_path=SECTION_DOI_DIR.with_name("document_metadata.csv"),
)

LOGGER.info(
    "Documents: %d",
    repository.table_row_count("documents"),
)

LOGGER.info("Finished.")