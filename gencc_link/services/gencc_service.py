"""GenCC service: orchestrates the repository, consensus, and shaping.

Tools call this layer (never the repository directly). Methods return plain
JSON-ready dicts (the data payload); the MCP tool wrapper attaches
``_meta.next_commands`` and the success/error envelope.
"""

from __future__ import annotations

import time
from typing import Any

from gencc_link.data.base import GenCCRepositoryProtocol
from gencc_link.exceptions import InvalidInputError, NotFoundError
from gencc_link.models import BuildMeta
from gencc_link.models.enums import RESPONSE_MODES, ResponseMode
from gencc_link.services import shaping
from gencc_link.services.filters import validate_find_filters

_MAX_LIMIT = 200


class _TTLCache:
    """Tiny insertion-ordered TTL cache (disabled when maxsize <= 0)."""

    def __init__(self, maxsize: int, ttl: int) -> None:
        self._maxsize = maxsize
        self._ttl = ttl
        self._store: dict[str, tuple[float, dict[str, Any]]] = {}

    def get(self, key: str) -> dict[str, Any] | None:
        if self._maxsize <= 0:
            return None
        item = self._store.get(key)
        if item is None:
            return None
        expires_at, value = item
        if expires_at < time.monotonic():
            self._store.pop(key, None)
            return None
        return value

    def put(self, key: str, value: dict[str, Any]) -> None:
        if self._maxsize <= 0:
            return
        if len(self._store) >= self._maxsize:
            self._store.pop(next(iter(self._store)), None)
        self._store[key] = (time.monotonic() + self._ttl, value)


