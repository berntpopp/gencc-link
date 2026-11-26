"""Typed near-match candidates for a ``resolve_identifier`` miss.

Response-Envelope Standard v1 section 2a: a resolver miss returns ``not_found`` with
``candidates`` drawn from the repo's own gene/disease search, each typed with a
closed ``match_type`` (``all_terms`` = every query word is in the label;
``partial`` = only some are, flagged ``"match": "weak"``) and a token-overlap
``score`` (Jaccard, 0..1).
"""

from __future__ import annotations

import re
from typing import Any

from gencc_link.data.base import GenCCRepositoryProtocol
from gencc_link.exceptions import NotFoundError

_WORD = re.compile(r"[a-z0-9]+")
_MAX_CANDIDATES = 5


def _candidate(kind: str, ident: str, label: str, q_terms: set[str]) -> dict[str, Any]:
    l_terms = set(_WORD.findall(label.lower()))
    score = round(len(q_terms & l_terms) / len(q_terms | l_terms), 2) if q_terms else 0.0
    out: dict[str, Any] = {"kind": kind, "id": ident, "label": label, "score": score}
    if q_terms and q_terms <= l_terms:
        out["match_type"] = "all_terms"
    else:
        out["match_type"] = "partial"
        out["match"] = "weak"
    return out


def miss_candidates(repo: GenCCRepositoryProtocol, query: str, kind: str) -> list[dict[str, Any]]:
    """Ranked near matches for ``query`` (best first, at most five)."""
    q_terms = set(_WORD.findall(query.lower()))
    out: list[dict[str, Any]] = []
    if kind != "disease":
        genes, _ = repo.search_genes(query, limit=_MAX_CANDIDATES, offset=0)
        out += [_candidate("gene", g.gene_curie, g.gene_symbol, q_terms) for g in genes]
    if kind != "gene":
        diseases, _ = repo.search_diseases(query, limit=_MAX_CANDIDATES, offset=0)
        out += [
            _candidate("disease", d.disease_curie, d.disease_title or "", q_terms) for d in diseases
        ]
    out.sort(key=lambda c: c["score"], reverse=True)
    return out[:_MAX_CANDIDATES]


def resolve_miss(repo: GenCCRepositoryProtocol, query: str, kind: str) -> NotFoundError:
    """The ``not_found`` error for a ``resolve_identifier`` miss, with candidates."""
    q = query.strip()
    scope = {"gene": "GenCC gene", "disease": "GenCC disease"}.get(kind, "GenCC gene or disease")
    mondo = ", or mondo_resolve_disease for a MONDO id to pass back here"
    if q.upper().startswith("MONDO:"):  # Mondo is the disease front door; no id loop
        mondo = ""
    hint = {"gene": "Try search_genes.", "disease": f"Try search_diseases{mondo}."}.get(
        kind, f"Try search_genes or search_diseases{mondo}."
    )
    candidates = miss_candidates(repo, q, kind)
    if candidates:
        # Before the hint: messages are capped at 280 chars; next_commands repeat the hint.
        hint = f"Near matches (not resolutions) are in `candidates`. {hint}"
    return NotFoundError(f"Could not resolve the query to a {scope}. {hint}", candidates)
