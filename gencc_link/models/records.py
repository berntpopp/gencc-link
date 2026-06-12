"""Pydantic record models mapping GenCC database rows to typed objects.

These are the shared contract between the repository (which builds them from
SQLite rows), the services (which aggregate/shape them), and the MCP tools
(which serialize them). Field names are snake_case and match the GenCC export.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class GeneSummary(BaseModel):
    """A gene in the GenCC catalog with assertion roll-up counts."""

    gene_curie: str = Field(description="HGNC CURIE, e.g. HGNC:10896")
    gene_symbol: str = Field(description="HGNC-approved gene symbol, e.g. SKI")
    n_submissions: int = Field(description="Number of GenCC submissions touching this gene")
    n_diseases: int = Field(description="Distinct diseases asserted for this gene")
    n_submitters: int = Field(description="Distinct submitting organizations")
    max_classification: str | None = Field(
        default=None, description="Strongest classification across this gene's assertions"
    )
    has_conflict: bool = Field(
        default=False, description="True if any gene-disease pair has conflicting assertions"
    )


class DiseaseSummary(BaseModel):
    """A disease in the GenCC catalog with gene roll-up counts."""

    disease_curie: str = Field(description="Harmonized disease CURIE, e.g. MONDO:0008426")
    disease_title: str | None = Field(default=None, description="Harmonized disease label")
    n_submissions: int = Field(description="Number of GenCC submissions for this disease")
    n_genes: int = Field(description="Distinct genes asserted for this disease")
    n_submitters: int = Field(description="Distinct submitting organizations")
    max_classification: str | None = Field(
        default=None, description="Strongest classification across this disease's assertions"
    )


class SubmitterSummary(BaseModel):
    """A GenCC submitting organization with contribution counts."""

    submitter_curie: str = Field(description="GenCC submitter CURIE, e.g. GENCC:000101")
    submitter_title: str = Field(description="Submitter name, e.g. Ambry Genetics")
    n_submissions: int = Field(description="Total submissions from this organization")
    n_genes: int = Field(description="Distinct genes curated")
    n_diseases: int = Field(description="Distinct diseases curated")


class SubmitterAssertion(BaseModel):
    """One submitter's assertion within an aggregated gene-disease pair."""

    submitter_curie: str | None = None
    submitter_title: str | None = None
    classification_title: str | None = None
    classification_rank: int | None = None
    moi_title: str | None = None
    submitted_as_date: str | None = None
    public_report_url: str | None = None
    assertion_criteria_url: str | None = None
    pmids: list[str] = Field(default_factory=list)


class GeneDiseaseAssertion(BaseModel):
    """Aggregated view of all submitter assertions for one gene-disease pair."""

    gene_curie: str
    gene_symbol: str
    disease_curie: str
    disease_title: str | None = None
    n_submissions: int = 0
    n_submitters: int = 0
    strongest_classification: str | None = Field(
        default=None,
        description=(
            "Strongest (highest-rank) classification asserted by any submitter; "
            "NOT an agreement measure -- read has_conflict and min_classification "
            "for disagreement and the classification range."
        ),
    )
    consensus_rank: int | None = None
    min_classification: str | None = None
    has_conflict: bool = Field(
        default=False,
        description="True when supporting (>=Moderate) and against (<=Disputed) coexist",
    )
    classification_titles: list[str] = Field(default_factory=list)
    moi_titles: list[str] = Field(default_factory=list)
    submitter_titles: list[str] = Field(default_factory=list)
    pmids: list[str] = Field(default_factory=list)
    submitters: list[SubmitterAssertion] = Field(
        default_factory=list, description="Per-submitter breakdown (populated on detail views)"
    )


class SubmissionRecord(BaseModel):
    """A single raw GenCC submission row (sgc_id), used in full-detail views."""

    sgc_id: str
    version_number: int | None = None
    gene_curie: str
    gene_symbol: str
    disease_curie: str
    disease_title: str | None = None
    disease_original_curie: str | None = None
    disease_original_title: str | None = None
    classification_title: str | None = None
    classification_rank: int | None = None
    moi_title: str | None = None
    submitter_curie: str | None = None
    submitter_title: str | None = None
    submitted_as_date: str | None = None
    public_report_url: str | None = None
    assertion_criteria_url: str | None = None
    notes: str | None = None
    pmids: list[str] = Field(default_factory=list)
    submitted_run_date: str | None = None


class BuildMeta(BaseModel):
    """Provenance for the built SQLite database (from the meta table)."""

    schema_version: str
    source_format: str
    source_url: str
    source_etag: str | None = None
    source_last_modified: str | None = None
    gencc_run_date: str | None = None
    row_count: int = 0
    gene_count: int = 0
    disease_count: int = 0
    submitter_count: int = 0
    build_utc: str | None = None
    build_duration_s: float | None = None
