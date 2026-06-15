"""Tests for next_commands builders (gencc_link.mcp.next_commands)."""

from __future__ import annotations

import pytest

from gencc_link.mcp import next_commands as nc


class TestCmd:
    def test_shape(self) -> None:
        out = nc.cmd("search_genes", query="SKI")
        assert out == {"tool": "search_genes", "arguments": {"query": "SKI"}}


class TestGeneKwargs:
    def test_hgnc_curie_maps_to_hgnc_id(self) -> None:
        assert nc.gene_kwargs("HGNC:10896") == {"hgnc_id": "HGNC:10896"}
        assert nc.gene_kwargs("hgnc:1") == {"hgnc_id": "hgnc:1"}

    def test_symbol_maps_to_gene_symbol(self) -> None:
        assert nc.gene_kwargs("SKI") == {"gene_symbol": "SKI"}


class TestAfterSearchGenes:
    def test_with_hits(self) -> None:
        out = nc.after_search_genes(["HGNC:1"])
        assert out == [{"tool": "get_gene_curations", "arguments": {"hgnc_id": "HGNC:1"}}]

    def test_empty_with_query_crosses_over(self) -> None:
        out = nc.after_search_genes([], "ZZZX")
        assert out == [{"tool": "search_diseases", "arguments": {"query": "ZZZX"}}]

    def test_empty_without_query_is_empty(self) -> None:
        assert nc.after_search_genes([]) == []


class TestAfterSearchDiseases:
    def test_with_hits(self) -> None:
        out = nc.after_search_diseases(["MONDO:1"])
        assert out[0]["tool"] == "get_disease_curations"
        assert out[0]["arguments"]["disease"] == "MONDO:1"

    def test_empty_with_query_crosses_over(self) -> None:
        out = nc.after_search_diseases([], "ZZZX")
        assert out == [{"tool": "search_genes", "arguments": {"query": "ZZZX"}}]

    def test_empty_without_query_is_empty(self) -> None:
        assert nc.after_search_diseases([]) == []


class TestAfterGeneCurations:
    def test_with_diseases(self) -> None:
        # Builders receive a resolved gene_curie, so they emit the canonical hgnc_id.
        out = nc.after_gene_curations("HGNC:2222", ["MONDO:1"])
        assert out == [
            {
                "tool": "get_gene_disease_assertion",
                "arguments": {"hgnc_id": "HGNC:2222", "disease": "MONDO:1"},
            }
        ]

    def test_empty(self) -> None:
        assert nc.after_gene_curations("SKI", []) == []


class TestAfterDiseaseCurations:
    def test_with_genes(self) -> None:
        out = nc.after_disease_curations("MONDO:1", ["HGNC:1"])
        assert out[0]["arguments"] == {"hgnc_id": "HGNC:1", "disease": "MONDO:1"}

    def test_empty(self) -> None:
        assert nc.after_disease_curations("MONDO:1", []) == []


class TestAfterAssertion:
    def test_two_steps(self) -> None:
        out = nc.after_assertion("SKI", "MONDO:1")
        assert len(out) == 2
        assert out[0]["tool"] == "get_gene_curations"
        assert out[1]["tool"] == "get_disease_curations"
        for entry in out:
            assert set(entry.keys()) == {"tool", "arguments"}


class TestFanOut:
    def test_after_search_genes_fans_out_capped(self) -> None:
        curies = [f"HGNC:{i}" for i in range(8)]
        cmds = nc.after_search_genes(curies, "x")
        assert [c["tool"] for c in cmds] == ["get_gene_curations"] * nc._MAX_NEXT_COMMANDS
        assert cmds[0]["arguments"]["hgnc_id"] == "HGNC:0"

    def test_after_search_diseases_fans_out_capped(self) -> None:
        curies = [f"MONDO:{i}" for i in range(8)]
        cmds = nc.after_search_diseases(curies, "x")
        assert [c["tool"] for c in cmds] == ["get_disease_curations"] * nc._MAX_NEXT_COMMANDS

    def test_after_genes_curations_drilldown_plus_unresolved(self) -> None:
        payload = {
            "results": [
                {"gene": {"gene_curie": "HGNC:1"}, "diseases": [{"disease_curie": "MONDO:1"}]},
                {"gene": {"gene_curie": "HGNC:2"}, "diseases": [{"disease_curie": "MONDO:2"}]},
            ],
            "unresolved": [{"input": "NOTAGENE", "reason": "not_found"}],
        }
        cmds = nc.after_genes_curations(payload)
        tools = [c["tool"] for c in cmds]
        assert tools.count("get_gene_disease_assertion") == 2
        assert {"tool": "search_genes", "arguments": {"query": "NOTAGENE"}} in cmds
        assert len(cmds) <= nc._MAX_NEXT_COMMANDS

    def test_after_diseases_curations_drilldown_plus_unresolved(self) -> None:
        payload = {
            "results": [
                {"disease": {"disease_curie": "MONDO:1"}, "genes": [{"gene_curie": "HGNC:1"}]},
            ],
            "unresolved": [{"input": "NODISEASE", "reason": "not_found"}],
        }
        cmds = nc.after_diseases_curations(payload)
        assert any(c["tool"] == "get_gene_disease_assertion" for c in cmds)
        assert {"tool": "search_diseases", "arguments": {"query": "NODISEASE"}} in cmds

    def test_after_genes_curations_no_unresolved_uses_full_cap(self) -> None:
        payload = {
            "results": [
                {"gene": {"gene_curie": f"HGNC:{i}"}, "diseases": [{"disease_curie": f"MONDO:{i}"}]}
                for i in range(8)
            ]
        }
        cmds = nc.after_genes_curations(payload)
        assert len(cmds) == nc._MAX_NEXT_COMMANDS


