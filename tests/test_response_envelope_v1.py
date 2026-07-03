"""Locking test for the GeneFoundry Response-Envelope Standard v1.

gencc-link is one of the fleet backends that already conforms to the ratified
standard (docs/RESPONSE-ENVELOPE-STANDARD-v1.md in genefoundry-router):

- SUCCESS: ``{"success": True, <payload>, "_meta": {..., "unsafe_for_clinical_use": True}}``
- FAILURE: a FLAT in-band dict -- ``{"success": False, "error_code": <str>,
  "message": <str>, "retryable": <bool>, "recovery_action": <str>,
  "_meta": {"tool": ..., "unsafe_for_clinical_use": True}}`` -- never a bare
  exception, never a nested ``error: {...}`` object.

This repo does not have a separate ``run_mcp_tool``/``mcp/errors.py`` split;
both the success-``_meta`` builder and the flat error-envelope builder live in
``gencc_link.mcp.envelope``, fronted by the single ``run_mcp_tool`` boundary
that every tool wrapper calls (see ``gencc_link/mcp/tools/*.py``). This test
exercises that real boundary directly -- with a real registered tool name --
so a future change to the wrapper that breaks the flat-banner contract fails
CI instead of silently drifting.

This is a regression lock, not new coverage: ``tests/test_envelope.py``
already covers ``run_mcp_tool`` unit-by-unit. This file asserts the
fleet-standard shape as a single, standard-referencing contract test.
"""

from __future__ import annotations

from typing import Any

from gencc_link.exceptions import NotFoundError
from gencc_link.mcp.envelope import McpErrorContext, run_mcp_tool


class TestSuccessEnvelopeV1:
    """Locks the flat success banner built by ``run_mcp_tool``."""

    async def test_success_envelope_matches_standard(self) -> None:
        async def call() -> dict[str, Any]:
            # Representative payload shape (list-of-results), not asserted by
            # the wrapper itself -- the wrapper only injects success/_meta.
            return {"results": [{"gene_curie": "HGNC:1100"}]}

        out = await run_mcp_tool(
            "search_genes",
            call,
            context=McpErrorContext("search_genes", arguments={"query": "BRCA1"}),
            response_mode="compact",
        )

        assert out["success"] is True
        assert out["results"] == [{"gene_curie": "HGNC:1100"}]
        assert "_meta" in out

        meta = out["_meta"]
        assert meta["unsafe_for_clinical_use"] is True
        # Real guarantees of run_mcp_tool's success path (see envelope.py):
        # observability (request_id/elapsed_ms) and mode-aware citation.
        assert isinstance(meta["request_id"], str)
        assert len(meta["request_id"]) >= 8
        assert isinstance(meta["elapsed_ms"], (int, float))
        assert meta["elapsed_ms"] >= 0
        assert meta["citation_ref"] == "gencc://citation"
        assert meta["citation_short"]
        assert meta["response_mode"] == "compact"
        # Drift note: unlike the error path, the success _meta does NOT carry
        # a "tool" key -- run_mcp_tool only stamps "tool" into error envelopes
        # (see _error_envelope). Ground truth, not a gap in this test.
        assert "tool" not in meta


class TestErrorEnvelopeV1:
    """Locks the flat error banner built by ``run_mcp_tool`` / ``_error_envelope``."""

    async def test_error_envelope_is_flat_not_nested(self) -> None:
        async def call() -> dict[str, Any]:
            raise NotFoundError("gene ZZZ not found")

        out = await run_mcp_tool(
            "get_gene_curations",
            call,
            context=McpErrorContext("get_gene_curations", arguments={"gene": "ZZZ"}),
        )

        assert out["success"] is False
        assert isinstance(out["error_code"], str) and out["error_code"]
        assert out["error_code"] == "not_found"
        assert isinstance(out["message"], str) and out["message"]
        assert isinstance(out["retryable"], bool)
        assert out["retryable"] is False
        assert isinstance(out["recovery_action"], str) and out["recovery_action"]
        assert out["recovery_action"] == "reformulate_input"

        # Flat-banner contract: no bare exception, no nested error object.
        assert "error" not in out

        meta = out["_meta"]
        assert meta["tool"] == "get_gene_curations"
        assert meta["unsafe_for_clinical_use"] is True

    async def test_error_envelope_uses_real_registered_tool_name(self) -> None:
        """Drives the flat error path through a second real tool name to show
        the contract holds independent of which registered tool triggered it.
        """

        async def call() -> dict[str, Any]:
            raise NotFoundError("disease MONDO:9999999 not found")

        out = await run_mcp_tool(
            "get_gene_disease_assertion",
            call,
            context=McpErrorContext(
                "get_gene_disease_assertion", arguments={"gene": "ZZZ", "disease": "MONDO:9999999"}
            ),
        )

        assert out["success"] is False
        assert out["error_code"] == "not_found"
        assert "error" not in out
        assert out["_meta"]["tool"] == "get_gene_disease_assertion"
        assert out["_meta"]["unsafe_for_clinical_use"] is True
