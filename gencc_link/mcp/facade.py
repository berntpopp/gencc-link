"""MCP facade for GenCC-Link."""

from __future__ import annotations

from fastmcp import FastMCP

from gencc_link import __version__
from gencc_link.mcp.capabilities import register_capability_resources
from gencc_link.mcp.middleware import InputValidationMiddleware
from gencc_link.mcp.notfound_guard import (
    NotFoundGuard,
    install_notfound_log_filter,
    install_protocol_error_handler,
)
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
        # Tool-Surface Budget v1: input schemas carry no $ref, so leaving them
        # dereferenced only bloats the surface. Off = ~26% smaller tool surface.
        dereference_schemas=False,
    )
    # Guard the FastMCP-core not-found reflection surface: core echoes the caller's
    # OWN requested tool name / resource URI / prompt name (with any control/
    # zero-width/bidi/NUL code points) to the caller and to logs BEFORE backend
    # middleware runs. NotFoundGuard preflights the tool NAME (unknown -> fixed
    # name-free envelope) and fixes the on_read_resource boundary; add it FIRST so
    # it is the OUTERMOST middleware. See notfound_guard.py.
    mcp.add_middleware(NotFoundGuard())
    # Error-handling middleware goes next so it wraps every tool call and can turn
    # pre-body argument-validation failures into a structured envelope.
    mcp.add_middleware(InputValidationMiddleware())

    register_discovery_tools(mcp)
    register_gene_tools(mcp)
    register_disease_tools(mcp)
    register_assertion_tools(mcp)
    register_submitter_tools(mcp)
    register_capability_resources(mcp)

    # Layer 3: install the protocol-handler backstop AFTER every tool/resource/
    # prompt is registered, so it is the outermost wrapper on the raw CallTool/
    # ReadResource/GetPrompt handlers. It catches the unknown-tool *return* path and
    # any resource/prompt dispatch error that would echo the requested name/URI (the
    # only layer covering the unknown-prompt surface).
    install_protocol_error_handler(mcp)
    # Layer 5: scrub FastMCP-core / MCP-SDK validation logs that would echo the
    # caller-supplied name/URI (idempotent; process-global).
    install_notfound_log_filter()

    return mcp