class TestRecoveryCommands:
    def test_not_found_gene_curations(self) -> None:
        out = nc.recovery_commands(
            "get_gene_curations", "not_found", {"gene_symbol": "ZZZ", "hgnc_id": None}, None
        )
        assert out == [{"tool": "search_genes", "arguments": {"query": "ZZZ"}}]

    def test_not_found_gene_curations_by_hgnc_id(self) -> None:
        out = nc.recovery_commands(
            "get_gene_curations", "not_found", {"gene_symbol": None, "hgnc_id": "HGNC:9"}, None
        )
        assert out == [{"tool": "search_genes", "arguments": {"query": "HGNC:9"}}]

    def test_not_found_disease_curations(self) -> None:
        out = nc.recovery_commands(
            "get_disease_curations", "not_found", {"disease": "MONDO:9"}, None
        )
        assert out == [{"tool": "search_diseases", "arguments": {"query": "MONDO:9"}}]

    def test_not_found_assertion_two_steps(self) -> None:
        out = nc.recovery_commands(
            "get_gene_disease_assertion",
            "not_found",
            {"gene_symbol": "SKI", "hgnc_id": None, "disease": "MONDO:1"},
            None,
        )
        assert {c["tool"] for c in out} == {"get_gene_curations", "get_disease_curations"}
        gene_cmd = next(c for c in out if c["tool"] == "get_gene_curations")
        assert gene_cmd["arguments"] == {"gene_symbol": "SKI"}

    def test_not_found_resolve_identifier(self) -> None:
        out = nc.recovery_commands("resolve_identifier", "not_found", {"query": "foo"}, None)
        assert {c["tool"] for c in out} == {"search_genes", "search_diseases"}

    def test_invalid_submitter_points_to_list(self) -> None:
        out = nc.recovery_commands("find_curations", "invalid_input", {}, "submitter")
        assert out == [{"tool": "list_submitters", "arguments": {}}]

    def test_invalid_classification_points_to_capabilities(self) -> None:
        out = nc.recovery_commands("find_curations", "invalid_input", {}, "classification")
        assert out[0]["tool"] == "get_server_capabilities"

    def test_invalid_moi_points_to_capabilities(self) -> None:
        out = nc.recovery_commands("find_curations", "invalid_input", {}, "moi")
        assert out[0]["tool"] == "get_server_capabilities"

    def test_data_unavailable(self) -> None:
        out = nc.recovery_commands("get_gene_curations", "data_unavailable", {}, None)
        assert out[0]["tool"] == "get_gencc_diagnostics"

    def test_unknown_returns_empty(self) -> None:
        assert nc.recovery_commands("list_submitters", "internal_error", {}, None) == []

    def test_invalid_no_field_points_to_capabilities(self) -> None:
        # D2b: every invalid_input is chainable, even with no specific field.
        out = nc.recovery_commands("search_genes", "invalid_input", {}, None)
        assert out == [{"tool": "get_server_capabilities", "arguments": {}}]

    @pytest.mark.parametrize(
        "tool, field",
        [
            ("search_genes", "query"),
            ("get_genes_curations", "genes"),
            ("get_diseases_curations", "diseases"),
            ("find_curations", None),
            ("find_curations", "offset"),
            ("get_gene_disease_assertion", "response_mode"),
        ],
    )
    def test_invalid_input_always_has_recovery(self, tool: str, field: str | None) -> None:
        assert nc.recovery_commands(tool, "invalid_input", {}, field), f"{tool}/{field} bare"

    def test_cursor_drift_routes_to_diagnostics(self) -> None:
        out = nc.recovery_commands("find_curations", "invalid_input", {}, "cursor")
        assert out[0]["tool"] == "get_gencc_diagnostics"

    def test_ambiguous_query_resolve(self) -> None:
        out = nc.recovery_commands(
            "resolve_identifier", "ambiguous_query", {"query": "AMBIG"}, None
        )
        assert [c["tool"] for c in out] == ["get_gene_curations", "get_disease_curations"]
