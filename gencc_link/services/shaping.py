"""Response shaping for token efficiency.

Converts domain records into JSON-ready dicts trimmed to a ``response_mode``,
and builds plain-English ``headline`` strings so an agent can answer without
parsing the whole payload.
"""

from __future__ import annotations

import re
from typing import Any

from gencc_link.mcp.untrusted_content import UntrustedText, fence_untrusted_text
from gencc_link.models import (
    DiseaseSummary,
    GeneDiseaseAssertion,
    GeneSummary,
    SubmissionRecord,
    SubmitterSummary,
)
from gencc_link.models.enums import ResponseMode
from gencc_link.services.cursor import encode_cursor


def gene_headline(gene: GeneSummary) -> str:
    """One-line summary for a gene."""
    conflict = " (has conflicting assertions)" if gene.has_conflict else ""
    strongest = gene.max_classification or "no classification"
    return (
        f"{gene.gene_symbol} ({gene.gene_curie}): {gene.n_diseases} disease(s), "
        f"{gene.n_submitters} submitter(s); strongest = {strongest}{conflict}."
    )


def disease_headline(disease: DiseaseSummary) -> str:
    """One-line summary for a disease."""
    label = disease.disease_title or disease.disease_curie
    strongest = disease.max_classification or "no classification"
    return (
        f"{label} ({disease.disease_curie}): {disease.n_genes} gene(s), "
        f"{disease.n_submitters} submitter(s); strongest = {strongest}."
    )


def assertion_headline(a: GeneDiseaseAssertion) -> str:
    """One-line summary for a gene-disease assertion."""
    label = a.disease_title or a.disease_curie
    strongest = a.strongest_classification or "no classification"
    conflict = " — CONFLICT" if a.has_conflict else ""
    spread = ""
    if a.min_classification and a.min_classification != a.strongest_classification:
        spread = f" (range {a.strongest_classification}..{a.min_classification})"
    return (
        f"{a.gene_symbol} - {label}: {strongest} from {a.n_submitters} "
        f"submitter(s){spread}{conflict}."
    )


_MAX_HEADLINE_NAMES = 5

_ISO_DATE = re.compile(r"^\s*(\d{4})-(\d{2})-(\d{2})")


def normalize_submitted_date(raw: str | None) -> str | None:
    """Normalize a verbatim submitter date to an ISO-8601 date (YYYY-MM-DD).

    GenCC passes dates through verbatim, mixing '2017-08-29 00:00:00' and ISO-8601
    '2024-08-29T00:00:00.000000Z'. The reliably-present, comparable granularity is
    the calendar date; returns None when no valid leading date can be parsed.
    """
    if not raw:
        return None
    match = _ISO_DATE.match(raw)
    if not match:
        return None
    year, month, day = (int(part) for part in match.groups())
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return None
    return f"{year:04d}-{month:02d}-{day:02d}"


def _search_headline(query: str, names: list[str], returned: int, total: int, noun: str) -> str:
    """Set-aware headline: '<scope> match '<query>': name1, name2, …, +N more.'"""
    plural = f"{noun}s" if total != 1 else noun
    scope = f"{returned} of {total} {plural}" if total > returned else f"{total} {plural}"
    shown = ", ".join(names[:_MAX_HEADLINE_NAMES])
    extra = len(names) - _MAX_HEADLINE_NAMES
    more = f", +{extra} more" if extra > 0 else ""
    return f"{scope} match '{query}': {shown}{more}."


def genes_search_headline(query: str, hits: list[GeneSummary], total: int) -> str:
    """Headline for a gene search: rich single line for one exact hit, else set summary."""
    if len(hits) == 1 and total == 1:
        return gene_headline(hits[0])
    return _search_headline(query, [g.gene_symbol for g in hits], len(hits), total, "gene")


def diseases_search_headline(query: str, hits: list[DiseaseSummary], total: int) -> str:
    """Headline for a disease search: rich single line for one exact hit, else set summary."""
    if len(hits) == 1 and total == 1:
        return disease_headline(hits[0])
    names = [d.disease_title or d.disease_curie for d in hits]
    return _search_headline(query, names, len(hits), total, "disease")


def _submitter_dict(s: Any, mode: ResponseMode) -> dict[str, Any]:
    """Shape one SubmitterAssertion (pydantic or dict-like) per mode."""
    data = s if isinstance(s, dict) else s.model_dump()
    base = {
        "submitter_title": data.get("submitter_title"),
        "classification_title": data.get("classification_title"),
        "moi_title": data.get("moi_title"),
    }
    if mode in ("standard", "full"):
        base["submitted_as_date"] = data.get("submitted_as_date")
        base["submitted_as_date_iso"] = normalize_submitted_date(data.get("submitted_as_date"))
        base["public_report_url"] = data.get("public_report_url")
    if mode == "full":
        base["submitter_curie"] = data.get("submitter_curie")
        base["assertion_criteria_url"] = data.get("assertion_criteria_url")
        base["pmids"] = data.get("pmids", [])
    return base


