"""
ASGI entry point for the IPBES Document Search application.
"""

from __future__ import annotations

import logging
from core.logging_config import configure_logging
from contextlib import asynccontextmanager

from starlette.applications import Starlette
from starlette.routing import Mount

from database import repository
from database.migrations import migrate
from search.service import configure

LOGGER = logging.getLogger(__name__)
configure_logging()


LOGGER.info("Running database migration...")
migrate()

LOGGER.info("Configuring search service...")
configure(repository)


@asynccontextmanager
async def lifespan(app):

    LOGGER.info("Application startup complete.")

    yield

    LOGGER.info("Application shutdown.")


LOGGER.info("Importing UI...")
from ui.app import app as shiny_app


app = Starlette(
    debug=False,
    lifespan=lifespan,
    routes=[
        Mount("/", app=shiny_app),
    ],
)

LOGGER.info("Application initialised.")