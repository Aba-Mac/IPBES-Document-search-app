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

load_dotenv(PROJECT_ROOT / ".env")

###############################################################################
# Data directories
###############################################################################

DATA_DIR: Final[Path] = PROJECT_ROOT / "data"

DOCX_DIR: Final[Path] = DATA_DIR / "docx"
GLOSSARY_DIR: Final[Path] = DATA_DIR / "glossary"
SECTION_DOI_DIR: Final[Path] = DOCX_DIR / "section_lookup.csv"

###############################################################################
# Application directories
###############################################################################

LOG_DIR: Final[Path] = PROJECT_ROOT / "logs"

###############################################################################
# Create required directories
###############################################################################

for directory in (
    DATA_DIR,
    DOCX_DIR,
    GLOSSARY_DIR,
    LOG_DIR,
):
    directory.mkdir(parents=True, exist_ok=True)