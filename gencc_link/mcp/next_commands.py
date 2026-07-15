"""Builders for _meta.next_commands entries: {tool, arguments} ready-to-call steps.

Every emitted ``next_command`` MUST target its tool by that tool's ACTUAL input
schema. The gene tools take a single polymorphic ``gene_symbol`` (an approved
symbol OR an HGNC CURIE), so resolved HGNC CURIEs are emitted as ``gene_symbol``.
A guard test (tests/test_next_commands.py) validates every affordance against the
live schema so a param the target rejects can never ship again.
"""

from __future__ import annotations

from typing import Any

from gencc_link.mcp.untrusted_content import sanitize_message

_MAX_NEXT_COMMANDS = 5


def cmd(tool: str, **arguments: Any) -> dict[str, Any]:
    """One ready-to-call next step."""
    return {"tool": tool, "arguments": arguments}


def _clean(value: Any) -> str:
    """Strip forbidden code points from a caller-supplied value echoed into an
    error-path recovery command's arguments (a ``next_commands[*].arguments.*``
    field the model may act on)."""
    return sanitize_message(str(value))


def after_search_genes(gene_curies: list[str], query: str = "") -> list[dict[str, Any]]:
    """After resolving genes: pull each gene's curations (capped), or cross to disease search.

    On zero hits the original ``query`` is propagated (a gene miss is often a
    disease term); an empty query yields no suggestion rather than a guaranteed
    ``invalid_input`` from ``search_diseases(query="")``.
    """
    if not gene_curies:
        return [cmd("search_diseases", query=query)] if query else []
    return [cmd("get_gene_curations", gene_symbol=c) for c in gene_curies[:_MAX_NEXT_COMMANDS]]


def after_search_diseases(disease_curies: list[str], query: str = "") -> list[dict[str, Any]]:
    """After resolving diseases: pull each disease's curations (capped), or cross to gene search."""
    if not disease_curies:
        return [cmd("search_genes", query=query)] if query else []
    return [cmd("get_disease_curations", disease=c) for c in disease_curies[:_MAX_NEXT_COMMANDS]]


def after_gene_curations(gene: str, disease_curies: list[str]) -> list[dict[str, Any]]:
    """After a gene's curations: drill into the top disease pair."""
    if not disease_curies:
        return []
    return [cmd("get_gene_disease_assertion", gene_symbol=gene, disease=disease_curies[0])]


def after_disease_curations(disease: str, gene_curies: list[str]) -> list[dict[str, Any]]:
    """After a disease's curations: drill into the top gene pair."""
    if not gene_curies:
        return []
    return [cmd("get_gene_disease_assertion", gene_symbol=gene_curies[0], disease=disease)]


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
                    gene_symbol=gene["gene_curie"],
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
                    gene_symbol=genes[0]["gene_curie"],
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
        cmd("get_gene_curations", gene_symbol=gene),
        cmd("get_disease_curations", disease=disease),
    ]


def recovery_commands(
    tool: str, error_code: str, arguments: dict[str, Any], field: str | None
) -> list[dict[str, Any]]:
    """Ready-to-call recovery steps for an error envelope (empty when none apply).

    Mirrors the success-path ``next_commands`` so an agent can deterministically
    recover from a failure instead of parsing the prose ``recovery_action``.
    """
    gene_raw = arguments.get("gene_symbol")
    gene_in = _clean(gene_raw) if gene_raw else None
    disease_in = _clean(arguments["disease"]) if arguments.get("disease") else None
    query_in = _clean(arguments["query"]) if arguments.get("query") else None
    if error_code == "not_found":
        if tool == "get_gene_curations" and gene_in:
            return [cmd("search_genes", query=gene_in)]
        if tool == "get_disease_curations" and disease_in:
            return [cmd("search_diseases", query=disease_in)]
        if tool == "get_gene_disease_assertion":
            out: list[dict[str, Any]] = []
            if gene_in:
                out.append(cmd("get_gene_curations", gene_symbol=gene_in))
            if disease_in:
                out.append(cmd("get_disease_curations", disease=disease_in))
            return out
        if tool == "resolve_identifier" and query_in:
            return [
                cmd("search_genes", query=query_in),
                cmd("search_diseases", query=query_in),
            ]
    if error_code == "ambiguous_query" and tool == "resolve_identifier" and query_in:
        return [
            cmd("get_gene_curations", gene_symbol=query_in),
            cmd("get_disease_curations", disease=query_in),
        ]
    if error_code == "invalid_input":
        if field == "submitter":
            return [cmd("list_submitters")]
        if field == "cursor":
            return [cmd("get_gencc_diagnostics"), cmd("get_server_capabilities")]
        # classification, moi, response_mode, empty query, >20 batch, bad
        # offset/limit: the authoritative parameter contract is
        # get_server_capabilities. Guarantees every invalid_input envelope is
        # chainable (capabilities promises next_commands on errors).
        return [cmd("get_server_capabilities")]
    return []
