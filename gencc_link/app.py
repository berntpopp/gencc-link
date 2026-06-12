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
    """Application lifespan: configure logging on startup."""
    logger = configure_logging()
    logger.info("gencc-link starting", host=settings.host, port=settings.port)
    yield
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

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=settings.cors_allow_credentials,
        allow_methods=settings.cors_allow_methods,
        allow_headers=settings.cors_allow_headers,
    )

    @app.get("/health")
    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        """Liveness probe. Reports data status without forcing a build."""
        from gencc_link.mcp.capabilities import _data_status

        return {"status": "ok", "version": __version__, "data": _data_status()}

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
