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
from gencc_link.mcp.untrusted_content import UntrustedTextLimitError


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
        assert out["_meta"]["unsafe_for_clinical_use"] is True

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
            (
                UntrustedTextLimitError("too many fenced objects"),
                "untrusted_text_limit_exceeded",
                "reformulate_input",
            ),
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


class TestObservability:
    async def test_meta_has_request_id_and_timing(self) -> None:
        async def body() -> dict[str, Any]:
            return {}

        out = await run_mcp_tool("t", body)
        assert isinstance(out["_meta"]["request_id"], str)
        assert len(out["_meta"]["request_id"]) >= 8
        assert isinstance(out["_meta"]["elapsed_ms"], (int, float))
        assert out["_meta"]["elapsed_ms"] >= 0

    async def test_error_meta_has_request_id_and_timing(self) -> None:
        out = await run_mcp_tool("t", _raiser(NotFoundError("x")))
        assert "request_id" in out["_meta"]
        assert isinstance(out["_meta"]["elapsed_ms"], (int, float))


class TestCitationByMode:
    async def test_compact_uses_citation_ref(self) -> None:
        async def body() -> dict[str, Any]:
            return {}

        out = await run_mcp_tool("t", body, response_mode="compact")
        assert out["_meta"]["citation_ref"] == "gencc://citation"
        assert "recommended_citation" not in out["_meta"]
        assert out["_meta"]["response_mode"] == "compact"

    async def test_minimal_uses_citation_ref(self) -> None:
        async def body() -> dict[str, Any]:
            return {}

        out = await run_mcp_tool("t", body, response_mode="minimal")
        assert out["_meta"]["citation_ref"] == "gencc://citation"

    async def test_standard_uses_citation_ref(self) -> None:
        async def body() -> dict[str, Any]:
            return {}

        out = await run_mcp_tool("t", body, response_mode="standard")
        assert out["_meta"]["citation_ref"] == "gencc://citation"
        assert out["_meta"]["citation_short"]
        assert "recommended_citation" not in out["_meta"]

    async def test_full_uses_full_citation(self) -> None:
        async def body() -> dict[str, Any]:
            return {}

        out = await run_mcp_tool("t", body, response_mode="full")
        assert out["_meta"]["recommended_citation"]
        assert "citation_ref" not in out["_meta"]

    async def test_no_mode_keeps_full_citation(self) -> None:
        async def body() -> dict[str, Any]:
            return {}

        out = await run_mcp_tool("t", body)
        assert out["_meta"]["recommended_citation"]
        assert "response_mode" not in out["_meta"]

    async def test_data_license_only_in_full(self) -> None:
        async def body() -> dict[str, Any]:
            return {}

        full = await run_mcp_tool("t", body, response_mode="full")
        assert full["_meta"]["data_license"] == "CC0-1.0"
        for mode in ("minimal", "compact", "standard"):
            out = await run_mcp_tool("t", body, response_mode=mode)
            assert "data_license" not in out["_meta"]
            assert out["_meta"]["unsafe_for_clinical_use"] is True

    async def test_error_envelope_citation_ref_only(self) -> None:
        out = await run_mcp_tool("t", _raiser(NotFoundError("x")))
        meta = out["_meta"]
        assert meta["citation_ref"] == "gencc://citation"
        assert "recommended_citation" not in meta
        assert "citation_short" not in meta  # an error carries no claim to cite
        assert "data_license" not in meta
        assert meta["unsafe_for_clinical_use"] is True


class TestErrorNextCommands:
    async def test_not_found_recovery(self) -> None:
        out = await run_mcp_tool(
            "get_gene_curations",
            _raiser(NotFoundError("nope")),
            context=McpErrorContext("get_gene_curations", arguments={"gene": "ZZZ"}),
        )
        assert out["_meta"]["next_commands"] == [
            {"tool": "search_genes", "arguments": {"query": "ZZZ"}}
        ]

    async def test_invalid_submitter_recovery(self) -> None:
        out = await run_mcp_tool(
            "find_curations",
            _raiser(InvalidInputError("bad", field="submitter")),
            context=McpErrorContext("find_curations", arguments={}),
        )
        assert out["_meta"]["next_commands"][0]["tool"] == "list_submitters"

    async def test_no_recovery_omits_next_commands(self) -> None:
        out = await run_mcp_tool("t", _raiser(RuntimeError("boom")))
        assert "next_commands" not in out["_meta"]


def _make_validation_error():
    from pydantic import BaseModel, ValidationError

    class _M(BaseModel):
        response_mode: str

    try:
        _M(response_mode=["not", "a", "str"])  # type: ignore[arg-type]
    except ValidationError as exc:
        return exc
    raise AssertionError("expected ValidationError")


def test_validation_error_envelope_shape() -> None:
    from gencc_link.mcp.envelope import validation_error_envelope

    env = validation_error_envelope(
        tool_name="get_gene_disease_assertion",
        arguments={"response_mode": "ultra"},
        exc=_make_validation_error(),
    )
    assert env["success"] is False
    assert env["error_code"] == "invalid_input"
    assert env["retryable"] is False
    assert env["recovery_action"] == "reformulate_input"
    assert env["field_errors"]
    assert env["_meta"]["tool"] == "get_gene_disease_assertion"
    assert env["_meta"]["next_commands"]
    assert isinstance(env["_meta"]["request_id"], str)
    assert "elapsed_ms" in env["_meta"]
