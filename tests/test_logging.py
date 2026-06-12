"""Tests for logging configuration (gencc_link.logging_config)."""

from __future__ import annotations

import logging

from gencc_link.logging_config import (
    configure_logging,
    configure_stdlib_logging,
    configure_structlog,
)


def test_configure_stdlib_logging_sets_handler() -> None:
    configure_stdlib_logging()
    root = logging.getLogger()
    assert root.handlers
    # httpx noise suppressed.
    assert logging.getLogger("httpx").level == logging.WARNING


def test_configure_structlog_runs() -> None:
    configure_structlog()  # should not raise


def test_configure_logging_returns_bound_logger() -> None:
    logger = configure_logging()
    # A bound structlog logger exposes .info without raising.
    logger.info("test-event", key="value")


def test_configure_structlog_json(monkeypatch) -> None:
    import gencc_link.logging_config as mod

    monkeypatch.setattr(mod.settings, "log_format", "json")
    configure_structlog()


def test_configure_stdlib_debug(monkeypatch) -> None:
    import gencc_link.logging_config as mod

    monkeypatch.setattr(mod.settings, "log_level", "DEBUG")
    configure_stdlib_logging()
    assert logging.getLogger().level == logging.DEBUG
    # Restore a sane level for the rest of the suite.
    monkeypatch.setattr(mod.settings, "log_level", "INFO")
    configure_stdlib_logging()
