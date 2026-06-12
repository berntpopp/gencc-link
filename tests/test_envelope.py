"""Tests for the MCP envelope boundary (gencc_link.mcp.envelope)."""

from __future__ import annotations

from typing import Any

import pytest

from gencc_link.exceptions import (
    AmbiguousQueryError,
    DataUnavailableError,
    DownloadError,
    InvalidInputError,
    NotFoundError,
    QuotaExceededError,
)
from gencc_link.mcp.envelope import (
    McpErrorContext,
    McpToolError,
    run_mcp_tool,
    set_data_release,
)


def _raiser(exc: Exception):
    async def body() -> dict[str, Any]:
        raise exc

    return body


class TestHappyPath:
    async def test_injects_success_and_meta(self) -> None:
        async def body() -> dict[str, Any]:
            return {"value": 42}

        out = await run_mcp_tool("t", body)
        assert out["success"] is True
        assert out["value"] == 42
        assert "_meta" in out
        assert out["_meta"]["recommended_citation"]
        assert out["_meta"]["unsafe_for_clinical_use"] is True

    async def test_preserves_existing_meta(self) -> None:
        async def body() -> dict[str, Any]:
            return {"_meta": {"next_commands": [{"tool": "x", "arguments": {}}]}}

        out = await run_mcp_tool("t", body)
        assert out["_meta"]["next_commands"]
        assert out["_meta"]["data_license"]

    async def test_does_not_overwrite_explicit_success(self) -> None:
        async def body() -> dict[str, Any]:
            return {"success": False, "custom": 1}

        out = await run_mcp_tool("t", body)
        assert out["success"] is False


class TestErrorClassification:
    @pytest.mark.parametrize(
        ("exc", "code", "recovery"),
        [
            (NotFoundError("nope"), "not_found", "reformulate_input"),
            (AmbiguousQueryError("amb"), "ambiguous_query", "reformulate_input"),
            (DataUnavailableError("no db"), "data_unavailable", "build_database"),
            (QuotaExceededError("quota"), "rate_limited", "retry_backoff"),
            (DownloadError("net"), "upstream_unavailable", "retry_backoff"),
            (RuntimeError("boom"), "internal_error", "switch_tool"),
        ],
    )
    async def test_codes(self, exc: Exception, code: str, recovery: str) -> None:
        out = await run_mcp_tool("t", _raiser(exc), context=McpErrorContext("t"))
        assert out["success"] is False
        assert out["error_code"] == code
        assert out["recovery_action"] == recovery
        assert out["_meta"]["tool"] == "t"

    async def test_invalid_input_with_field_errors(self) -> None:
        out = await run_mcp_tool("t", _raiser(InvalidInputError("bad", field="query")))
        assert out["error_code"] == "invalid_input"
        assert out["field_errors"] == [{"field": "query", "reason": "bad"}]

    async def test_invalid_input_without_field(self) -> None:
        out = await run_mcp_tool("t", _raiser(InvalidInputError("bad")))
        assert out["error_code"] == "invalid_input"
        assert "field_errors" not in out

    async def test_retryable_flags(self) -> None:
        out = await run_mcp_tool("t", _raiser(QuotaExceededError("q")))
        assert out["retryable"] is True
        out2 = await run_mcp_tool("t", _raiser(NotFoundError("n")))
        assert out2["retryable"] is False

    async def test_pydantic_validation_error(self) -> None:
        from pydantic import BaseModel

        class M(BaseModel):
            x: int

        async def body() -> dict[str, Any]:
            M(x="not-an-int")  # type: ignore[arg-type]
            return {}

        out = await run_mcp_tool("t", body)
        assert out["error_code"] == "invalid_input"
        assert out["field_errors"]


class TestMcpToolError:
    async def test_custom_error_code(self) -> None:
        out = await run_mcp_tool(
            "t", _raiser(McpToolError(error_code="custom_code", message="msg"))
        )
        assert out["error_code"] == "custom_code"
        assert out["message"] == "msg"

    async def test_custom_retryable_codes(self) -> None:
        out = await run_mcp_tool("t", _raiser(McpToolError(error_code="rate_limited", message="m")))
        assert out["retryable"] is True


class TestSetDataRelease:
    async def test_adds_gencc_release_to_meta(self) -> None:
        try:
            set_data_release("2024-11-01")

            async def body() -> dict[str, Any]:
                return {}

            out = await run_mcp_tool("t", body)
            assert out["_meta"]["gencc_release"] == "2024-11-01"
        finally:
            set_data_release(None)

    async def test_none_release_omits_key(self) -> None:
        set_data_release(None)

        async def body() -> dict[str, Any]:
            return {}

        out = await run_mcp_tool("t", body)
        assert "gencc_release" not in out["_meta"]
