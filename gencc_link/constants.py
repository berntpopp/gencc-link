"""Stable GenCC vocabulary, download endpoints, and provenance constants.

These are deliberately hard-coded (not derived from a given export) because they
define the *contract* the ingest builder, repository, services, and MCP tools all
agree on. The classification ranks drive consensus and conflict detection.
"""

from __future__ import annotations

# --- Download endpoints (verified 2026-06-12) -----------------------------------

GENCC_BASE_URL = "https://thegencc.org"

# "new" format is recommended by GenCC; "legacy" is deprecated until 2026-09-30.
DOWNLOAD_URLS: dict[str, dict[str, str]] = {
    "new": {
        "tsv": f"{GENCC_BASE_URL}/download/action/submissions-export-tsv?format=new",
        "csv": f"{GENCC_BASE_URL}/download/action/submissions-export-csv?format=new",
        "xlsx": f"{GENCC_BASE_URL}/download/action/submissions-export-xlsx?format=new",
    },
    "legacy": {
        "tsv": f"{GENCC_BASE_URL}/download/action/submissions-export-tsv",
        "csv": f"{GENCC_BASE_URL}/download/action/submissions-export-csv",
        "xlsx": f"{GENCC_BASE_URL}/download/action/submissions-export-xlsx",
    },
}

# GenCC serves a per-IP daily download quota; 304 Not Modified and HEAD are exempt.
DOWNLOAD_DAILY_QUOTA = 20

# --- TSV schema (new format, 31 columns) ----------------------------------------

# Authoritative column order of the GenCC new-format submissions export. The
# parser validates the live header against this list.
SUBMISSION_COLUMNS: tuple[str, ...] = (
    "sgc_id",
    "version_number",
    "gene_curie",
    "gene_symbol",
    "disease_curie",
    "disease_title",
    "disease_original_curie",
    "disease_original_title",
    "classification_curie",
    "classification_title",
    "moi_curie",
    "moi_title",
    "submitter_curie",
    "submitter_title",
    "submitted_as_hgnc_id",
    "submitted_as_hgnc_symbol",
    "submitted_as_disease_id",
    "submitted_as_disease_name",
    "submitted_as_moi_id",
    "submitted_as_moi_name",
    "submitted_as_submitter_id",
    "submitted_as_submitter_name",
    "submitted_as_classification_id",
    "submitted_as_classification_name",
    "submitted_as_date",
    "submitted_as_public_report_url",
    "submitted_as_notes",
    "submitted_as_pmids",
    "submitted_as_assertion_criteria_url",
    "submitted_as_submission_id",
    "submitted_run_date",
)

# --- Classification vocabulary + ranks ------------------------------------------

# GenCC harmonized classification titles, ranked high (strong evidence for a
# gene-disease relationship) to low (evidence against). Higher rank == stronger
# positive validity. Animal-model-only and no-known-relationship are not on the
# positive/negative evidence ladder and get sentinel low ranks so they never win
# a consensus.
CLASSIFICATION_RANKS: dict[str, int] = {
    "Definitive": 6,
    "Strong": 5,
    "Moderate": 4,
    "Supportive": 3,
    "Limited": 2,
    "Disputed Evidence": 1,
    "Refuted Evidence": 0,
    "Animal Model Only": -1,
    "No Known Disease Relationship": -2,
}

# Ordered best -> worst, for capabilities/reference output.
CLASSIFICATION_ORDER: tuple[str, ...] = tuple(
    sorted(CLASSIFICATION_RANKS, key=lambda title: CLASSIFICATION_RANKS[title], reverse=True)
)

# Conflict detection between submitters on one gene-disease pair. A conflict
# exists when at least one submitter asserts *supporting* evidence while another
# asserts *against*. "Animal Model Only" is deliberately excluded from both sides:
# it is weak/orthogonal evidence, not a contradiction.
SUPPORTING_CLASSIFICATIONS: frozenset[str] = frozenset({"Definitive", "Strong", "Moderate"})
AGAINST_CLASSIFICATIONS: frozenset[str] = frozenset(
    {"Disputed Evidence", "Refuted Evidence", "No Known Disease Relationship"}
)

UNKNOWN_CLASSIFICATION_RANK = -99


def classification_rank(title: str | None) -> int:
    """Return the numeric rank for a classification title (unknown -> sentinel)."""
    if not title:
        return UNKNOWN_CLASSIFICATION_RANK
    return CLASSIFICATION_RANKS.get(title.strip(), UNKNOWN_CLASSIFICATION_RANK)


# --- Provenance -----------------------------------------------------------------

SCHEMA_VERSION = "1"

RESEARCH_USE_NOTICE = (
    "Research use only; not for clinical decision support, diagnosis, treatment, "
    "or patient management. GenCC data is not intended for direct diagnostic use "
    "or medical decision-making without review by a genetics professional."
)

# GenCC data is CC0; attribution to GenCC and contributing sources is requested.
DATA_LICENSE = "CC0-1.0"

# Short attribution stub for compact/minimal envelopes; the full verbatim citation
# stays behind gencc://citation (and in standard/full). Not a substitute for
# RECOMMENDED_CITATION.
CITATION_SHORT = "GenCC (thegencc.org), CC0-1.0"

RECOMMENDED_CITATION = (
    "DiStefano MT, Goehringer S, Babb L, et al. The Gene Curation Coalition: A "
    "global effort to harmonize gene-disease evidence resources. Genet Med. "
    "2022;24(8):1732-1742. doi:10.1016/j.gim.2022.04.017. Data: GenCC "
    "(thegencc.org), CC0 1.0."
)
