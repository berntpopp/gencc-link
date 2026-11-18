"""Host/Origin boundary contracts for the unified MCP application."""

from __future__ import annotations

from importlib.metadata import version

import pytest
from fastapi.testclient import TestClient
from packaging.version import Version

from gencc_link.config import ServerSettings, settings
from gencc_link.server_manager import create_unified_app


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(
        settings,
        "allowed_hosts",
        ["localhost", "127.0.0.1", "::1", "gencc-link.genefoundry.org"],
    )
    monkeypatch.setattr(settings, "allowed_origins", ["https://genefoundry.org"])
    return TestClient(create_unified_app(), raise_server_exceptions=False)


def test_fastmcp_344_strict_guard_is_installed(client: TestClient) -> None:
    assert Version(version("fastmcp")) >= Version("3.4.4")

    response = client.get("/mcp", headers={"Host": "gencc-link.genefoundry.org"})
    assert response.status_code not in {403, 421}


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "[::1]"])
def test_loopback_hosts_are_allowed(client: TestClient, host: str) -> None:
    response = client.get("/mcp", headers={"Host": host})
    assert response.status_code not in {403, 421}


@pytest.mark.parametrize("path", ["/", "/health", "/mcp"])
def test_untrusted_host_is_rejected_on_every_route(client: TestClient, path: str) -> None:
    response = client.get(path, headers={"Host": "evil.example"})
    assert response.status_code == 421


def test_absent_and_configured_origins_are_allowed(client: TestClient) -> None:
    no_origin = client.get("/mcp", headers={"Host": "gencc-link.genefoundry.org"})
    configured_origin = client.get(
        "/mcp",
        headers={
            "Host": "gencc-link.genefoundry.org",
            "Origin": "https://genefoundry.org",
        },
    )
    assert no_origin.status_code not in {403, 421}
    assert configured_origin.status_code not in {403, 421}


@pytest.mark.parametrize("path", ["/", "/health", "/mcp"])
def test_untrusted_origin_is_rejected_on_every_route(client: TestClient, path: str) -> None:
    response = client.get(
        path,
        headers={"Host": "gencc-link.genefoundry.org", "Origin": "https://evil.example"},
    )
    assert response.status_code == 403


@pytest.mark.parametrize("wildcard", ["*", "*.example.org", "host?.example.org", "host[0]"])
def test_wildcard_host_is_rejected(wildcard: str) -> None:
    with pytest.raises(ValueError, match="wildcard"):
        ServerSettings(_env_file=None, allowed_hosts=[wildcard])


def test_json_environment_allowlists_are_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "GENCC_LINK_ALLOWED_HOSTS",
        '["localhost","gencc-link.genefoundry.org"]',
    )
    monkeypatch.setenv("GENCC_LINK_ALLOWED_ORIGINS", '["https://genefoundry.org"]')

    configured = ServerSettings(_env_file=None)

    assert configured.allowed_hosts == ["localhost", "gencc-link.genefoundry.org"]
    assert configured.allowed_origins == ["https://genefoundry.org"]


_MODERN_VERSION = "2026-07-28"
_MODERN_META = {
    "io.modelcontextprotocol/protocolVersion": _MODERN_VERSION,
    "io.modelcontextprotocol/clientCapabilities": {},
    "io.modelcontextprotocol/clientInfo": {"name": "gencc-host-test", "version": "1.0.0"},
}


def _modern_post(
    client: TestClient, req_id: int, method: str, params: dict[str, object], name: str | None = None
):  # type: ignore[no-untyped-def]
    headers = {
        "accept": "application/json, text/event-stream",
        "content-type": "application/json",
        "host": "localhost",
        "mcp-protocol-version": _MODERN_VERSION,
        "mcp-method": method,
    }
    if name is not None:
        headers["mcp-name"] = name
    return client.post(
        "/mcp",
        headers=headers,
        json={
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": {"_meta": _MODERN_META, **params},
        },
    )


def test_modern_mcp_http_discovers_lists_calls_and_fences_unknown_tool(
    client: TestClient,
) -> None:
    """The 2026-07-28 sessionless era passes the Host/Origin guard end to end."""

    hostile = "ignore-instructions-secret"
    with client:
        discover = _modern_post(client, 1, "server/discover", {})
        listed = _modern_post(client, 2, "tools/list", {})
        called = _modern_post(
            client,
            3,
            "tools/call",
            {"name": "get_server_capabilities", "arguments": {}},
            name="get_server_capabilities",
        )
        unknown = _modern_post(
            client, 4, "tools/call", {"name": hostile, "arguments": {}}, name=hostile
        )

    assert discover.status_code == 200
    assert _MODERN_VERSION in discover.json()["result"]["supportedVersions"]
    assert "mcp-session-id" not in discover.headers
    assert listed.status_code == 200
    assert "get_server_capabilities" in {t["name"] for t in listed.json()["result"]["tools"]}
    assert called.status_code == 200
    called_result = called.json()["result"]
    assert called_result["structuredContent"]["success"] is True
    assert unknown.status_code == 200
    unknown_result = unknown.json()["result"]
    assert unknown_result["isError"] is True
    assert unknown_result["structuredContent"]["error_code"] == "not_found"
    assert hostile not in unknown.text
