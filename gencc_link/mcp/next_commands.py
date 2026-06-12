"""Builders for _meta.next_commands entries: {tool, arguments} ready-to-call steps."""

from __future__ import annotations

from typing import Any


_MAX_NEXT_COMMANDS = 5


def cmd(tool: str, **arguments: Any) -> dict[str, Any]:
    """One ready-to-call next step."""
    return {"tool": tool, "arguments": arguments}


def after_search_genes(gene_curies: list[str], query: str = "") -> list[dict[str, Any]]:
    """After resolving genes: pull each gene's curations (capped), or cross to disease search.

    On zero hits the original ``query`` is propagated (a gene miss is often a
    disease term); an empty query yields no suggestion rather than a guaranteed
    ``invalid_input`` from ``search_diseases(query="")``.
    """
    if not gene_curies:
        return [cmd("search_diseases", query=query)] if query else []
    return [cmd("get_gene_curations", gene=c) for c in gene_curies[:_MAX_NEXT_COMMANDS]]


def after_search_diseases(disease_curies: list[str], query: str = "") -> list[dict[str, Any]]:
    """After resolving diseases: pull each disease's curations (capped), or cross to gene search."""
    if not disease_curies:
        return [cmd("search_genes", query=query)] if query else []
    return [cmd("get_disease_curations", disease=c) for c in disease_curies[:_MAX_NEXT_COMMANDS]]


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


def after_genes_curations(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Drill into each resolved gene's top disease (capped); append unresolved recovery.

    Resolved follow-ups come first; the unresolved-recovery hint is an addition,
    not the only entry (a slot is reserved for it so it is never crowded out).
    """
    unresolved = payload.get("unresolved") or []
    cap = _MAX_NEXT_COMMANDS - 1 if unresolved else _MAX_NEXT_COMMANDS
    nexts: list[dict[str, Any]] = []
    for block in payload.get("results") or []:
        gene = block.get("gene") or {}
        diseases = block.get("diseases") or []
        if gene.get("gene_curie") and diseases:
            nexts.append(
                cmd(
                    "get_gene_disease_assertion",
                    gene=gene["gene_curie"],
                    disease=diseases[0]["disease_curie"],
                )
            )
        if len(nexts) >= cap:
            break
    if unresolved:
        nexts.append(cmd("search_genes", query=unresolved[0]["input"]))
    return nexts


def after_diseases_curations(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Drill into each resolved disease's top gene (capped); append unresolved recovery."""
    unresolved = payload.get("unresolved") or []
    cap = _MAX_NEXT_COMMANDS - 1 if unresolved else _MAX_NEXT_COMMANDS
    nexts: list[dict[str, Any]] = []
    for block in payload.get("results") or []:
        disease = block.get("disease") or {}
        genes = block.get("genes") or []
        if disease.get("disease_curie") and genes:
            nexts.append(
                cmd(
                    "get_gene_disease_assertion",
                    gene=genes[0]["gene_curie"],
                    disease=disease["disease_curie"],
                )
            )
        if len(nexts) >= cap:
            break
    if unresolved:
        nexts.append(cmd("search_diseases", query=unresolved[0]["input"]))
    return nexts


def after_assertion(gene: str, disease: str) -> list[dict[str, Any]]:
    """After a gene-disease assertion: widen to the gene's other diseases."""
    return [
        cmd("get_gene_curations", gene=gene),
        cmd("get_disease_curations", disease=disease),
    ]


def recovery_commands(
    tool: str, error_code: str, arguments: dict[str, Any], field: str | None
) -> list[dict[str, Any]]:
    """Ready-to-call recovery steps for an error envelope (empty when none apply).

    Mirrors the success-path ``next_commands`` so an agent can deterministically
    recover from a failure instead of parsing the prose ``recovery_action``.
    """
    if error_code == "not_found":
        if tool == "get_gene_curations" and arguments.get("gene"):
            return [cmd("search_genes", query=arguments["gene"])]
        if tool == "get_disease_curations" and arguments.get("disease"):
            return [cmd("search_diseases", query=arguments["disease"])]
        if tool == "get_gene_disease_assertion":
            out: list[dict[str, Any]] = []
            if arguments.get("gene"):
                out.append(cmd("get_gene_curations", gene=arguments["gene"]))
            if arguments.get("disease"):
                out.append(cmd("get_disease_curations", disease=arguments["disease"]))
            return out
        if tool == "resolve_identifier" and arguments.get("query"):
            return [
                cmd("search_genes", query=arguments["query"]),
                cmd("search_diseases", query=arguments["query"]),
            ]
    if error_code == "ambiguous_query" and tool == "resolve_identifier" and arguments.get("query"):
        return [
            cmd("get_gene_curations", gene=arguments["query"]),
            cmd("get_disease_curations", disease=arguments["query"]),
        ]
    if error_code == "invalid_input":
        if field == "submitter":
            return [cmd("list_submitters")]
        if field in ("classification", "moi"):
            return [cmd("get_server_capabilities")]
    if error_code == "data_unavailable":
        return [cmd("get_gencc_diagnostics")]
    return []
