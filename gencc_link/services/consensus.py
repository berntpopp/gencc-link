"""Consensus + conflict aggregation across submitter assertions.

Pure functions shared by the ingest builder (to precompute `gene_disease` rows)
and the service layer. The aggregation is the analytical value-add of GenCC-Link:
it collapses many submitters' assertions for one gene-disease into a consensus
classification and flags disagreement.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from gencc_link.constants import (
    AGAINST_CLASSIFICATIONS,
    SUPPORTING_CLASSIFICATIONS,
    UNKNOWN_CLASSIFICATION_RANK,
    classification_rank,
)

_PMID_SPLIT = re.compile(r"[;,\s]+")


def parse_pmids(raw: str | None) -> list[str]:
    """Extract bare PMIDs from a GenCC ``submitted_as_pmids`` field.

    Handles ``"PMID: 28106320"``, ``"28106320;28106321"``, and mixed forms.
    Returns a de-duplicated, order-preserving list of digit strings.
    """
    if not raw:
        return []
    out: list[str] = []
    for token in _PMID_SPLIT.split(raw.strip()):
        cleaned = token.strip().upper()
        if cleaned.startswith("PMID"):
            cleaned = cleaned[4:].lstrip(":").strip()
        if cleaned.isdigit():
            out.append(cleaned)
    return list(dict.fromkeys(out))


def _dedupe(values: list[str | None]) -> list[str]:
    """Drop blanks/Nones and de-duplicate, preserving first-seen order."""
    return list(dict.fromkeys(v for v in values if v))


@dataclass
class Aggregate:
    """Pre-computed aggregation for one gene-disease pair."""

    n_submissions: int = 0
    n_submitters: int = 0
    consensus_classification: str | None = None
    consensus_rank: int | None = None
    min_classification: str | None = None
    min_rank: int | None = None
    has_conflict: bool = False
    classification_titles: list[str] = field(default_factory=list)
    moi_titles: list[str] = field(default_factory=list)
    submitter_titles: list[str] = field(default_factory=list)
    pmids: list[str] = field(default_factory=list)
    submitters: list[dict[str, Any]] = field(default_factory=list)


def aggregate_gene_disease(rows: list[dict[str, Any]]) -> Aggregate:
    """Aggregate raw submission rows for a single gene-disease pair.

    Args:
        rows: submission dicts with at least the keys ``classification_title``,
            ``submitter_curie``, ``submitter_title``, ``moi_title``,
            ``submitted_as_date``, ``submitted_as_public_report_url``,
            ``submitted_as_assertion_criteria_url``, ``submitted_as_pmids``.

    Returns:
        An :class:`Aggregate` with consensus, conflict flag, and per-submitter
        breakdown. Submitters are ordered strongest classification first.
    """
    agg = Aggregate(n_submissions=len(rows))

    submitters: list[dict[str, Any]] = []
    ranks: list[int] = []
    classification_titles: list[str | None] = []
    moi_titles: list[str | None] = []
    submitter_titles: list[str | None] = []
    all_pmids: list[str] = []

    for row in rows:
        title = row.get("classification_title")
        rank = classification_rank(title)
        pmids = parse_pmids(row.get("submitted_as_pmids"))
        all_pmids.extend(pmids)
        classification_titles.append(title)
        moi_titles.append(row.get("moi_title"))
        submitter_titles.append(row.get("submitter_title"))
        if rank > UNKNOWN_CLASSIFICATION_RANK:
            ranks.append(rank)
        submitters.append(
            {
                "submitter_curie": row.get("submitter_curie"),
                "submitter_title": row.get("submitter_title"),
                "classification_title": title,
                "classification_rank": rank if rank > UNKNOWN_CLASSIFICATION_RANK else None,
                "moi_title": row.get("moi_title"),
                "submitted_as_date": row.get("submitted_as_date"),
                "public_report_url": row.get("submitted_as_public_report_url"),
                "assertion_criteria_url": row.get("submitted_as_assertion_criteria_url"),
                "pmids": pmids,
            }
        )

    # Order submitters strongest-first (None ranks sink to the bottom).
    submitters.sort(
        key=lambda s: s["classification_rank"] if s["classification_rank"] is not None else -1000,
        reverse=True,
    )

    agg.submitters = submitters
    agg.n_submitters = len(_dedupe([str(s["submitter_curie"]) for s in submitters]))
    agg.classification_titles = _dedupe(classification_titles)
    agg.moi_titles = _dedupe(moi_titles)
    agg.submitter_titles = _dedupe(submitter_titles)
    agg.pmids = list(dict.fromkeys(all_pmids))

    if ranks:
        agg.consensus_rank = max(ranks)
        agg.min_rank = min(ranks)
        agg.consensus_classification = _title_for_rank(submitters, agg.consensus_rank)
        agg.min_classification = _title_for_rank(submitters, agg.min_rank)

    titles = set(agg.classification_titles)
    agg.has_conflict = bool(
        (titles & SUPPORTING_CLASSIFICATIONS) and (titles & AGAINST_CLASSIFICATIONS)
    )
    return agg


def _title_for_rank(submitters: list[dict[str, Any]], rank: int) -> str | None:
    """Return the first classification title matching ``rank``."""
    for s in submitters:
        if s["classification_rank"] == rank:
            return str(s["classification_title"]) if s["classification_title"] else None
    return None
