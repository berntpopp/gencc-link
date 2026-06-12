"""Capabilities discovery surface for GenCC-Link (parity with sibling -link servers)."""

from __future__ import annotations

import functools
import hashlib
import json
from importlib.metadata import PackageNotFoundError, version
from typing import TYPE_CHECKING, Any

from gencc_link.constants import (
    CLASSIFICATION_ORDER,
    CLASSIFICATION_RANKS,
    DATA_LICENSE,
    RECOMMENDED_CITATION,
)
from gencc_link.mcp.resources import (
    GENCC_LICENSE_NOTE,
    GENCC_REFERENCE_NOTES,
    GENCC_USAGE_NOTES,
    RESEARCH_USE_NOTICE,
)
from gencc_link.models.enums import RESPONSE_MODES

if TYPE_CHECKING:
    from fastmcp import FastMCP

TOOLS: tuple[str, ...] = (
    "get_server_capabilities",
    "get_gencc_diagnostics",
    "search_genes",
    "search_diseases",
    "get_gene_curations",
    "get_disease_curations",
    "get_genes_curations",
    "get_diseases_curations",
    "get_gene_disease_assertion",
    "find_curations",
    "list_submitters",
    "resolve_identifier",
)


def _server_version() -> str:
    try:
        return version("gencc-link")
    except PackageNotFoundError:
        return "0.0.0"


