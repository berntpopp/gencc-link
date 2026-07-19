"""Contract Truth v1 gate against the live GenCC MCP registry."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING, Never

import pytest

if TYPE_CHECKING:
    from gencc_link.services.gencc_service import GenCCService

EXPECTED_HELPER_SHA256 = "e6c12b087c8231f5324c6388abd01afaeffa305a84d0b7c0e3629e17993d3674"


async def test_documentation_matches_live_mcp_contract(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    service: GenCCService,
) -> None:
    """Lint repository documentation against the production MCP registry."""
    helper_path = Path(__file__).with_name("contract_truth.py")
    pin_path = Path(__file__).with_name("contract_truth.sha256")

    vendored_pin = pin_path.read_text(encoding="utf-8").strip()
    assert vendored_pin == EXPECTED_HELPER_SHA256
    assert sha256(helper_path.read_bytes()).hexdigest() == vendored_pin

    from .contract_truth import (
        active_markdown_files,
        historical_markdown_files,
        lint_repository,
    )

    monkeypatch.chdir(tmp_path)

    from gencc_link.mcp import service_adapters
    from gencc_link.mcp.facade import create_gencc_mcp

    bootstrap_calls: list[str] = []

    def reject_data_config() -> Never:
        bootstrap_calls.append("get_data_config")
        raise AssertionError("contract discovery must not bootstrap repository data")

    monkeypatch.setattr(service_adapters, "get_data_config", reject_data_config)
    service_adapters.set_service_for_testing(service)
    try:
        assert service_adapters.get_gencc_service() is service
        mcp = create_gencc_mcp()
        tools = await mcp.list_tools()
        assert bootstrap_calls == []
    finally:
        service_adapters.set_service_for_testing(None)
        service_adapters.reset_gencc_service()

    assert tools, "the live MCP registry must not be empty"
    catalog: dict[str, dict[str, object]] = {}
    for tool in tools:
        assert isinstance(tool.parameters, dict)
        catalog[tool.name] = {"inputSchema": tool.parameters}

    repo_root = Path(__file__).resolve().parents[2]
    assert active_markdown_files(repo_root), "active Markdown discovery must not be empty"
    assert historical_markdown_files(repo_root), "historical Markdown discovery must not be empty"

    findings = lint_repository(repo_root, catalog)
    rendered = "\n".join(
        f"{finding.path}:{finding.line}: {finding.rule}: {finding.message}" for finding in findings
    )
    assert not findings, rendered
