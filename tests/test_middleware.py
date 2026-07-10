"""Tests for MCP middleware compatibility boundaries."""

from __future__ import annotations

from typing import Any

import pytest
from fastmcp.exceptions import ValidationError as FastMCPValidationError
from fastmcp.server.middleware import MiddlewareContext
from mcp.types import CallToolRequestParams

from gencc_link.mcp.middleware import InputValidationMiddleware


@pytest.mark.parametrize("cause", [None, RuntimeError("unrelated")])
async def test_fastmcp_validation_without_pydantic_cause_propagates(
    cause: BaseException | None,
) -> None:
    error = FastMCPValidationError("framework validation failed")
    if cause is not None:
        try:
            raise error from cause
        except FastMCPValidationError as chained:
            error = chained

    context = MiddlewareContext(
        message=CallToolRequestParams(name="search_genes", arguments={}),
        method="tools/call",
    )

    async def call_next(_: MiddlewareContext[Any]) -> Any:
        raise error

    with pytest.raises(FastMCPValidationError, match="framework validation failed"):
        await InputValidationMiddleware().on_call_tool(context, call_next)
