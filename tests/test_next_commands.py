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

    def test_empty(self) -> None:
        out = nc.after_search_genes([])
        assert out[0]["tool"] == "search_diseases"


class TestAfterSearchDiseases:
    def test_with_hits(self) -> None:
        out = nc.after_search_diseases(["MONDO:1"])
        assert out[0]["tool"] == "get_disease_curations"
        assert out[0]["arguments"]["disease"] == "MONDO:1"

    def test_empty(self) -> None:
        out = nc.after_search_diseases([])
        assert out[0]["tool"] == "search_genes"


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