@functools.cache
def _static_surface() -> dict[str, Any]:
    surface: dict[str, Any] = {
        "server": "gencc-link",
        "server_version": _server_version(),
        "mcp_protocol_version": "2025-11-25",
        "data_source": "Gene Curation Coalition (GenCC) submissions export, new format",
        "research_use_only": True,
        "data_license": DATA_LICENSE,
        "tools": list(TOOLS),
        "classifications": [
            {"title": title, "rank": CLASSIFICATION_RANKS[title]} for title in CLASSIFICATION_ORDER
        ],
        "response_modes": {
            "minimal": "ids + headline + counts only",
            "compact": "default; consensus + summary lists, no per-submitter detail",
            "standard": "adds per-submitter classification, MOI, dates, report URLs",
            "full": "adds submitter curies, criteria URLs, PMIDs, and raw submission rows",
        },
        "recommended_workflows": [
            "gene symbol -> search_genes -> get_gene_curations -> get_gene_disease_assertion",
            "disease text -> search_diseases -> get_disease_curations",
            "Definitive AD genes from ClinGen -> find_curations(classification=['Definitive'], "
            "moi='Autosomal dominant', submitter=['ClinGen'])",
            "multiple genes at once -> get_genes_curations(genes=['BRCA2','NAA10']); "
            "multiple diseases -> get_diseases_curations(diseases=[...])",
        ],
        "parameter_conventions": {
            "gene": "HGNC CURIE (HGNC:10896) or approved symbol (SKI); resolved exactly",
            "disease": "MONDO CURIE (MONDO:0008426), OMIM CURIE, or harmonized title",
            "genes": "list of gene symbols or HGNC ids (max 20); batch form of `gene`",
            "diseases": "list of disease ids or titles (max 20); batch form of `disease`",
            "classification": "one or more of the classification titles (see `classifications`)",
            "submitter": "submitter title (e.g. ClinGen) or GenCC submitter CURIE; "
            "validated against the live roster (see list_submitters)",
            "moi": "mode-of-inheritance title; data-derived and validated "
            "(see inheritance_modes). Out-of-vocabulary values return invalid_input.",
            "response_mode": "minimal | compact | standard | full (default compact)",
        },
        "error_codes": [
            "invalid_input",
            "not_found",
            "ambiguous_query",
            "data_unavailable",
            "upstream_unavailable",
            "rate_limited",
            "internal_error",
        ],
        "token_cost_hints": {
            "search_genes": "~1-3kB",
            "get_gene_curations": "compact ~2-5kB; full larger with per-submitter rows",
            "get_genes_curations": "~2-5kB per resolved gene (compact); scales with the list",
            "get_diseases_curations": "~2-5kB per resolved disease (compact); scales with the list",
            "get_gene_disease_assertion": "standard ~2-4kB; full adds raw submissions",
            "get_server_capabilities": "<4kB",
        },
        "response_fields": {
            "headline": "one-line plain-English answer at the top of each payload",
            "next_commands": "_meta.next_commands: ready-to-call {tool, arguments} next steps "
            "(on success AND error envelopes)",
            "recommended_citation": "_meta.recommended_citation: paste verbatim "
            "(standard/full); minimal/compact emit _meta.citation_ref instead",
            "citation_ref": "_meta.citation_ref: 'gencc://citation' in minimal/compact; "
            "dereference once and cache",
            "request_id": "_meta.request_id + _meta.elapsed_ms: per-call trace id and "
            "server-side timing on every envelope",
            "matched": "find_curations: the submission(s) that satisfied a submission-level "
            "classification/submitter/moi filter (compact/standard/full)",
            "has_conflict": "true when supporting and against assertions coexist for a pair",
        },
        "resources": {
            "gencc://capabilities": "this document",
            "gencc://usage": "compact usage notes",
            "gencc://reference": "classification ranks, error taxonomy, field glossary",
            "gencc://license": "CC0 license + attribution + OMIM restriction note",
            "gencc://citation": "recommended citation",
        },
        "response_modes_list": list(RESPONSE_MODES),
        "citation": RECOMMENDED_CITATION,
    }
    digest = hashlib.sha256(
        json.dumps(surface, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:16]
    surface["capabilities_version"] = digest
    return surface


def capabilities_version() -> str:
    """16-char content hash of the static capabilities surface."""
    return str(_static_surface()["capabilities_version"])


def build_capabilities() -> dict[str, Any]:
    """Return the capabilities document, including live data freshness if built.

    ``inheritance_modes`` and ``data_notes`` are data-derived and live outside the
    hashed static surface, so they never perturb ``capabilities_version``.
    """
    surface = dict(_static_surface())
    surface["data"] = _data_status()
    surface["inheritance_modes"] = _inheritance_modes()
    surface["data_notes"] = [
        "Some submitter fields pass through verbatim: assertion_criteria_url may hold "
        "non-URL text (e.g. 'PMID: 28106320'); submitted_as_date mixes formats "
        "(e.g. '2018-03-30 13:31:56' vs ISO 8601 '2024-07-23T00:00:00.000000Z').",
        "The structured pmids array is normalised and can correct malformed PMIDs in "
        "the raw submitter notes text.",
        "find_curations classification/submitter/moi match at the submission level "
        "(any submitter), not the consensus; each result row's `matched` field names "
        "the triggering submission(s).",
    ]
    return surface


def _inheritance_modes() -> list[dict[str, Any]]:
    """Data-derived mode-of-inheritance vocabulary; empty when data is unavailable."""
    try:
        from gencc_link.mcp.service_adapters import get_gencc_service

        return [
            {"title": title, "curie": curie} for title, curie in get_gencc_service().distinct_moi()
        ]
    except Exception:  # data not built yet or unreadable
        return []


def _data_status() -> dict[str, Any]:
    """Best-effort data provenance; never raises (capabilities must always work)."""
    try:
        from gencc_link.mcp.service_adapters import get_gencc_service

        meta = get_gencc_service().get_meta()
        return {
            "status": "ready",
            "gencc_run_date": meta.gencc_run_date,
            "source_last_modified": meta.source_last_modified,
            "schema_version": meta.schema_version,
            "row_count": meta.row_count,
            "gene_count": meta.gene_count,
            "disease_count": meta.disease_count,
            "submitter_count": meta.submitter_count,
            "build_utc": meta.build_utc,
        }
    except Exception as exc:  # data not built yet or unreadable
        return {
            "status": "unavailable",
            "detail": "Database not built. Run `make data` (gencc-link-data build).",
            "error": exc.__class__.__name__,
        }


def register_capability_resources(mcp: FastMCP) -> None:
    """Register the gencc:// resource family."""

    @mcp.resource("gencc://capabilities", mime_type="application/json")
    def capabilities() -> str:
        return json.dumps(build_capabilities())

    @mcp.resource("gencc://usage", mime_type="text/plain")
    def usage() -> str:
        return GENCC_USAGE_NOTES

    @mcp.resource("gencc://reference", mime_type="text/plain")
    def reference() -> str:
        return GENCC_REFERENCE_NOTES

    @mcp.resource("gencc://license", mime_type="text/plain")
    def license_() -> str:
        return GENCC_LICENSE_NOTE

    @mcp.resource("gencc://citation", mime_type="text/plain")
    def citation() -> str:
        return RECOMMENDED_CITATION

    @mcp.resource("gencc://research-use", mime_type="text/plain")
    def research_use() -> str:
        return RESEARCH_USE_NOTICE
