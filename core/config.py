"""
Application configuration.

Loads environment variables, validates configuration values, and exposes
strongly typed settings used throughout the application.

Configuration includes:

- SQLite database settings
- SQLite FTS5 search settings
- OCR settings
- Embedding model configuration
- Ollama LLM configuration
- Topic-tagging thresholds
- Search and pagination defaults

Filesystem paths are defined separately in ``core.paths``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

###############################################################################
# Project paths
###############################################################################

from .paths import (
    DATA_DIR,
    LOG_DIR,
)

###############################################################################
# Environment helpers
###############################################################################


class ConfigurationError(RuntimeError):
    """Raised when application configuration is invalid."""


def _get_env(
    name: str,
    default: str | None = None,
    *,
    required: bool = False,
) -> str:
    value = os.getenv(name, default)

    if required and (value is None or value.strip() == ""):
        raise ConfigurationError(
            f"Required environment variable '{name}' is missing."
        )

    return value


def _get_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)

    if value is None:
        return default

    value = value.lower()

    if value in {"1", "true", "yes", "y", "on"}:
        return True

    if value in {"0", "false", "no", "off"}:
        return False

    raise ConfigurationError(
        f"Environment variable '{name}' must be a boolean."
    )


def _get_int(
    name: str,
    default: int,
    *,
    minimum: int | None = None,
) -> int:
    try:
        value = int(os.getenv(name, default))
    except ValueError as exc:
        raise ConfigurationError(
            f"Environment variable '{name}' must be an integer."
        ) from exc

    if minimum is not None and value < minimum:
        raise ConfigurationError(
            f"{name} must be >= {minimum}."
        )

    return value


def _get_float(
    name: str,
    default: float,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    try:
        value = float(os.getenv(name, default))
    except ValueError as exc:
        raise ConfigurationError(
            f"Environment variable '{name}' must be numeric."
        ) from exc

    if minimum is not None and value < minimum:
        raise ConfigurationError(f"{name} must be >= {minimum}")

    if maximum is not None and value > maximum:
        raise ConfigurationError(f"{name} must be <= {maximum}")

    return value


###############################################################################
# Configuration objects
###############################################################################


@dataclass(frozen=True)
class DatabaseConfig:
    path: Path
    enable_foreign_keys: bool
    enable_wal: bool
    busy_timeout_ms: int
    fts_table: str
    tokenizer: str


@dataclass(frozen=True)
class EmbeddingConfig:
    model: str
    dimensions: int
    batch_size: int


@dataclass(frozen=True)
class OllamaConfig:
    host: str
    verification_model: str
    timeout_seconds: int


@dataclass(frozen=True)
class TaggingConfig:
    fuzzy_threshold: float
    embedding_threshold: float
    llm_threshold: float
    max_candidate_topics: int


@dataclass(frozen=True)
class SearchConfig:
    default_page_size: int
    maximum_page_size: int
    snippet_length: int
    enable_bm25: bool


@dataclass(frozen=True)
class OCRConfig:
    language: str
    deskew: bool
    optimize: int


@dataclass(frozen=True)
class LoggingConfig:
    level: str
    console: bool
    file: Path


@dataclass(frozen=True)
class AppConfig:
    database: DatabaseConfig
    embeddings: EmbeddingConfig
    ollama: OllamaConfig
    tagging: TaggingConfig
    search: SearchConfig
    ocr: OCRConfig
    logging: LoggingConfig


###############################################################################
# Configuration instance
###############################################################################

settings = AppConfig(
    database=DatabaseConfig(
        path=Path(
            _get_env(
                "DATABASE_PATH",
                str(DATA_DIR / "documents.sqlite"),
            )
        ),
        enable_foreign_keys=True,
        enable_wal=True,
        busy_timeout_ms=5000,
        fts_table="paragraphs_fts",
        tokenizer="unicode61 remove_diacritics 2",
    ),
    embeddings=EmbeddingConfig(
        model=_get_env(
            "EMBEDDING_MODEL",
            "BAAI/bge-base-en-v1.5",
        ),
        dimensions=_get_int(
            "EMBEDDING_DIMENSIONS",
            384,
            minimum=64,
        ),
        batch_size=_get_int(
            "EMBEDDING_BATCH_SIZE",
            64,
            minimum=1,
        ),
    ),
    ollama=OllamaConfig(
        host=_get_env(
            "OLLAMA_HOST",
            "http://localhost:11434",
        ),
        verification_model=_get_env(
            "OLLAMA_MODEL",
            "qwen2.5:7B-instruct",
        ),
        timeout_seconds=_get_int(
            "OLLAMA_TIMEOUT",
            120,
            minimum=10,
        ),
    ),
    tagging=TaggingConfig(
        fuzzy_threshold=_get_float(
            "TAG_FUZZY_THRESHOLD",
            0.82,
            minimum=0,
            maximum=1,
        ),
        embedding_threshold=_get_float(
            "TAG_EMBEDDING_THRESHOLD",
            0.76,
            minimum=0,
            maximum=1,
        ),
        llm_threshold=_get_float(
            "TAG_LLM_THRESHOLD",
            0.60,
            minimum=0,
            maximum=1,
        ),
        max_candidate_topics=_get_int(
            "MAX_TOPIC_CANDIDATES",
            5,
            minimum=1,
        ),
    ),
    search=SearchConfig(
        default_page_size=_get_int(
            "PAGE_SIZE",
            20,
            minimum=1,
        ),
        maximum_page_size=_get_int(
            "MAX_PAGE_SIZE",
            100,
            minimum=10,
        ),
        snippet_length=_get_int(
            "SNIPPET_LENGTH",
            250,
            minimum=50,
        ),
        enable_bm25=_get_bool(
            "ENABLE_BM25",
            True,
        ),
    ),
    ocr=OCRConfig(
        language=_get_env("OCR_LANGUAGE", "eng"),
        deskew=_get_bool("OCR_DESKEW", True),
        optimize=_get_int("OCR_OPTIMIZE", 3),
    ),
    logging=LoggingConfig(
        level=_get_env("LOG_LEVEL", "INFO").upper(),
        console=_get_bool("LOG_CONSOLE", True),
        file=LOG_DIR / "application.log",
    ),
)