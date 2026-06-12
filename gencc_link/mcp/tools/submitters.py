"""Submitter tools: list_submitters."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from gencc_link.mcp.annotations import READ_ONLY_OPEN_WORLD
from gencc_link.mcp.envelope import McpErrorContext, run_mcp_tool
from gencc_link.mcp.next_commands import cmd
from gencc_link.mcp.schemas import LIST_SUBMITTERS_SCHEMA
from gencc_link.mcp.service_adapters import get_gencc_service

if TYPE_CHECKING:
    from fastmcp import FastMCP


def register_submitter_tools(mcp: FastMCP) -> None:
    """Register the list_submitters reference tool."""

    @mcp.tool(
        name="list_submitters",
        title="List GenCC Submitters",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=LIST_SUBMITTERS_SCHEMA,
        tags={"reference"},
        description=(
            "List the GenCC submitting organizations (ClinGen, Genomics England "
            "PanelApp, Orphanet, Ambry, Invitae, Illumina, and others) with their "
            "submission, gene, and disease counts. Use submitter titles to filter "
            "find_curations."
        ),
    )
    async def list_submitters() -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            payload = get_gencc_service().list_submitters()
            payload["headline"] = f"{payload['count']} GenCC submitting organizations."
            payload["_meta"] = {
                "next_commands": [
                    cmd("find_curations", submitter=[payload["submitters"][0]["submitter_title"]])
                ]
                if payload.get("submitters")
                else []
            }
            return payload

        return await run_mcp_tool(
            "list_submitters", call, context=McpErrorContext("list_submitters")
        )
