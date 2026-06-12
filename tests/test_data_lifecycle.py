"""Tests for the data lifecycle: build lock, refresh scheduler, and hot-reload."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import pytest

from gencc_link.config import GenCCDataConfigModel
from gencc_link.exceptions import DataUnavailableError, DownloadError, QuotaExceededError
from gencc_link.ingest import builder as builder_mod
from gencc_link.ingest import lock as lock_mod
from gencc_link.ingest.builder import RebuildResult, build_database
from gencc_link.services import refresh as refresh_mod
from gencc_link.services.refresh import RefreshScheduler, build_scheduler

SAMPLE_TSV = Path("tests/fixtures/sample.tsv")


def _config(**kwargs) -> GenCCDataConfigModel:
    return GenCCDataConfigModel(
        data_dir=Path(tempfile.mkdtemp()), db_filename="gencc.sqlite", **kwargs
    )


# --- build lock -----------------------------------------------------------------


class TestBuildLock:
    def test_acquire_and_release(self) -> None:
        data_dir = Path(tempfile.mkdtemp())
        with lock_mod.build_lock(data_dir, timeout=5) as held:
            assert held is True
        # Re-acquire after release works.
        with lock_mod.build_lock(data_dir, timeout=5) as held:
            assert held is True

    @pytest.mark.skipif(not lock_mod._HAVE_FCNTL, reason="POSIX flock required")
    def test_contended_lock_times_out(self) -> None:
        data_dir = Path(tempfile.mkdtemp())
        with lock_mod.build_lock(data_dir, timeout=5):
            # A second acquisition (separate fd) must fail fast while held.
            with pytest.raises(DataUnavailableError):
                with lock_mod.build_lock(data_dir, timeout=0, poll_interval=0.01):
                    pass


# --- config ---------------------------------------------------------------------


class TestRefreshConfig:
    def test_defaults(self) -> None:
        cfg = GenCCDataConfigModel()
        assert cfg.refresh_enabled is True
        assert cfg.refresh_interval_hours == 24.0
        assert cfg.refresh_jitter_seconds == 300
        assert cfg.build_lock_timeout == 600

    def test_build_scheduler_disabled_returns_none(self) -> None:
        cfg = _config(refresh_enabled=False)
        assert build_scheduler(cfg) is None

    def test_build_scheduler_enabled_returns_scheduler(self) -> None:
        cfg = _config(refresh_enabled=True)
        assert isinstance(build_scheduler(cfg), RefreshScheduler)


# --- refresh scheduler ----------------------------------------------------------


class TestRefreshScheduler:
    async def test_runs_on_interval_and_applies_change(self, monkeypatch) -> None:
        cfg = _config()
        build_database(cfg, tsv_path=SAMPLE_TSV, etag="e0", last_modified="lm0")
        meta = builder_mod._read_meta(cfg.db_path)
        calls = {"n": 0}

        def fake_rebuild(config, *, force):
            calls["n"] += 1
            return RebuildResult(meta=meta, changed=True, not_modified=False)

        monkeypatch.setattr(builder_mod, "rebuild", fake_rebuild)
        sched = RefreshScheduler(cfg, None, interval_seconds=0.05, jitter_seconds=0.0)
        await sched.start()
        assert refresh_mod.get_active_scheduler() is sched
        await asyncio.sleep(0.18)
        await sched.stop()
        assert calls["n"] >= 2
        assert sched.status["state"] == "ok"
        assert sched.status["last_changed"] is True
        assert refresh_mod.get_active_scheduler() is None

    async def test_not_modified_records_unchanged(self, monkeypatch) -> None:
        cfg = _config()
        build_database(cfg, tsv_path=SAMPLE_TSV, etag="e0", last_modified="lm0")
        meta = builder_mod._read_meta(cfg.db_path)

        def fake_rebuild(config, *, force):
            return RebuildResult(meta=meta, changed=False, not_modified=True)

        monkeypatch.setattr(builder_mod, "rebuild", fake_rebuild)
        sched = RefreshScheduler(cfg, None, interval_seconds=0.05, jitter_seconds=0.0)
        await sched.start()
        await asyncio.sleep(0.12)
        await sched.stop()
        assert sched.status["last_changed"] is False
        assert sched.status["state"] == "ok"

    @pytest.mark.parametrize(
        "exc", [QuotaExceededError("q"), DownloadError("d"), RuntimeError("x")]
    )
    async def test_errors_do_not_kill_loop(self, monkeypatch, exc) -> None:
        cfg = _config()

        def fake_rebuild(config, *, force):
            raise exc

        monkeypatch.setattr(builder_mod, "rebuild", fake_rebuild)
        sched = RefreshScheduler(cfg, None, interval_seconds=0.05, jitter_seconds=0.0)
        await sched.start()
        await asyncio.sleep(0.12)
        # Still running after an error.
        assert sched._task is not None and not sched._task.done()
        await sched.stop()
        assert sched.status["state"] == "error"
        assert sched.status["last_error"] is not None

    async def test_start_is_idempotent_and_stop_cancels(self) -> None:
        cfg = _config()
        sched = RefreshScheduler(cfg, None, interval_seconds=10, jitter_seconds=0.0)
        await sched.start()
        task = sched._task
        await sched.start()  # no-op
        assert sched._task is task
        await sched.stop()
        assert sched._task is None


# --- hot reload -----------------------------------------------------------------


class TestHotReload:
    def test_service_reopens_after_db_swap(self, monkeypatch) -> None:
        from gencc_link.mcp import service_adapters as sa

        cfg = _config(auto_bootstrap=False)
        build_database(cfg, tsv_path=SAMPLE_TSV, etag="e0", last_modified="lm0")
        monkeypatch.setattr(sa, "get_data_config", lambda: cfg)
        sa.reset_gencc_service()
        try:
            svc1 = sa.get_gencc_service()
            assert svc1.get_meta().source_etag == "e0"
            # Same object while the file is unchanged.
            assert sa.get_gencc_service() is svc1
            # Atomically swap in a new build with a different etag.
            build_database(cfg, tsv_path=SAMPLE_TSV, etag="e1", last_modified="lm1")
            svc2 = sa.get_gencc_service()
            assert svc2 is not svc1
            assert svc2.get_meta().source_etag == "e1"
        finally:
            sa.reset_gencc_service()


# --- diagnostics surface --------------------------------------------------------


class TestDiagnosticsRefresh:
    @pytest.mark.mcp
    async def test_diagnostics_includes_refresh(self, mcp_client) -> None:
        payload = (await mcp_client.call_tool("get_gencc_diagnostics", {})).structured_content
        assert payload["success"] is True
        assert "refresh" in payload
        assert "enabled" in payload["refresh"]
        assert "interval_hours" in payload["refresh"]
        assert "scheduler_running" in payload["refresh"]
