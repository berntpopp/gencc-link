"""Tests for next_commands builders (gencc_link.mcp.next_commands)."""

from __future__ import annotations

from gencc_link.mcp import next_commands as nc


class TestCmd:
    def test_shape(self) -> None:
        out = nc.cmd("search_genes", query="SKI")
        assert out == {"tool": "search_genes", "arguments": {"query": "SKI"}}


class TestAfterSearchGenes:
    def test_with_hits(self) -> None:
        out = nc.after_search_genes(["HGNC:1"])
        assert out == [{"tool": "get_gene_curations", "arguments": {"gene": "HGNC:1"}}]

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
        out = nc.after_gene_curations("SKI", ["MONDO:1"])
        assert out == [
            {
                "tool": "get_gene_disease_assertion",
                "arguments": {"gene": "SKI", "disease": "MONDO:1"},
            }
        ]

    def test_empty(self) -> None:
        assert nc.after_gene_curations("SKI", []) == []


class TestAfterDiseaseCurations:
    def test_with_genes(self) -> None:
        out = nc.after_disease_curations("MONDO:1", ["HGNC:1"])
        assert out[0]["arguments"] == {"gene": "HGNC:1", "disease": "MONDO:1"}

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


class TestRecoveryCommands:
    def test_not_found_gene_curations(self) -> None:
        out = nc.recovery_commands("get_gene_curations", "not_found", {"gene": "ZZZ"}, None)
        assert out == [{"tool": "search_genes", "arguments": {"query": "ZZZ"}}]

    def test_not_found_disease_curations(self) -> None:
        out = nc.recovery_commands(
            "get_disease_curations", "not_found", {"disease": "MONDO:9"}, None
        )
        assert out == [{"tool": "search_diseases", "arguments": {"query": "MONDO:9"}}]

    def test_not_found_assertion_two_steps(self) -> None:
        out = nc.recovery_commands(
            "get_gene_disease_assertion", "not_found", {"gene": "SKI", "disease": "MONDO:1"}, None
        )
        assert {c["tool"] for c in out} == {"get_gene_curations", "get_disease_curations"}

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

    def test_invalid_no_field_returns_empty(self) -> None:
        assert nc.recovery_commands("search_genes", "invalid_input", {}, None) == []
