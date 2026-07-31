"""
Application logging configuration.

Features
--------
- structured logging
- console output
- rotating file logging
- timestamps in UTC
- module-aware formatting
"""

from __future__ import annotations

import logging
import logging.config
import logging.handlers
import time

from .config import settings


class UTCFormatter(logging.Formatter):
    """Logging formatter using UTC timestamps."""

    converter = time.gmtime


def configure_logging() -> None:
    """Configure application logging."""

    formatter = UTCFormatter(
        fmt=(
            "%(asctime)s "
            "%(levelname)s "
            "%(name)s "
            "%(filename)s:%(lineno)d "
            "%(message)s"
        ),
        datefmt="%Y-%m-%dT%H:%M:%SZ",
    )

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    file_handler = logging.handlers.RotatingFileHandler(
        filename=settings.logging.file,
        maxBytes=10 * 1024 * 1024,
        backupCount=10,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    root = logging.getLogger()

    root.handlers.clear()

    root.setLevel(settings.logging.level)

    if settings.logging.console:
        root.addHandler(console_handler)

    root.addHandler(file_handler)

    logging.captureWarnings(True)

    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("sentence_transformers").setLevel(
        logging.WARNING
    )
    logging.getLogger("unstructured").setLevel(logging.INFO)

    logging.getLogger(__name__).info(
        "Logging initialised."
    )