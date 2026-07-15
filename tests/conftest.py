"""Shared pytest fixtures for the GenCC-Link test suite.

A single SQLite database is built once per session from the committed
``tests/fixtures/sample.tsv`` using the real ingest builder, then wrapped in a
repository, service, and (for MCP tests) a connected fastmcp client.
"""

from __future__ import annotations

import tempfile
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest

from gencc_link.config import GenCCDataConfigModel
from gencc_link.data.repository import GenCCRepository
from gencc_link.ingest.builder import build_database
from gencc_link.services.gencc_service import GenCCService

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
SAMPLE_TSV = FIXTURES_DIR / "sample.tsv"


@pytest.fixture(scope="session")
def built_db_path() -> Iterator[Path]:
    """Build the sample database once for the whole test session."""
    data_dir = Path(tempfile.mkdtemp(prefix="gencc-test-"))
    cfg = GenCCDataConfigModel(data_dir=data_dir, db_filename="sample.sqlite")
    build_database(cfg, tsv_path=SAMPLE_TSV, etag="test-etag", last_modified="test-lm")
    yield cfg.db_path


@pytest.fixture
def repository(built_db_path: Path) -> Iterator[GenCCRepository]:
    """A read-only repository over the built sample database."""
    repo = GenCCRepository(built_db_path)
    try:
        yield repo
    finally:
        repo.close()


@pytest.fixture
def service(repository: GenCCRepository) -> GenCCService:
    """A GenCCService backed by the sample repository (cache enabled)."""
    return GenCCService(repository, cache_size=512, cache_ttl=3600)


@pytest.fixture
async def mcp_client(service: GenCCService) -> AsyncIterator[object]:
    """A connected fastmcp client with the service injected for tool use."""
    from fastmcp import Client

    from gencc_link.mcp.facade import create_gencc_mcp
    from gencc_link.mcp.service_adapters import (
        reset_gencc_service,
        set_service_for_testing,
    )

    set_service_for_testing(service)
    try:
        async with Client(create_gencc_mcp()) as client:
            # Error envelopes now carry MCP isError:true, so the fastmcp Client
            # raises ToolError by default. These tests inspect the structured error
            # envelope, so default call_tool to raise_on_error=False; the wire-level
            # isError contract is exercised by tests/conformance/test_behaviour_v1.
            yield _NonRaisingClient(client)
    finally:
        set_service_for_testing(None)
        reset_gencc_service()


class _NonRaisingClient:
    """Proxy that defaults ``call_tool`` to ``raise_on_error=False``."""

    def __init__(self, client: object) -> None:
        self._client = client

    async def call_tool(self, *args: object, **kwargs: object) -> object:
        kwargs.setdefault("raise_on_error", False)
        return await self._client.call_tool(*args, **kwargs)  # type: ignore[attr-defined]

    def __getattr__(self, name: str) -> object:
        return getattr(self._client, name)