def assertion_dict(
    a: GeneDiseaseAssertion,
    mode: ResponseMode,
    *,
    omit_gene: bool = False,
    omit_disease: bool = False,
) -> dict[str, Any]:
    """Shape an aggregated gene-disease assertion per response_mode.

    ``omit_gene``/``omit_disease`` drop the parent identifier from rows whose
    parent object already carries it (e.g. the gene in ``get_gene_curations``),
    but only in ``minimal``/``compact`` where per-row redundancy dominates the
    payload; ``standard``/``full`` rows keep both so they stay self-describing.
    """
    trim = mode in ("minimal", "compact")
    out: dict[str, Any] = {}
    if not (omit_gene and trim):
        out["gene_curie"] = a.gene_curie
        out["gene_symbol"] = a.gene_symbol
    if not (omit_disease and trim):
        out["disease_curie"] = a.disease_curie
        out["disease_title"] = a.disease_title
    out["strongest_classification"] = a.strongest_classification
    out["n_submitters"] = a.n_submitters
    out["n_submissions"] = a.n_submissions
    out["has_conflict"] = a.has_conflict
    if mode == "minimal":
        return out

    out["min_classification"] = a.min_classification
    out["classification_titles"] = a.classification_titles
    out["moi_titles"] = a.moi_titles
    if mode == "compact":
        out["submitter_titles"] = a.submitter_titles
        return out

    # standard + full: per-submitter breakdown. Each submitter carries its own
    # pmids in full; the pair-level union is dropped as pure redundancy (it
    # triplicated submitters[].pmids / submissions[].pmids and is trivially
    # derivable). See docs/superpowers/specs/2026-06-12-mcp-consumer-uplift-v0.4.0.
    out["submitters"] = [_submitter_dict(s, mode) for s in a.submitters]
    return out


def gene_summary_dict(gene: GeneSummary, mode: ResponseMode) -> dict[str, Any]:
    """Shape a gene summary per response_mode."""
    out = {
        "gene_curie": gene.gene_curie,
        "gene_symbol": gene.gene_symbol,
        "n_diseases": gene.n_diseases,
        "n_submitters": gene.n_submitters,
        "max_classification": gene.max_classification,
        "has_conflict": gene.has_conflict,
    }
    if mode != "minimal":
        out["n_submissions"] = gene.n_submissions
    return out


def disease_summary_dict(disease: DiseaseSummary, mode: ResponseMode) -> dict[str, Any]:
    """Shape a disease summary per response_mode."""
    out = {
        "disease_curie": disease.disease_curie,
        "disease_title": disease.disease_title,
        "n_genes": disease.n_genes,
        "n_submitters": disease.n_submitters,
        "max_classification": disease.max_classification,
    }
    if mode != "minimal":
        out["n_submissions"] = disease.n_submissions
    return out


def submitter_dict(s: SubmitterSummary) -> dict[str, Any]:
    """Shape a submitter summary."""
    return {
        "submitter_curie": s.submitter_curie,
        "submitter_title": s.submitter_title,
        "n_submissions": s.n_submissions,
        "n_genes": s.n_genes,
        "n_diseases": s.n_diseases,
    }


def submission_dict(
    s: SubmissionRecord, *, fenced_notes: list[UntrustedText] | None = None
) -> dict[str, Any]:
    """Shape a raw submission row as *raw-extras only* (full-detail view).

    In full mode the harmonized per-submitter fields (classification, MOI,
    dates, report/criteria URLs) live in ``submitters[]`` and the pair-constant
    disease identity comes from the parent assertion. This row therefore carries
    only what ``submitters[]`` cannot: raw IDs (``sgc_id``), version, the
    unharmonized original disease, free-text ``notes``, and the per-row
    classification/MOI/pmids that let a reader see divergent submissions from one
    submitter. Correlate a row back to a submitter via ``submitter_title``.

    ``notes`` is externally sourced free text (a submitting organization's
    intake-form comment) and is a v1.1 untrusted-text surface: it is emitted as
    the typed ``UntrustedText`` object (kind/text/provenance/raw_sha256), never
    a bare string, and never duplicated in a sibling field. ``notes`` is
    nullable; a missing note stays ``None`` rather than being wrapped. The
    stable GenCC submission id (``sgc_id``) is the fence's ``record_id``. When
    ``fenced_notes`` is given, the fenced object (pre-JSON-dump) is appended so
    the caller can enforce the response-wide v1.1 limits.
    """
    notes_value: dict[str, Any] | None = None
    if s.notes is not None:
        fenced = fence_untrusted_text(s.notes, source="gencc", record_id=s.sgc_id)
        if fenced_notes is not None:
            fenced_notes.append(fenced)
        notes_value = fenced.model_dump(mode="json")
    return {
        "sgc_id": s.sgc_id,
        "submitter_title": s.submitter_title,
        "classification_title": s.classification_title,
        "moi_title": s.moi_title,
        "disease_original_curie": s.disease_original_curie,
        "disease_original_title": s.disease_original_title,
        "version_number": s.version_number,
        "submitted_run_date": s.submitted_run_date,
        "pmids": s.pmids,
        "notes": notes_value,
    }


def truncation_block(
    total: int,
    limit: int,
    offset: int,
    *,
    cursor_context: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Return a truncation hint when more rows exist beyond this page.

    When ``cursor_context`` (``{"release": str | None, "filters": dict}``) is
    given, also mint an opaque ``next_cursor`` that reproduces the next page and
    is bound to the data release (refresh-safe). Callers that page by raw offset
    only (search_*, get_*_curations) omit it.
    """
    returned = max(0, min(limit, total - offset))
    if offset + returned >= total:
        return None
    block: dict[str, Any] = {
        "total": total,
        "returned": returned,
        "next_offset": offset + returned,
        "hint": "More results available; re-call with next_offset, or follow "
        "next_cursor for refresh-safe paging.",
    }
    if cursor_context is not None:
        block["next_cursor"] = encode_cursor(
            release=cursor_context["release"],
            offset=offset + returned,
            limit=limit,
            filters=cursor_context["filters"],
        )
    return block
