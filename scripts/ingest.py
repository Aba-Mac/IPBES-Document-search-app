"""
Populate the document database.

Run manually:

    python scripts/ingest.py
"""

from pathlib import Path
import logging

from database import repository
from database.migrations import migrate
from ingestion.pipeline import ingest_directory

logging.basicConfig(level=logging.INFO)

LOGGER = logging.getLogger(__name__)

LOGGER.info("Running migrations...")
migrate()

pdf_dir = Path("data/pdfs")

LOGGER.info("PDF directory: %s", pdf_dir.resolve())

if not pdf_dir.exists():
    raise FileNotFoundError(pdf_dir)

LOGGER.info(
    "Found %d PDFs",
    len(list(pdf_dir.glob("*.pdf")))
)

ingest_directory(
    directory=pdf_dir,
    terms_csv="data/glossary/terms.txt",
)

LOGGER.info(
    "Documents: %d",
    repository.table_row_count("documents"),
)

LOGGER.info("Finished.")