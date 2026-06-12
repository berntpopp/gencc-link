"""MCP tool registration for GenCC-Link."""

from __future__ import annotations

from gencc_link.mcp.tools.assertions import register_assertion_tools
from gencc_link.mcp.tools.discovery import register_discovery_tools
from gencc_link.mcp.tools.diseases import register_disease_tools
from gencc_link.mcp.tools.genes import register_gene_tools
from gencc_link.mcp.tools.submitters import register_submitter_tools

__all__ = [
    "register_assertion_tools",
    "register_discovery_tools",
    "register_disease_tools",
    "register_gene_tools",
    "register_submitter_tools",
]
