"""Builders for _meta.next_commands entries: {tool, arguments} ready-to-call steps.

Every emitted ``next_command`` MUST target its tool by that tool's ACTUAL input
schema. The gene tools take a single polymorphic ``gene_symbol`` (an approved
symbol OR an HGNC CURIE), so resolved HGNC CURIEs are emitted as ``gene_symbol``.
A guard test (tests/test_next_commands.py) validates every affordance against the
live schema so a param the target rejects can never ship again.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from gencc_link.mcp.untrusted_content import sanitize_message
from gencc_link.services.gene_ids import foreign_gene_converter

_MAX_NEXT_COMMANDS = 5

# GTS-CORE-TXT-04: a caller value is forwarded into another tool's step only after it
# passes the strict identifier shape for its kind; free text never is.
_GENE_ID = re.compile(r"HGNC:\d+|[A-Za-z0-9][A-Za-z0-9-]{0,29}", re.IGNORECASE)
_DISEASE_ID = re.compile(r"(?:MONDO|OMIM|Orphanet|ORPHA):\d+", re.IGNORECASE)
_MONDO_ID = re.compile(r"MONDO:\d+", re.IGNORECASE)


def _ok(pattern: re.Pattern[str], value: Any) -> bool:
    return isinstance(value, str) and pattern.fullmatch(value.strip()) is not None


def safe_echo(value: Any) -> bool:
    """True if a caller string may be repeated in a page step of the same call
    (GTS-CORE-TXT-04): at most 200 characters, no control/format code points (Cc/Cf)."""
    text = str(value)
    return len(text) <= 200 and not any(unicodedata.category(c) in ("Cc", "Cf") for c in text)


def cmd(tool: str, **arguments: Any) -> dict[str, Any]:
    """One ready-to-call next step."""
    return {"tool": tool, "arguments": arguments}


def _clean(value: Any) -> str:
    """Strip forbidden code points from a caller-supplied value echoed into an
    error-path recovery command's arguments (a ``next_commands[*].arguments.*``
    field the model may act on)."""
    return sanitize_message(str(value))


def after_search_genes(gene_curies: list[str], query: str = "") -> list[dict[str, Any]]:
    """After resolving genes: pull each gene's curations (capped), or a fixed discovery step.

    A no-hit free-text query is never forwarded (GTS-CORE-TXT-04).
    """
    if not gene_curies:
        return [cmd("get_server_capabilities")] if query else []
    return [cmd("get_gene_curations", gene_symbol=c) for c in gene_curies[:_MAX_NEXT_COMMANDS]]


def after_search_diseases(disease_curies: list[str], query: str = "") -> list[dict[str, Any]]:
    """After resolving diseases: pull each disease's curations (capped), or cross to gene search."""
    if not disease_curies:  # never forward a no-hit query (GTS-CORE-TXT-04)
        return [cmd("get_server_capabilities")] if query else []
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
    unsupported = payload.get("unsupported") or []
    cap = _MAX_NEXT_COMMANDS - bool(unresolved) - bool(unsupported)
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
        miss = unresolved[0]["input"]
        nexts.append(
            cmd("search_genes", query=miss)
            if _ok(_GENE_ID, miss)
            else cmd("get_server_capabilities")
        )
    if unsupported and (converter := foreign_gene_converter(unsupported[0]["input"])):
        nexts.append(converter)
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
        miss = unresolved[0]["input"]
        nexts.append(
            cmd("search_diseases", query=miss)
            if _ok(_DISEASE_ID, miss)
            else cmd("get_server_capabilities")
        )
    return nexts


def after_assertion(gene: str, disease: str) -> list[dict[str, Any]]:
    """After a gene-disease assertion: widen to the gene's other diseases."""
    return [
        cmd("get_gene_curations", gene_symbol=gene),
        cmd("get_disease_curations", disease=disease),
    ]


def recovery_commands(
    tool: str,
    error_code: str,
    arguments: dict[str, Any],
    field: str | None,
    candidates: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Ready-to-call recovery steps for an error envelope (empty when none apply).

    Mirrors the success-path ``next_commands`` so an agent can deterministically
    recover from a failure instead of parsing the prose ``recovery_action``.
    """
    # GTS-CORE-TXT-04: only values that pass a strict identifier shape are forwarded.
    gene_raw = arguments.get("gene_symbol")
    gene_in = _clean(gene_raw).strip() if _ok(_GENE_ID, gene_raw) else None
    disease_raw = arguments.get("disease")
    disease_in = _clean(disease_raw).strip() if _ok(_DISEASE_ID, disease_raw) else None
    query_raw = arguments.get("query")
    query_in = _clean(query_raw).strip() if query_raw else None
    if error_code == "not_found":
        out: list[dict[str, Any]] = []
        if tool == "get_gene_curations" and gene_in:
            out.append(cmd("search_genes", query=gene_in))
        if tool == "get_disease_curations" and disease_in:
            out.append(cmd("search_diseases", query=disease_in))
            if _MONDO_ID.fullmatch(disease_in):
                # A grouping MONDO term: GenCC curates its children, not the term itself.
                out.append(cmd("mondo_get_disease_descendants", term=disease_in))
        if tool == "get_gene_disease_assertion":
            if gene_in:
                out.append(cmd("get_gene_curations", gene_symbol=gene_in))
            if disease_in:
                out.append(cmd("get_disease_curations", disease=disease_in))
        if tool == "resolve_identifier" and query_in:
            kind = arguments.get("kind", "auto")
            # Section 2a: get_* on the top candidates first, then search, then Mondo.
            out = [
                cmd("get_gene_curations", gene_symbol=c["id"])
                if c["kind"] == "gene"
                else cmd("get_disease_curations", disease=c["id"])
                for c in (candidates or [])[:2]
            ]
            # The free-text query is forwarded only in a validated identifier shape.
            if kind != "disease" and _ok(_GENE_ID, query_in):
                out.append(cmd("search_genes", query=query_in))
            if kind != "gene" and _ok(_DISEASE_ID, query_in):
                out.append(cmd("search_diseases", query=query_in))
            if kind != "gene" and _MONDO_ID.fullmatch(query_in):
                out.append(cmd("mondo_get_disease_descendants", term=query_in))
        return out or [cmd("get_server_capabilities")]
    if error_code == "ambiguous_query" and tool == "resolve_identifier" and _ok(_GENE_ID, query_in):
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
