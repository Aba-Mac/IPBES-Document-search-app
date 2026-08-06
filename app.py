"""
ASGI entry point for the IPBES Document Search application.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from database import repository
from database.migrations import migrate
from ingestion.pipeline import ingest_directory
from search.service import configure

LOGGER = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

_ingestion_state = {"status": "not_started"}


def _run_ingestion_sync():
    LOGGER.info("Background ingestion starting...")
    _ingestion_state["status"] = "running"
    pdf_dir = Path("data/pdfs")
    try:
        if pdf_dir.exists():
            ingest_directory(directory=pdf_dir, terms_txt="data/glossary/terms.txt")
        else:
            LOGGER.warning("PDF directory %s not found; skipping ingestion.", pdf_dir)
        _ingestion_state["status"] = "complete"
        LOGGER.info("Background ingestion finished.")
    except Exception:
        _ingestion_state["status"] = "failed"
        LOGGER.exception("Background ingestion failed.")


@asynccontextmanager
async def lifespan(app):
    LOGGER.info("Running database migration...")
    migrate()

    LOGGER.info("Configuring search service...")
    configure(repository)

    # Fire-and-forget: don't block startup on this.
    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, _run_ingestion_sync)

    yield


LOGGER.info("Importing UI...")
from ui.app import app as shiny_app


async def healthcheck(request):
    return JSONResponse({"status": "ok", "ingestion": _ingestion_state["status"]})


app = Starlette(
    debug=False,
    lifespan=lifespan,
    routes=[
        Route("/health", endpoint=healthcheck),
        Mount("/", app=shiny_app),
    ],
)

LOGGER.info("Application initialised.")