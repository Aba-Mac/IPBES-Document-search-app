"""
Environment variable validation.

Call validate_environment() once during application startup.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

from .config import ConfigurationError

load_dotenv()


REQUIRED_DIRECTORIES = (
    "data",
    "logs",
)


def validate_environment() -> None:
    """
    Validate runtime configuration.

    Raises
    ------
    ConfigurationError
        If required configuration is invalid.
    """

    database = os.getenv("DATABASE_PATH")

    if database:
        parent = Path(database).expanduser().resolve().parent

        if not parent.exists():
            raise ConfigurationError(
                f"Database directory does not exist: {parent}"
            )

    timeout = os.getenv("OLLAMA_TIMEOUT")

    if timeout is not None:
        try:
            value = int(timeout)
        except ValueError as exc:
            raise ConfigurationError(
                "OLLAMA_TIMEOUT must be an integer."
            ) from exc

        if value <= 0:
            raise ConfigurationError(
                "OLLAMA_TIMEOUT must be positive."
            )

    for directory in REQUIRED_DIRECTORIES:
        Path(directory).mkdir(parents=True, exist_ok=True)