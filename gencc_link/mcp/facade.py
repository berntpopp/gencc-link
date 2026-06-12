"""MCP facade for GenCC-Link."""

from __future__ import annotations

from fastmcp import FastMCP

from gencc_link.mcp.capabilities import register_capability_resources
from gencc_link.mcp.resources import GENCC_SERVER_INSTRUCTIONS
from gencc_link.mcp.tools import (
    register_assertion_tools,
    register_discovery_tools,
    register_disease_tools,
    register_gene_tools,
    register_submitter_tools,
)


def create_gencc_mcp() -> FastMCP:
    """Build a FastMCP instance for GenCC-Link with all tools and resources."""
    mcp = FastMCP(
        name="gencc-link",
        instructions=GENCC_SERVER_INSTRUCTIONS,
        mask_error_details=True,
    )

    register_discovery_tools(mcp)
    register_gene_tools(mcp)
    register_disease_tools(mcp)
    register_assertion_tools(mcp)
    register_submitter_tools(mcp)
    register_capability_resources(mcp)

    return mcp
