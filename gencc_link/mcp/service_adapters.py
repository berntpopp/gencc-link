"""Service binding for MCP tools.

Single place where the repository + service are constructed for tool use. Tools
call ``get_gencc_service()``; tests can inject a service via
``set_service_for_testing``.
"""

from __future__ import annotations

from gencc_link.config import get_data_config
from gencc_link.mcp.envelope import set_data_release
from gencc_link.services.gencc_service import GenCCService

_OVERRIDE: GenCCService | None = None
_CACHED: GenCCService | None = None


def get_gencc_service() -> GenCCService:
    """Return the shared GenCCService, building the database if needed."""
    global _CACHED
    if _OVERRIDE is not None:
        return _OVERRIDE
    if _CACHED is not None:
        return _CACHED

    # Imported lazily so capabilities/import paths don't pull the data layer
    # until a tool actually needs it.
    from gencc_link.data.repository import GenCCRepository
    from gencc_link.ingest.builder import ensure_database

    cfg = get_data_config()
    db_path = ensure_database(cfg)
    repo = GenCCRepository(db_path)
    set_data_release(repo.get_meta().gencc_run_date)
    _CACHED = GenCCService(repo, cache_size=cfg.cache_size, cache_ttl=cfg.cache_ttl)
    return _CACHED


def set_service_for_testing(service: GenCCService | None) -> None:
    """Inject (or clear) a service instance for tests."""
    global _OVERRIDE
    _OVERRIDE = service


def reset_gencc_service() -> None:
    """Clear the cached service instance."""
    global _CACHED
    _CACHED = None
