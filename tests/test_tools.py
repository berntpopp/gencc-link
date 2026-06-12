"""End-to-end MCP tool tests via a connected fastmcp client."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.mcp

EXPECTED_TOOLS = {
    "get_server_capabilities",
    "get_gencc_diagnostics",
    "search_genes",
    "search_diseases",
    "get_gene_curations",
    "get_disease_curations",
    "get_gene_disease_assertion",
    "find_curations",
    "list_submitters",
    "resolve_identifier",
}

EXPECTED_RESOURCES = {
    "gencc://capabilities",
    "gencc://usage",
    "gencc://reference",
    "gencc://license",
    "gencc://citation",
    "gencc://research-use",
}


async def test_list_tools(mcp_client) -> None:
    tools = await mcp_client.list_tools()
    names = {t.name for t in tools}
    assert names == EXPECTED_TOOLS


async def test_list_resources(mcp_client) -> None:
    resources = await mcp_client.list_resources()
    uris = {str(r.uri) for r in resources}
    assert uris == EXPECTED_RESOURCES


async def test_search_genes_success(mcp_client) -> None:
    result = await mcp_client.call_tool("search_genes", {"query": "SKI"})
    data = result.structured_content
    assert data["success"] is True
    assert "next_commands" in data["_meta"]
    # compact (default) swaps the full citation for a cacheable ref
    assert data["_meta"]["citation_ref"] == "gencc://citation"


async def test_search_diseases_success(mcp_client) -> None:
    result = await mcp_client.call_tool("search_diseases", {"query": "Fabry"})
    data = result.structured_content
    assert data["success"] is True
    assert data["_meta"]["next_commands"]


async def test_get_gene_curations_success(mcp_client) -> None:
    result = await mcp_client.call_tool("get_gene_curations", {"gene": "SKI"})
    data = result.structured_content
    assert data["success"] is True
    assert data["gene"]["gene_symbol"] == "SKI"
    assert "next_commands" in data["_meta"]
    assert data["_meta"]["citation_ref"] == "gencc://citation"


async def test_get_disease_curations_success(mcp_client) -> None:
    result = await mcp_client.call_tool("get_disease_curations", {"disease": "MONDO:0008426"})
    data = result.structured_content
    assert data["success"] is True


async def test_get_gene_disease_assertion_gla_conflict(mcp_client) -> None:
    result = await mcp_client.call_tool(
        "get_gene_disease_assertion",
        {"gene": "GLA", "disease": "MONDO:0010526", "response_mode": "full"},
    )
    data = result.structured_content
    assert data["success"] is True
    assert data["assertion"]["has_conflict"] is True
    assert data["assertion"]["submitters"]
    assert "submissions" in data


async def test_find_curations_success(mcp_client) -> None:
    result = await mcp_client.call_tool("find_curations", {"has_conflict": True})
    data = result.structured_content
    assert data["success"] is True
    assert data["total"] == 2


async def test_list_submitters_success(mcp_client) -> None:
    result = await mcp_client.call_tool("list_submitters", {})
    data = result.structured_content
    assert data["success"] is True
    assert data["count"] == 3
    assert "next_commands" in data["_meta"]


async def test_resolve_identifier_success(mcp_client) -> None:
    result = await mcp_client.call_tool("resolve_identifier", {"query": "SKI"})
    data = result.structured_content
    assert data["success"] is True
    assert data["gene"]["gene_symbol"] == "SKI"


async def test_capabilities_tool(mcp_client) -> None:
    result = await mcp_client.call_tool("get_server_capabilities", {})
    data = result.structured_content
    assert data["success"] is True
    assert len(data["tools"]) == 10
    assert data["data"]["status"] == "ready"


async def test_diagnostics_tool(mcp_client) -> None:
    result = await mcp_client.call_tool("get_gencc_diagnostics", {})
    data = result.structured_content
    assert data["success"] is True
    assert data["data"]["row_count"] == 31


async def test_error_not_found(mcp_client) -> None:
    result = await mcp_client.call_tool("get_gene_curations", {"gene": "NOTAGENE"})
    data = result.structured_content
    assert data["success"] is False
    assert data["error_code"] == "not_found"
    assert data["recovery_action"] == "reformulate_input"


async def test_error_invalid_input_no_filters(mcp_client) -> None:
    result = await mcp_client.call_tool("find_curations", {})
    data = result.structured_content
    assert data["success"] is False
    assert data["error_code"] == "invalid_input"


async def test_resource_capabilities_read(mcp_client) -> None:
    contents = await mcp_client.read_resource("gencc://capabilities")
    assert contents
    assert contents[0].text


class TestEvalHardening:
    async def test_search_genes_zero_result_propagates_query(self, mcp_client) -> None:
        result = await mcp_client.call_tool("search_genes", {"query": "ZZZXNOPE"})
        data = result.structured_content
        nxt = data["_meta"]["next_commands"]
        assert nxt == [] or nxt[0]["arguments"].get("query") == "ZZZXNOPE"

    async def test_find_curations_invalid_classification(self, mcp_client) -> None:
        result = await mcp_client.call_tool("find_curations", {"classification": ["Pathogenic"]})
        data = result.structured_content
        assert data["success"] is False
        assert data["error_code"] == "invalid_input"
        assert data["_meta"]["next_commands"][0]["tool"] == "get_server_capabilities"

    async def test_find_curations_invalid_submitter_recovery(self, mcp_client) -> None:
        result = await mcp_client.call_tool("find_curations", {"submitter": ["NotARealLab"]})
        data = result.structured_content
        assert data["success"] is False
        assert data["_meta"]["next_commands"][0]["tool"] == "list_submitters"

    async def test_gene_curations_not_found_recovery(self, mcp_client) -> None:
        result = await mcp_client.call_tool("get_gene_curations", {"gene": "NOTAGENE"})
        data = result.structured_content
        assert data["success"] is False
        assert data["error_code"] == "not_found"
        assert data["_meta"]["next_commands"][0] == {
            "tool": "search_genes",
            "arguments": {"query": "NOTAGENE"},
        }

    async def test_find_curations_matched_in_payload(self, mcp_client) -> None:
        result = await mcp_client.call_tool(
            "find_curations", {"classification": ["Refuted Evidence"]}
        )
        data = result.structured_content
        assert data["success"] is True
        assert data["results"]
        assert all("matched" in r for r in data["results"])

    async def test_request_id_and_timing_present(self, mcp_client) -> None:
        result = await mcp_client.call_tool("list_submitters", {})
        data = result.structured_content
        assert isinstance(data["_meta"]["request_id"], str)
        assert isinstance(data["_meta"]["elapsed_ms"], (int, float))

    async def test_compact_curations_has_citation_ref(self, mcp_client) -> None:
        result = await mcp_client.call_tool(
            "get_gene_curations", {"gene": "SKI", "response_mode": "compact"}
        )
        data = result.structured_content
        assert data["_meta"]["citation_ref"] == "gencc://citation"


class TestDiagnosticsQuota:
    async def test_diagnostics_has_quota_block(self, mcp_client) -> None:
        result = await mcp_client.call_tool("get_gencc_diagnostics", {})
        data = result.structured_content
        assert "quota" in data
        assert data["quota"]["daily_quota"] == 20
        assert "remaining" in data["quota"]
        assert "used_today" in data["quota"]
