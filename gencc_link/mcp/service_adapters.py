"""Service binding for MCP tools.

Single place where the repository + service are constructed for tool use. Tools
call ``get_gencc_service()``. The cached service **hot-reloads** when the
database file on disk changes (e.g. after a scheduled refresh or an external cron
rebuild atomically swaps the file): a cheap ``stat`` per call detects the new
file and reopens the read-only connection. Tests can inject a service via
``set_service_for_testing``.
"""

from __future__ import annotations

from pathlib import Path

from gencc_link.config import get_data_config
from gencc_link.mcp.envelope import set_data_release
from gencc_link.services.gencc_service import GenCCService

_OVERRIDE: GenCCService | None = None
_CACHED: GenCCService | None = None
_CACHED_MTIME: float | None = None
_REPO: object | None = None  # GenCCRepository; typed loosely to avoid import cycle


def _db_mtime(path: Path) -> float | None:
    """Return the database file's mtime, or ``None`` when it does not exist."""
    try:
        return path.stat().st_mtime_ns / 1_000_000_000
    except FileNotFoundError:
        return None


def get_gencc_service() -> GenCCService:
    """Return the shared GenCCService, building or reopening the database as needed.

    Reopens the underlying read-only connection when the database file changes,
    so a refresh that atomically swaps ``gencc.sqlite`` is picked up live.
    """
    global _CACHED, _CACHED_MTIME, _REPO
    if _OVERRIDE is not None:
        return _OVERRIDE

    cfg = get_data_config()
    current_mtime = _db_mtime(cfg.db_path)
    if _CACHED is not None and current_mtime is not None and current_mtime == _CACHED_MTIME:
        return _CACHED

    # Imported lazily so capabilities/import paths don't pull the data layer
    # until a tool actually needs it.
    from gencc_link.data.repository import GenCCRepository
    from gencc_link.ingest.builder import ensure_database

    _close_repo()
    db_path = ensure_database(cfg)
    repo = GenCCRepository(db_path)
    set_data_release(repo.get_meta().gencc_run_date)
    _REPO = repo
    _CACHED = GenCCService(repo, cache_size=cfg.cache_size, cache_ttl=cfg.cache_ttl)
    _CACHED_MTIME = _db_mtime(db_path)
    return _CACHED


def _close_repo() -> None:
    """Close and drop the cached repository/service, if any."""
    global _CACHED, _CACHED_MTIME, _REPO
    if _REPO is not None:
        close = getattr(_REPO, "close", None)
        if callable(close):
            close()
    _REPO = None
    _CACHED = None
    _CACHED_MTIME = None


def set_service_for_testing(service: GenCCService | None) -> None:
    """Inject (or clear) a service instance for tests."""
    global _OVERRIDE
    _OVERRIDE = service


def reset_gencc_service() -> None:
    """Clear the cached service so the next call reopens the database."""
    _close_repo()
