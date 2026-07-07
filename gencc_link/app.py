"""FastAPI application factory for GenCC-Link (health + discovery surface)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import __version__
from .config import settings
from .logging_config import configure_logging

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: ensure data is present, then run the refresh scheduler.

    The startup build is non-fatal: if the database cannot be built (e.g. an
    external scheduler owns it and has not run yet), the server still starts and
    tools report ``data_unavailable`` until data lands. The in-process scheduler
    keeps the database fresh and hot-reloads it on change.
    """
    import asyncio

    from gencc_link.config import get_data_config
    from gencc_link.ingest.builder import ensure_database
    from gencc_link.services.refresh import build_scheduler

    logger = configure_logging()
    logger.info("gencc-link starting", host=settings.host, port=settings.port)

    cfg = get_data_config()
    try:
        await asyncio.to_thread(ensure_database, cfg)
    except Exception as exc:  # non-fatal: serve, report data_unavailable until ready
        logger.warning("database not ready at startup", error=str(exc))

    scheduler = build_scheduler(cfg, logger)
    if scheduler is not None:
        await scheduler.start()
    try:
        yield
    finally:
        if scheduler is not None:
            await scheduler.stop()
        logger.info("gencc-link shutting down")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="GenCC-Link",
        description="MCP/API server for Gene Curation Coalition gene-disease validity data",
        version=__version__,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # This backend is unauthenticated by design (no cookies/session), so CORS
    # credentials are meaningless: force them off. Additionally fail loud on the
    # dangerous wildcard-origin + credentials combination (Container Hardening
    # Standard v1; browsers also reject "*" + credentials).
    if settings.cors_allow_credentials and "*" in settings.cors_origins:
        raise RuntimeError(
            "Invalid CORS configuration: allow_credentials=True with wildcard '*' origin"
        )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=settings.cors_allow_methods,
        allow_headers=settings.cors_allow_headers,
    )

    @app.get("/health")
    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        """Liveness probe. Reports data status without forcing a build."""
        from gencc_link.mcp.capabilities import _data_status

        return {
            "status": "ok",
            "version": __version__,
            "transport": "streamable-http-stateless",
            "data": _data_status(),
        }

    @app.get("/")
    async def root() -> dict[str, Any]:
        """Service metadata."""
        return {
            "name": "GenCC-Link",
            "version": __version__,
            "description": (
                "MCP/API server for Gene Curation Coalition gene-disease validity data"
            ),
            "docs": "/docs",
            "health": "/health",
            "mcp_endpoint": settings.mcp_path,
        }

    return app


app = create_app()
