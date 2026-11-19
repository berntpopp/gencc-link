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


async def test_arg_error_logs_field_names_not_values(caplog: pytest.LogCaptureFixture) -> None:
    """#130: an argument error is diagnosable from logs without the caller's value."""
    from pydantic import BaseModel, ValidationError

    class _Args(BaseModel, extra="forbid"):
        limit: int

    try:
        _Args.model_validate({"limit": "SECRET-VALUE", "SECRET_KEY": 1})
    except ValidationError as exc:
        pyd = exc
    context = MiddlewareContext(
        message=CallToolRequestParams(name="search_genes", arguments={"limit": "SECRET-VALUE"}),
        method="tools/call",
    )

    async def call_next(_: MiddlewareContext[Any]) -> Any:
        raise FastMCPValidationError("bad") from pyd

    with caplog.at_level("WARNING", logger="gencc_link.mcp.middleware"):
        await InputValidationMiddleware().on_call_tool(context, call_next)
    (msg,) = [r.getMessage() for r in caplog.records if "mcp_arg_error" in r.getMessage()]
    assert msg == (
        "mcp_arg_error tool=search_genes fields=limit,argument types=extra_forbidden,int_parsing"
    )
    assert "SECRET" not in msg
