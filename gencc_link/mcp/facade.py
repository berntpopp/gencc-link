"""MCP facade for GenCC-Link."""

from __future__ import annotations

from fastmcp import FastMCP

from gencc_link import __version__
from gencc_link.mcp.capabilities import register_capability_resources
from gencc_link.mcp.middleware import InputValidationMiddleware
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
        version=__version__,
        instructions=GENCC_SERVER_INSTRUCTIONS,
        mask_error_details=True,
    )
    # Error-handling middleware goes first so it wraps every tool call and can
    # turn pre-body argument-validation failures into a structured envelope.
    mcp.add_middleware(InputValidationMiddleware())

    register_discovery_tools(mcp)
    register_gene_tools(mcp)
    register_disease_tools(mcp)
    register_assertion_tools(mcp)
    register_submitter_tools(mcp)
    register_capability_resources(mcp)

    return mcp
