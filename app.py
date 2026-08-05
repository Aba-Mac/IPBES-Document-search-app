"""
ASGI entry point for the IPBES Document Search application.

Only lightweight startup work should occur here.
"""

from __future__ import annotations

import logging
from typing import Final

from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from database import repository
from database.migrations import migrate
from search.service import configure

LOGGER = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

LOGGER.info("Running database migration...")
migrate()

LOGGER.info("Configuring search service...")
configure(repository)

LOGGER.info("Importing UI...")
from ui.app import app as shiny_app


async def healthcheck(request):
    return JSONResponse(
        {
            "status": "ok",
            "service": "document-search",
        }
    )


app = Starlette(
    debug=False,
    routes=[
        Route("/health", endpoint=healthcheck),
        Mount("/", app=shiny_app),
    ],
)

LOGGER.info("Application initialised.")