"""Response shaping for token efficiency.

Converts domain records into JSON-ready dicts trimmed to a ``response_mode``,
and builds plain-English ``headline`` strings so an agent can answer without
parsing the whole payload.
"""

from __future__ import annotations

from typing import Any

from gencc_link.models import (
    DiseaseSummary,
    GeneDiseaseAssertion,
    GeneSummary,
    SubmissionRecord,
    SubmitterSummary,
)
from gencc_link.models.enums import ResponseMode


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

    # standard + full: per-submitter breakdown
    out["submitters"] = [_submitter_dict(s, mode) for s in a.submitters]
    if mode == "full":
        out["pmids"] = a.pmids
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


def submission_dict(s: SubmissionRecord) -> dict[str, Any]:
    """Shape a raw submission row (full-detail view)."""
    return {
        "sgc_id": s.sgc_id,
        "submitter_title": s.submitter_title,
        "classification_title": s.classification_title,
        "moi_title": s.moi_title,
        "disease_curie": s.disease_curie,
        "disease_title": s.disease_title,
        "disease_original_curie": s.disease_original_curie,
        "disease_original_title": s.disease_original_title,
        "submitted_as_date": s.submitted_as_date,
        "public_report_url": s.public_report_url,
        "assertion_criteria_url": s.assertion_criteria_url,
        "pmids": s.pmids,
        "notes": s.notes,
    }


def truncation_block(total: int, limit: int, offset: int) -> dict[str, Any] | None:
    """Return a truncation hint when more rows exist beyond this page."""
    returned = max(0, min(limit, total - offset))
    if offset + returned >= total:
        return None
    return {
        "total": total,
        "returned": returned,
        "next_offset": offset + returned,
        "hint": "More results available; re-call with the next offset to page further.",
    }
