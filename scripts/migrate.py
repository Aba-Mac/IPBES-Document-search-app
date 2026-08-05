"""
Run database migrations.

Usage

    python scripts/migrate.py
"""

import logging

from database.migrations import migrate

logging.basicConfig(level=logging.INFO)

LOGGER = logging.getLogger(__name__)

LOGGER.info("Running migrations...")

migrate()

LOGGER.info("Finished.")