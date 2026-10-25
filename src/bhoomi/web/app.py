"""FastAPI application factory.

A factory rather than a module-level ``app`` so tests can inject a container with
fixtures and no network, and so the composition root stays the single place that
decides on adapters.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from bhoomi.composition import Container, build_container
from bhoomi.domain.errors import (
    BhoomiError,
    PlaceNotFoundError,
    UpstreamAuthError,
    UpstreamUnavailableError,
)
from bhoomi.web.routes import router

logger = logging.getLogger("bhoomi")

STATIC_DIR = Path(__file__).parent / "static"


def create_app(
    container: Container | None = None,
    *,
    container_factory: Callable[[], Container] = build_container,
) -> FastAPI:
    """Build the ASGI app.

    Pass ``container`` to pin one (tests), or leave it and the factory runs on
    startup.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.container = container or container_factory()
        logger.info(
            "bhoomi ready: data_source=%s", app.state.container.data_source
        )
        try:
            yield
        finally:
            app.state.container.close()

    app = FastAPI(
        title="Bhoomi Mitra",
        version="1.0.0",
        summary=(
            "A multilingual, agentic civic-information assistant built on ISRO "
            "Bhuvan data and Sarvam AI."
        ),
        lifespan=lifespan,
    )

    app.include_router(router)

    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

        @app.get("/", include_in_schema=False)
        def index() -> FileResponse:
            return FileResponse(STATIC_DIR / "index.html")

    _register_error_handlers(app)
    return app


def _register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(PlaceNotFoundError)
    async def _not_found(request: Request, exc: PlaceNotFoundError) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={"error": "place_not_found", "detail": str(exc)},
        )

    @app.exception_handler(UpstreamAuthError)
    async def _auth(request: Request, exc: UpstreamAuthError) -> JSONResponse:
        logger.warning("upstream auth failure: %s", exc)
        return JSONResponse(
            status_code=502,
            content={
                "error": "upstream_auth_failed",
                "detail": (
                    "The upstream provider rejected the configured credentials. "
                    "Check BHUVAN_TOKEN / SARVAM_API_KEY, or run with "
                    "BHOOMI_DATA_MODE=fixture."
                ),
            },
        )

    @app.exception_handler(UpstreamUnavailableError)
    async def _unavailable(
        request: Request, exc: UpstreamUnavailableError
    ) -> JSONResponse:
        logger.warning("upstream unavailable: %s", exc)
        return JSONResponse(
            status_code=503,
            content={"error": "upstream_unavailable", "detail": str(exc)},
        )

    @app.exception_handler(BhoomiError)
    async def _domain(request: Request, exc: BhoomiError) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={"error": "domain_error", "detail": str(exc)},
        )
