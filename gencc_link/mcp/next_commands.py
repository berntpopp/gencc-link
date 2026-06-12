"""Builders for _meta.next_commands entries: {tool, arguments} ready-to-call steps."""

from __future__ import annotations

from typing import Any


def cmd(tool: str, **arguments: Any) -> dict[str, Any]:
    """One ready-to-call next step."""
    return {"tool": tool, "arguments": arguments}


def after_search_genes(gene_curies: list[str]) -> list[dict[str, Any]]:
    """After resolving genes: pull the gene's curations."""
    if not gene_curies:
        return [cmd("search_diseases", query="")]
    return [cmd("get_gene_curations", gene=gene_curies[0])]


def after_search_diseases(disease_curies: list[str]) -> list[dict[str, Any]]:
    """After resolving diseases: pull the disease's curations."""
    if not disease_curies:
        return [cmd("search_genes", query="")]
    return [cmd("get_disease_curations", disease=disease_curies[0])]


def after_gene_curations(gene: str, disease_curies: list[str]) -> list[dict[str, Any]]:
    """After a gene's curations: drill into the top disease pair."""
    if not disease_curies:
        return []
    return [cmd("get_gene_disease_assertion", gene=gene, disease=disease_curies[0])]


def after_disease_curations(disease: str, gene_curies: list[str]) -> list[dict[str, Any]]:
    """After a disease's curations: drill into the top gene pair."""
    if not gene_curies:
        return []
    return [cmd("get_gene_disease_assertion", gene=gene_curies[0], disease=disease)]


def after_assertion(gene: str, disease: str) -> list[dict[str, Any]]:
    """After a gene-disease assertion: widen to the gene's other diseases."""
    return [
        cmd("get_gene_curations", gene=gene),
        cmd("get_disease_curations", disease=disease),
    ]
