"""Discovery tools: server capabilities and data diagnostics."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from gencc_link.mcp.annotations import READ_ONLY_OPEN_WORLD
from gencc_link.mcp.capabilities import build_capabilities
from gencc_link.mcp.envelope import McpErrorContext, run_mcp_tool
from gencc_link.mcp.service_adapters import get_gencc_service

if TYPE_CHECKING:
    from fastmcp import FastMCP


def register_discovery_tools(mcp: FastMCP) -> None:
    """Register get_server_capabilities and get_gencc_diagnostics."""

    @mcp.tool(
        name="get_server_capabilities",
        title="Get Server Capabilities",
        annotations=READ_ONLY_OPEN_WORLD,
        tags={"discovery"},
        description=(
            "Return the GenCC-Link tool inventory, classification vocabulary and "
            "ranks, response modes, recommended workflows, error codes, resources, "
            "and live data freshness. Compare `capabilities_version` to skip "
            "re-fetching when unchanged."
        ),
    )
    async def get_server_capabilities() -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            return build_capabilities()

        return await run_mcp_tool(
            "get_server_capabilities", call, context=McpErrorContext("get_server_capabilities")
        )

    @mcp.tool(
        name="get_gencc_diagnostics",
        title="Get GenCC Diagnostics",
        annotations=READ_ONLY_OPEN_WORLD,
        tags={"discovery"},
        description=(
            "Report build provenance and data freshness: GenCC run date, source "
            "ETag/last-modified, row/gene/disease/submitter counts, schema version, "
            "and when the local database was built."
        ),
    )
    async def get_gencc_diagnostics() -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            meta = get_gencc_service().get_meta()
            return {
                "headline": (
                    f"GenCC data: {meta.row_count} submissions, {meta.gene_count} genes, "
                    f"{meta.disease_count} diseases from {meta.submitter_count} submitters; "
                    f"run date {meta.gencc_run_date or 'unknown'}."
                ),
                "data": meta.model_dump(),
            }

        return await run_mcp_tool(
            "get_gencc_diagnostics", call, context=McpErrorContext("get_gencc_diagnostics")
        )
