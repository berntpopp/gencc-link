"""In-process scheduled refresh of the GenCC database.

A dependency-free asyncio loop that, on an interval, runs a *conditional*
refresh (HTTP ETag/Last-Modified; an unchanged export returns 304 and costs no
download quota). When the export changed, it rebuilds atomically and hot-reloads
the served database. The blocking download+build runs in a worker thread so the
event loop is never stalled.

The first run is scheduled one interval *after* startup, because the container
entrypoint (or the lifespan bootstrap) already ensures fresh data at boot. Only
the unified/http transports start this scheduler; stdio is short-lived and does
not.

For deployments that prefer a dedicated scheduler (cron sidecar, Kubernetes
CronJob, systemd timer), disable this via ``GENCC_LINK_DATA__REFRESH_ENABLED=false``
and run ``gencc-link-data refresh`` externally — the server still hot-reloads the
swapped database file.
"""

from __future__ import annotations

import asyncio
import contextlib
import random
from typing import TYPE_CHECKING, Any

from gencc_link.exceptions import DownloadError, QuotaExceededError

if TYPE_CHECKING:
    from structlog.typing import FilteringBoundLogger

    from gencc_link.config import GenCCDataConfigModel

# Fixed, low-cardinality classifications stored as ``last_error`` (surfaced by the
# get_gencc_diagnostics MCP tool). A raw ``str(exc)`` is never stored: it can carry
# the export URL, filesystem paths, or transport detail into a caller-visible field.
_REFRESH_ERROR_QUOTA = "quota_exceeded"
_REFRESH_ERROR_DOWNLOAD = "download_failed"
_REFRESH_ERROR_INTERNAL = "internal_error"

# The currently active scheduler (for diagnostics), set on start, cleared on stop.
_ACTIVE: RefreshScheduler | None = None


def get_active_scheduler() -> RefreshScheduler | None:
    """Return the running scheduler, if any (used by diagnostics)."""
    return _ACTIVE


class RefreshScheduler:
    """Periodically run a conditional GenCC refresh and hot-reload on change."""

    def __init__(
        self,
        config: GenCCDataConfigModel,
        logger: FilteringBoundLogger | None = None,
        *,
        interval_seconds: float | None = None,
        jitter_seconds: float | None = None,
    ) -> None:
        self._config = config
        self._logger = logger
        self._interval = (
            interval_seconds
            if interval_seconds is not None
            else config.refresh_interval_hours * 3600.0
        )
        self._jitter = (
            jitter_seconds if jitter_seconds is not None else float(config.refresh_jitter_seconds)
        )
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self._status: dict[str, Any] = {
            "enabled": True,
            "interval_seconds": self._interval,
            "state": "pending",
            "last_checked_utc": None,
            "last_changed": False,
            "last_error": None,
        }

    @property
    def status(self) -> dict[str, Any]:
        """A snapshot of the scheduler's last refresh outcome (for diagnostics)."""
        return dict(self._status)

    async def start(self) -> None:
        """Start the background refresh loop (idempotent)."""
        global _ACTIVE
        if self._task is not None:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._loop(), name="gencc-refresh")
        _ACTIVE = self
        if self._logger:
            self._logger.info(
                "refresh scheduler started",
                interval_seconds=self._interval,
                jitter_seconds=self._jitter,
            )

    async def stop(self) -> None:
        """Stop the loop and wait for the task to finish."""
        global _ACTIVE
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        if _ACTIVE is self:
            _ACTIVE = None
        if self._logger:
            self._logger.info("refresh scheduler stopped")

    async def _loop(self) -> None:
        while not self._stop.is_set():
            delay = self._interval + random.uniform(0, self._jitter)  # noqa: S311 - not crypto
            # Sleep, but wake immediately if stop() is called.
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=delay)
            if self._stop.is_set():
                return
            await self._run_once()

    async def _run_once(self) -> None:
        """Run one conditional refresh; hot-reload the service when it changed."""
        from gencc_link.ingest.builder import rebuild

        try:
            result = await asyncio.to_thread(rebuild, self._config, force=False)
        except QuotaExceededError:
            # Store a FIXED classification, not str(exc): the raw download exception
            # can carry the export URL / transport detail, and last_error is surfaced
            # by the get_gencc_diagnostics MCP tool. The raw value is not logged either
            # (M3 no-PII-in-logs invariant).
            self._record(error=_REFRESH_ERROR_QUOTA)
            if self._logger:
                self._logger.warning("refresh skipped: quota exceeded")
            return
        except DownloadError:
            self._record(error=_REFRESH_ERROR_DOWNLOAD)
            if self._logger:
                self._logger.warning("refresh failed: download error")
            return
        except Exception as exc:  # defensive: a refresh must never kill the loop
            self._record(error=_REFRESH_ERROR_INTERNAL)
            if self._logger:
                # Only the stable exception class name -- never str(exc).
                self._logger.error("refresh failed", error_type=type(exc).__name__)
            return

        if result.changed:
            self._reload(result.meta.gencc_run_date)
            if self._logger:
                self._logger.info(
                    "refresh applied: database rebuilt",
                    gencc_run_date=result.meta.gencc_run_date,
                    rows=result.meta.row_count,
                )
        elif self._logger:
            self._logger.info("refresh check: source not modified")
        self._record(changed=result.changed, run_date=result.meta.gencc_run_date)

    @staticmethod
    def _reload(run_date: str | None) -> None:
        from gencc_link.mcp.envelope import set_data_release
        from gencc_link.mcp.service_adapters import reset_gencc_service

        reset_gencc_service()
        set_data_release(run_date)

    def _record(
        self, *, changed: bool = False, run_date: str | None = None, error: str | None = None
    ) -> None:
        from datetime import UTC, datetime

        self._status.update(
            {
                "state": "error" if error else "ok",
                "last_checked_utc": datetime.now(tz=UTC).isoformat(),
                "last_changed": changed,
                "last_error": error,
            }
        )
        if run_date is not None:
            self._status["last_run_date"] = run_date


def build_scheduler(
    config: GenCCDataConfigModel, logger: FilteringBoundLogger | None = None
) -> RefreshScheduler | None:
    """Return a scheduler when in-app refresh is enabled, else ``None``."""
    if not config.refresh_enabled:
        return None
    return RefreshScheduler(config, logger)