class GenCCService:
    """Read-only business logic over the GenCC database."""

    def __init__(
        self,
        repository: GenCCRepositoryProtocol,
        *,
        cache_size: int = 512,
        cache_ttl: int = 3600,
    ) -> None:
        self._repo = repository
        self._cache = _TTLCache(cache_size, cache_ttl)

    # --- helpers --------------------------------------------------------

    @staticmethod
    def _validate_mode(mode: str) -> ResponseMode:
        if mode not in RESPONSE_MODES:
            raise InvalidInputError(
                f"Invalid response_mode {mode!r}. Use one of: {', '.join(RESPONSE_MODES)}.",
                field="response_mode",
            )
        return mode

    @staticmethod
    def _clamp_limit(limit: int) -> int:
        if limit < 1:
            raise InvalidInputError("limit must be >= 1.", field="limit")
        return min(limit, _MAX_LIMIT)

    @staticmethod
    def _validate_offset(offset: int) -> int:
        if offset < 0:
            raise InvalidInputError("offset must be >= 0.", field="offset")
        return offset

    def get_meta(self) -> BuildMeta:
        """Return build provenance (cached for the process lifetime)."""
        return self._repo.get_meta()

    def distinct_moi(self) -> list[tuple[str, str | None]]:
        """Distinct ``(moi_title, moi_curie)`` present in the data (for discovery)."""
        return self._repo.distinct_moi()

    # --- search ---------------------------------------------------------

    def search_genes(
        self, query: str, *, response_mode: str = "compact", limit: int = 20, offset: int = 0
    ) -> dict[str, Any]:
        mode = self._validate_mode(response_mode)
        if not query or not query.strip():
            raise InvalidInputError("query must not be empty.", field="query")
        limit = self._clamp_limit(limit)
        offset = self._validate_offset(offset)
        key = f"sg:{query.strip().lower()}:{mode}:{limit}:{offset}"
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        hits, total = self._repo.search_genes(query.strip(), limit=limit, offset=offset)
        payload: dict[str, Any] = {
            "query": query.strip(),
            "count": len(hits),
            "total": total,
            "genes": [shaping.gene_summary_dict(g, mode) for g in hits],
        }
        if hits:
            payload["headline"] = shaping.gene_headline(hits[0])
        trunc = shaping.truncation_block(total, limit, offset)
        if trunc:
            payload["truncated"] = trunc
        self._cache.put(key, payload)
        return payload

    def search_diseases(
        self, query: str, *, response_mode: str = "compact", limit: int = 20, offset: int = 0
    ) -> dict[str, Any]:
        mode = self._validate_mode(response_mode)
        if not query or not query.strip():
            raise InvalidInputError("query must not be empty.", field="query")
        limit = self._clamp_limit(limit)
        offset = self._validate_offset(offset)
        key = f"sd:{query.strip().lower()}:{mode}:{limit}:{offset}"
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        hits, total = self._repo.search_diseases(query.strip(), limit=limit, offset=offset)
        payload: dict[str, Any] = {
            "query": query.strip(),
            "count": len(hits),
            "total": total,
            "diseases": [shaping.disease_summary_dict(d, mode) for d in hits],
        }
        if hits:
            payload["headline"] = shaping.disease_headline(hits[0])
        trunc = shaping.truncation_block(total, limit, offset)
        if trunc:
            payload["truncated"] = trunc
        self._cache.put(key, payload)
        return payload

    # --- curations ------------------------------------------------------

    def get_gene_curations(
        self, gene: str, *, response_mode: str = "compact", limit: int = 50, offset: int = 0
    ) -> dict[str, Any]:
        mode = self._validate_mode(response_mode)
        if not gene or not gene.strip():
            raise InvalidInputError("gene must not be empty.", field="gene")
        limit = self._clamp_limit(limit)
        offset = self._validate_offset(offset)

        summary = self._repo.resolve_gene(gene.strip())
        if summary is None:
            raise NotFoundError(
                f"No GenCC gene found for {gene!r}. Try search_genes to resolve a symbol "
                "or HGNC id."
            )
        pairs = self._repo.get_gene_disease_pairs(summary.gene_curie)
        total = len(pairs)
        page = pairs[offset : offset + limit]
        payload: dict[str, Any] = {
            "gene": shaping.gene_summary_dict(summary, mode),
            "headline": shaping.gene_headline(summary),
            "count": len(page),
            "total": total,
            "diseases": [shaping.assertion_dict(a, mode, omit_gene=True) for a in page],
        }
        trunc = shaping.truncation_block(total, limit, offset)
        if trunc:
            payload["truncated"] = trunc
        return payload

    def get_disease_curations(
        self, disease: str, *, response_mode: str = "compact", limit: int = 50, offset: int = 0
    ) -> dict[str, Any]:
        mode = self._validate_mode(response_mode)
        if not disease or not disease.strip():
            raise InvalidInputError("disease must not be empty.", field="disease")
        limit = self._clamp_limit(limit)
        offset = self._validate_offset(offset)

        summary = self._repo.resolve_disease(disease.strip())
        if summary is None:
            raise NotFoundError(
                f"No GenCC disease found for {disease!r}. Try search_diseases to resolve a "
                "label or MONDO id."
            )
        pairs = self._repo.get_disease_gene_pairs(summary.disease_curie)
        total = len(pairs)
        page = pairs[offset : offset + limit]
        payload: dict[str, Any] = {
            "disease": shaping.disease_summary_dict(summary, mode),
            "headline": shaping.disease_headline(summary),
            "count": len(page),
            "total": total,
            "genes": [shaping.assertion_dict(a, mode, omit_disease=True) for a in page],
        }
        trunc = shaping.truncation_block(total, limit, offset)
        if trunc:
            payload["truncated"] = trunc
        return payload

    # --- detail ---------------------------------------------------------

    def get_gene_disease_assertion(
        self, gene: str, disease: str, *, response_mode: str = "standard"
    ) -> dict[str, Any]:
        mode = self._validate_mode(response_mode)
        if not gene or not gene.strip():
            raise InvalidInputError("gene must not be empty.", field="gene")
        if not disease or not disease.strip():
            raise InvalidInputError("disease must not be empty.", field="disease")

        gene_summary = self._repo.resolve_gene(gene.strip())
        if gene_summary is None:
            raise NotFoundError(f"No GenCC gene found for {gene!r}.")
        disease_summary = self._repo.resolve_disease(disease.strip())
        if disease_summary is None:
            raise NotFoundError(f"No GenCC disease found for {disease!r}.")

        assertion = self._repo.get_gene_disease(
            gene_summary.gene_curie, disease_summary.disease_curie
        )
        if assertion is None:
            raise NotFoundError(
                f"No GenCC assertion links {gene_summary.gene_symbol} to "
                f"{disease_summary.disease_curie}."
            )
        payload: dict[str, Any] = {
            "assertion": shaping.assertion_dict(
                assertion, "standard" if mode == "minimal" else mode
            ),
            "headline": shaping.assertion_headline(assertion),
        }
        if mode == "full":
            submissions = self._repo.get_submissions(
                gene_summary.gene_curie, disease_summary.disease_curie
            )
            payload["submissions"] = [shaping.submission_dict(s) for s in submissions]
        return payload

    # --- find / list ----------------------------------------------------

    def find_curations(
        self,
        *,
        gene: str | None = None,
        disease: str | None = None,
        classification: list[str] | None = None,
        submitter: list[str] | None = None,
        moi: str | None = None,
        has_conflict: bool | None = None,
        response_mode: str = "compact",
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        mode = self._validate_mode(response_mode)
        limit = self._clamp_limit(limit)
        offset = self._validate_offset(offset)
        if not any([gene, disease, classification, submitter, moi, has_conflict is not None]):
            raise InvalidInputError(
                "Provide at least one filter (gene, disease, classification, submitter, "
                "moi, or has_conflict)."
            )

        valid_subm_titles: set[str] = set()
        valid_subm_curies: set[str] = set()
        valid_moi_titles: set[str] = set()
        if submitter:
            subs = self._repo.list_submitters()
            valid_subm_titles = {s.submitter_title for s in subs if s.submitter_title}
            valid_subm_curies = {s.submitter_curie for s in subs if s.submitter_curie}
        if moi and moi.strip():
            valid_moi_titles = {title for title, _ in self._repo.distinct_moi()}

        classification, submitter, moi = validate_find_filters(
            classification=classification,
            submitter=submitter,
            moi=moi,
            valid_submitter_titles=valid_subm_titles,
            valid_submitter_curies=valid_subm_curies,
            valid_moi_titles=valid_moi_titles,
        )

        results, total, matched = self._repo.find_assertions(
            gene=gene.strip() if gene else None,
            disease=disease.strip() if disease else None,
            classification=classification,
            submitter=submitter,
            moi=moi,
            has_conflict=has_conflict,
            limit=limit,
            offset=offset,
        )
        rows: list[dict[str, Any]] = []
        for a in results:
            row = shaping.assertion_dict(a, mode)
            if matched and mode != "minimal":
                row["matched"] = matched.get((a.gene_curie, a.disease_curie), [])
            rows.append(row)
        payload: dict[str, Any] = {
            "count": len(results),
            "total": total,
            "filters": {
                "gene": gene,
                "disease": disease,
                "classification": classification,
                "submitter": submitter,
                "moi": moi,
                "has_conflict": has_conflict,
            },
            "results": rows,
        }
        trunc = shaping.truncation_block(total, limit, offset)
        if trunc:
            payload["truncated"] = trunc
        return payload

    def list_submitters(self) -> dict[str, Any]:
        submitters = self._repo.list_submitters()
        return {
            "count": len(submitters),
            "submitters": [shaping.submitter_dict(s) for s in submitters],
        }

    def resolve_identifier(self, query: str, *, kind: str = "auto") -> dict[str, Any]:
        if not query or not query.strip():
            raise InvalidInputError("query must not be empty.", field="query")
        if kind not in ("auto", "gene", "disease"):
            raise InvalidInputError("kind must be 'auto', 'gene', or 'disease'.", field="kind")
        q = query.strip()
        result: dict[str, Any] = {"query": q, "gene": None, "disease": None}
        if kind in ("auto", "gene"):
            gene = self._repo.resolve_gene(q)
            if gene is not None:
                result["gene"] = shaping.gene_summary_dict(gene, "compact")
        if kind in ("auto", "disease"):
            disease = self._repo.resolve_disease(q)
            if disease is not None:
                result["disease"] = shaping.disease_summary_dict(disease, "compact")
        if result["gene"] is None and result["disease"] is None:
            raise NotFoundError(
                f"Could not resolve {query!r} to a GenCC gene or disease. Try search_genes "
                "or search_diseases."
            )
        return result
