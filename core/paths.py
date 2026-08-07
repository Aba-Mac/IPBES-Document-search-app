"""
Application filesystem paths.

Defines project directories used throughout the application and ensures
required directories exist at startup.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

from dotenv import load_dotenv

###############################################################################
# Project root
###############################################################################

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parent.parent

# Load environment variables from the project root.
load_dotenv(PROJECT_ROOT / ".env")

###############################################################################
# Data directories
###############################################################################

DATA_DIR: Final[Path] = PROJECT_ROOT / "data"

PDF_DIR: Final[Path] = DATA_DIR / "pdfs"
GLOSSARY_DIR: Final[Path] = DATA_DIR / "glossary"
PROCESSED_DIR: Final[Path] = DATA_DIR / "processed"
CACHE_DIR: Final[Path] = DATA_DIR / "cache"
EXPORT_DIR: Final[Path] = DATA_DIR / "exports"

###############################################################################
# Application directories
###############################################################################

LOG_DIR: Final[Path] = PROJECT_ROOT / "logs"

TEST_DATA_DIR: Final[Path] = PROJECT_ROOT / "tests" / "data"

###############################################################################
# Create required directories
###############################################################################

for directory in (
    DATA_DIR,
    PDF_DIR,
    GLOSSARY_DIR,
    PROCESSED_DIR,
    CACHE_DIR,
    EXPORT_DIR,
    LOG_DIR,
):
    directory.mkdir(parents=True, exist_ok=True)