"""Query helpers for the read-only GenCC repository.

Holds FTS5 sanitization, ``LIKE`` escaping, and the ``sqlite3.Row`` -> pydantic
record builders used by :mod:`gencc_link.data.repository`. Kept separate so the
repository module stays focused on connection management and query orchestration.
"""

from __future__ import annotations

import json
import re
import sqlite3
from typing import Any

from gencc_link.models import (
    DiseaseSummary,
    GeneDiseaseAssertion,
    GeneSummary,
    SubmissionRecord,
    SubmitterAssertion,
)
from gencc_link.services.consensus import parse_pmids

# Tokens for FTS5: keep alphanumerics; everything else is a separator. Tokens are
# re-quoted before being handed to MATCH so they can never be read as operators.
_FTS_TOKEN = re.compile(r"[A-Za-z0-9]+")


def sanitize_fts_query(query: str) -> str | None:
    """Build a safe FTS5 ``MATCH`` expression from free-text input.

    Each alphanumeric token is wrapped in double quotes (so FTS5 treats it as a
    literal phrase, never an operator), tokens are AND-combined, and a ``*``
    prefix wildcard is appended to the final token for type-ahead search.

    Args:
        query: Raw user query string.

    Returns:
        A sanitized MATCH expression, or ``None`` when the query has no usable
        tokens (the caller should then fall back to ``LIKE``).
    """
    tokens = _FTS_TOKEN.findall(query)
    if not tokens:
        return None
    quoted = [f'"{token}"' for token in tokens]
    quoted[-1] = f'"{tokens[-1]}"*'
    return " ".join(quoted)


def like_pattern(query: str) -> str:
    """Return a ``LIKE`` pattern matching ``query`` as a substring.

    Escapes ``\\``, ``%``, and ``_`` so user input cannot inject wildcards
    (pair with an ``ESCAPE '\\'`` clause at the call site).
    """
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def json_list(raw: str | None) -> list[Any]:
    """Parse a JSON array column into a list (empty list on null/blank)."""
    if not raw:
        return []
    parsed: list[Any] = json.loads(raw)
    return parsed


def gene_summary_from_row(row: sqlite3.Row) -> GeneSummary:
    """Build a :class:`GeneSummary` from a ``genes`` row."""
    return GeneSummary(
        gene_curie=row["gene_curie"],
        gene_symbol=row["gene_symbol"],
        n_submissions=row["n_submissions"],
        n_diseases=row["n_diseases"],
        n_submitters=row["n_submitters"],
        max_classification=row["max_classification"],
        has_conflict=bool(row["has_conflict"]),
    )


def disease_summary_from_row(row: sqlite3.Row) -> DiseaseSummary:
    """Build a :class:`DiseaseSummary` from a ``diseases`` row."""
    return DiseaseSummary(
        disease_curie=row["disease_curie"],
        disease_title=row["disease_title"],
        n_submissions=row["n_submissions"],
        n_genes=row["n_genes"],
        n_submitters=row["n_submitters"],
        max_classification=row["max_classification"],
    )


def assertion_from_row(row: sqlite3.Row) -> GeneDiseaseAssertion:
    """Build a :class:`GeneDiseaseAssertion` from a ``gene_disease`` row.

    The ``*_json`` columns are decoded into lists; ``submitters_json`` decodes
    into :class:`SubmitterAssertion` objects. The table's ``min_rank`` column
    has no model field and is ignored.
    """
    submitters = [SubmitterAssertion(**entry) for entry in json_list(row["submitters_json"])]
    return GeneDiseaseAssertion(
        gene_curie=row["gene_curie"],
        gene_symbol=row["gene_symbol"],
        disease_curie=row["disease_curie"],
        disease_title=row["disease_title"],
        n_submissions=row["n_submissions"],
        n_submitters=row["n_submitters"],
        consensus_classification=row["consensus_classification"],
        consensus_rank=row["consensus_rank"],
        min_classification=row["min_classification"],
        has_conflict=bool(row["has_conflict"]),
        classification_titles=json_list(row["classification_titles_json"]),
        moi_titles=json_list(row["moi_titles_json"]),
        submitter_titles=json_list(row["submitter_titles_json"]),
        pmids=json_list(row["pmids_json"]),
        submitters=submitters,
    )


def submission_from_row(row: sqlite3.Row) -> SubmissionRecord:
    """Build a :class:`SubmissionRecord` from a ``submissions`` row."""
    return SubmissionRecord(
        sgc_id=row["sgc_id"],
        version_number=row["version_number"],
        gene_curie=row["gene_curie"],
        gene_symbol=row["gene_symbol"],
        disease_curie=row["disease_curie"],
        disease_title=row["disease_title"],
        disease_original_curie=row["disease_original_curie"],
        disease_original_title=row["disease_original_title"],
        classification_title=row["classification_title"],
        classification_rank=row["classification_rank"],
        moi_title=row["moi_title"],
        submitter_curie=row["submitter_curie"],
        submitter_title=row["submitter_title"],
        submitted_as_date=row["submitted_as_date"],
        public_report_url=row["submitted_as_public_report_url"],
        assertion_criteria_url=row["submitted_as_assertion_criteria_url"],
        notes=row["submitted_as_notes"],
        pmids=parse_pmids(row["submitted_as_pmids"]),
        submitted_run_date=row["submitted_run_date"],
    )
