"""
Top-level application entry point.

This module is intentionally thin. It imports the fully assembled Shiny
application from ``ui.app`` and exposes it as ``app`` for Posit Connect.

It also exposes a lightweight health-check endpoint suitable for Posit
Connect monitoring and external load balancers.

Deployment:

    GitHub
        ↓
    Posit Connect

Posit Connect expects a top-level ``app`` object.

Author:
    Your Project

License:
    MIT
"""

from __future__ import annotations

import logging
from typing import Final

from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from search.service import configure
from database import repository
from database.migrations import migrate

LOGGER = logging.getLogger(__name__)
LOGGER.info("Running database migration...")
migrate()
LOGGER.info("Migration finished.")

print(
    "Documents:",
    repository.table_row_count("documents")
)

print(
    "Paragraphs:",
    repository.table_row_count("paragraphs")
)

print(
    "Terms:",
    repository.table_row_count("terms")
)

configure(repository)

from ui.app import app as shiny_app

###############################################################################
# Logging
###############################################################################

LOGGER: Final = logging.getLogger(__name__)

###############################################################################
# Health Check
###############################################################################


async def healthcheck(request):
    """
    Health endpoint.

    Used by Posit Connect and reverse proxies to verify that the
    application process is alive.

    Returns
    -------
    JSONResponse
        HTTP 200 with a simple JSON payload.
    """
    return JSONResponse(
        {
            "status": "ok",
            "service": "document-search",
        },
        status_code=200,
    )


###############################################################################
# Combined ASGI application
###############################################################################

app = Starlette(
    debug=False,
    routes=[
        Route(
            "/health",
            endpoint=healthcheck,
            methods=["GET"],
        ),
        Mount(
            "/",
            app=shiny_app,
        ),
    ],
)

LOGGER.info("Application initialised.")