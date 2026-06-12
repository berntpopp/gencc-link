"""Static string resources for MCP tool descriptions, instructions, and docs."""

from __future__ import annotations

from gencc_link.constants import (
    CLASSIFICATION_ORDER,
    DATA_LICENSE,
    RECOMMENDED_CITATION,
    RESEARCH_USE_NOTICE,
)

GENCC_SERVER_INSTRUCTIONS = (
    "GenCC-Link grounds gene-disease validity questions in the Gene Curation "
    "Coalition (GenCC) dataset, which harmonizes curated assertions from member "
    "organizations (ClinGen, Genomics England PanelApp, Orphanet, Ambry, Invitae, "
    "Illumina, and more). Canonical workflow: search_genes / search_diseases to "
    "resolve free text to a HGNC or MONDO id -> get_gene_curations (all diseases "
    "for a gene, with consensus) or get_disease_curations (all genes for a "
    "disease) -> get_gene_disease_assertion for the per-submitter breakdown with "
    "classifications, modes of inheritance, PMIDs, and evidence URLs. Use "
    "find_curations to filter by classification, submitter, or mode of "
    "inheritance (e.g. Definitive autosomal-dominant genes from ClinGen). Each "
    "gene-disease pair carries a consensus classification and a has_conflict flag "
    "(supporting vs. refuting submitters). Results are JSON with a `success` "
    "flag, a plain-English `headline`, `_meta.next_commands`, and "
    "`recommended_citation`. response_mode (minimal|compact|standard|full) trims "
    "tokens; start compact. Call get_server_capabilities or read "
    "gencc://capabilities for the full surface. " + RESEARCH_USE_NOTICE
)

GENCC_USAGE_NOTES = (
    "Resolve text with search_genes/search_diseases (FTS-backed), then "
    "get_gene_curations or get_disease_curations for the aggregated view, or "
    "get_gene_disease_assertion for one pair's full submitter breakdown. "
    "find_curations filters by classification(s), submitter(s), moi, gene, "
    "disease, or has_conflict with limit/offset paging. response_mode=compact is "
    "the default; widen to standard/full for per-submitter detail and raw "
    "submissions. Follow _meta.next_commands to advance without guessing the next "
    "tool. Paste recommended_citation verbatim."
)

GENCC_REFERENCE_NOTES = (
    "Classification ranks (strong -> weak): "
    + " > ".join(CLASSIFICATION_ORDER)
    + ". consensus_classification is the strongest assertion across submitters; "
    "min_classification is the weakest. has_conflict is true when a supporting "
    "classification (Definitive/Strong/Moderate) and an against classification "
    "(Disputed/Refuted/No Known Disease Relationship) coexist for one pair. "
    "Error codes: invalid_input, not_found, ambiguous_query, data_unavailable, "
    "upstream_unavailable, rate_limited, internal_error. Errors carry retryable "
    "+ recovery_action. Disease ids are harmonized to MONDO; OMIM disease names "
    "are restricted by licensing and may be absent. Identifiers: gene_curie is "
    "HGNC (e.g. HGNC:10896); disease_curie is MONDO (e.g. MONDO:0008426). "
    "find_curations classification/submitter/moi filters match at the submission "
    "level (any submitter), not the consensus; each result row's matched field "
    "names the triggering submission. Out-of-vocabulary filter values return "
    "invalid_input with the accepted set (matching is case-insensitive). Some "
    "passthrough fields are verbatim from submitters: assertion_criteria_url may "
    "be non-URL; submitted_as_date mixes formats; the pmids array is normalised."
)

GENCC_LICENSE_NOTE = (
    f"GenCC data is released under {DATA_LICENSE} (public domain dedication). "
    "Attribution to GenCC and the contributing source organizations is requested. "
    "The GenCC download excludes OMIM disease text due to licensing restrictions. "
    + RESEARCH_USE_NOTICE
)

__all__ = [
    "GENCC_LICENSE_NOTE",
    "GENCC_REFERENCE_NOTES",
    "GENCC_SERVER_INSTRUCTIONS",
    "GENCC_USAGE_NOTES",
    "RECOMMENDED_CITATION",
    "RESEARCH_USE_NOTICE",
]
