"""Read-only repository interface (contract between data store and services).

The concrete SQLite implementation lives in ``gencc_link.data.repository``.
Defining the Protocol here lets the service layer and tests depend on the
interface, not the implementation.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from gencc_link.models import (
    BuildMeta,
    DiseaseSummary,
    GeneDiseaseAssertion,
    GeneSummary,
    SubmissionRecord,
    SubmitterSummary,
)


@runtime_checkable
class GenCCRepositoryProtocol(Protocol):
    """Read-only access to the built GenCC SQLite database."""

    def get_meta(self) -> BuildMeta:
        """Return build provenance from the ``meta`` table."""
        ...

    def search_genes(
        self, query: str, *, limit: int, offset: int
    ) -> tuple[list[GeneSummary], int]:
        """FTS/exact search over the gene catalog. Returns (page, total_hits)."""
        ...

    def resolve_gene(self, identifier: str) -> GeneSummary | None:
        """Resolve an exact HGNC CURIE or gene symbol to a gene summary."""
        ...

    def search_diseases(
        self, query: str, *, limit: int, offset: int
    ) -> tuple[list[DiseaseSummary], int]:
        """FTS/exact search over the disease catalog. Returns (page, total_hits)."""
        ...

    def resolve_disease(self, identifier: str) -> DiseaseSummary | None:
        """Resolve an exact disease CURIE (MONDO/OMIM) or title to a summary."""
        ...

    def get_gene_disease_pairs(self, gene_curie: str) -> list[GeneDiseaseAssertion]:
        """All aggregated disease assertions for a gene (submitters populated)."""
        ...

    def get_disease_gene_pairs(self, disease_curie: str) -> list[GeneDiseaseAssertion]:
        """All aggregated gene assertions for a disease (submitters populated)."""
        ...

    def get_gene_disease(
        self, gene_curie: str, disease_curie: str
    ) -> GeneDiseaseAssertion | None:
        """One aggregated gene-disease assertion (submitters populated)."""
        ...

    def get_submissions(
        self, gene_curie: str, disease_curie: str
    ) -> list[SubmissionRecord]:
        """Raw submission rows for a gene-disease pair (for full-detail views)."""
        ...

    def find_assertions(
        self,
        *,
        gene: str | None = None,
        disease: str | None = None,
        classification: list[str] | None = None,
        submitter: list[str] | None = None,
        moi: str | None = None,
        has_conflict: bool | None = None,
        limit: int,
        offset: int,
    ) -> tuple[list[GeneDiseaseAssertion], int]:
        """Filter aggregated gene-disease assertions. Returns (page, total)."""
        ...

    def list_submitters(self) -> list[SubmitterSummary]:
        """Return all submitting organizations with contribution counts."""
        ...

    def close(self) -> None:
        """Release the underlying database connection."""
        ...
