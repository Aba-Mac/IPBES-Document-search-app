"""
Recompute glossary term matches for all already-ingested documents,
without re-running OCR/extraction/chunking.

Run manually after editing a glossary .txt file:

    python scripts/reindex_glossary.py
"""

import logging

from database import repository
from ingestion.glossary import reindex_all_glossary_matches
from core.paths import GLOSSARY_DIR

logging.basicConfig(level=logging.INFO)
LOGGER = logging.getLogger(__name__)

glossary_sources = {
    "ILK": GLOSSARY_DIR / "ilk.txt",
    "Glossary": GLOSSARY_DIR / "glossary.txt",
}

missing = [name for name, path in glossary_sources.items() if not path.exists()]
if missing:
    raise FileNotFoundError(f"Missing glossary file(s): {', '.join(missing)}")

with repository.transaction() as connection:
    match_count = reindex_all_glossary_matches(connection, glossary_sources)

LOGGER.info("Reindexed glossary matches: %d paragraph-term rows.", match_count)