-- GenCC-Link SQLite schema (schema_version = 1).
-- Built atomically by gencc_link.ingest.builder from the GenCC submissions
-- export (new format). Every table is dropped and rebuilt on each run.

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = OFF;

-- One row per GenCC submission (sgc_id). Mirrors the 31-column new-format
-- export, plus a derived classification_rank for fast ordering.
CREATE TABLE submissions (
    sgc_id                              TEXT PRIMARY KEY,
    version_number                      INTEGER,
    gene_curie                          TEXT NOT NULL,
    gene_symbol                         TEXT NOT NULL,
    disease_curie                       TEXT NOT NULL,
    disease_title                       TEXT,
    disease_original_curie              TEXT,
    disease_original_title              TEXT,
    classification_curie                TEXT,
    classification_title                TEXT,
    moi_curie                           TEXT,
    moi_title                           TEXT,
    submitter_curie                     TEXT,
    submitter_title                     TEXT,
    submitted_as_hgnc_id                TEXT,
    submitted_as_hgnc_symbol            TEXT,
    submitted_as_disease_id             TEXT,
    submitted_as_disease_name           TEXT,
    submitted_as_moi_id                 TEXT,
    submitted_as_moi_name               TEXT,
    submitted_as_submitter_id           TEXT,
    submitted_as_submitter_name         TEXT,
    submitted_as_classification_id      TEXT,
    submitted_as_classification_name    TEXT,
    submitted_as_date                   TEXT,
    submitted_as_public_report_url      TEXT,
    submitted_as_notes                  TEXT,
    submitted_as_pmids                  TEXT,
    submitted_as_assertion_criteria_url TEXT,
    submitted_as_submission_id          TEXT,
    submitted_run_date                  TEXT,
    classification_rank                 INTEGER NOT NULL DEFAULT -99
);
CREATE INDEX idx_sub_gene_curie ON submissions(gene_curie);
CREATE INDEX idx_sub_gene_symbol ON submissions(gene_symbol);
CREATE INDEX idx_sub_disease_curie ON submissions(disease_curie);
CREATE INDEX idx_sub_submitter ON submissions(submitter_curie);
CREATE INDEX idx_sub_classification ON submissions(classification_title);
CREATE INDEX idx_sub_moi ON submissions(moi_title);
CREATE INDEX idx_sub_gene_disease ON submissions(gene_curie, disease_curie);

-- Derived gene catalog.
CREATE TABLE genes (
    gene_curie              TEXT PRIMARY KEY,
    gene_symbol             TEXT NOT NULL,
    n_submissions           INTEGER NOT NULL,
    n_diseases              INTEGER NOT NULL,
    n_submitters            INTEGER NOT NULL,
    max_classification      TEXT,
    max_classification_rank INTEGER,
    has_conflict            INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_genes_symbol ON genes(gene_symbol COLLATE NOCASE);

-- Derived disease catalog.
CREATE TABLE diseases (
    disease_curie           TEXT PRIMARY KEY,
    disease_title           TEXT,
    n_submissions           INTEGER NOT NULL,
    n_genes                 INTEGER NOT NULL,
    n_submitters            INTEGER NOT NULL,
    max_classification      TEXT,
    max_classification_rank INTEGER
);

-- Derived submitter catalog.
CREATE TABLE submitters (
    submitter_curie         TEXT PRIMARY KEY,
    submitter_title         TEXT NOT NULL,
    n_submissions           INTEGER NOT NULL,
    n_genes                 INTEGER NOT NULL,
    n_diseases              INTEGER NOT NULL
);

-- Aggregated gene-disease assertion: one row per (gene_curie, disease_curie).
-- JSON columns hold pre-computed lists so the repository avoids re-aggregation.
CREATE TABLE gene_disease (
    gene_curie                  TEXT NOT NULL,
    gene_symbol                 TEXT NOT NULL,
    disease_curie               TEXT NOT NULL,
    disease_title               TEXT,
    n_submissions               INTEGER NOT NULL,
    n_submitters                INTEGER NOT NULL,
    consensus_classification    TEXT,
    consensus_rank              INTEGER,
    min_classification          TEXT,
    min_rank                    INTEGER,
    has_conflict                INTEGER NOT NULL DEFAULT 0,
    classification_titles_json  TEXT NOT NULL DEFAULT '[]',
    moi_titles_json             TEXT NOT NULL DEFAULT '[]',
    submitter_titles_json       TEXT NOT NULL DEFAULT '[]',
    pmids_json                  TEXT NOT NULL DEFAULT '[]',
    submitters_json             TEXT NOT NULL DEFAULT '[]',
    PRIMARY KEY (gene_curie, disease_curie)
);
CREATE INDEX idx_gd_gene ON gene_disease(gene_curie);
CREATE INDEX idx_gd_disease ON gene_disease(disease_curie);
CREATE INDEX idx_gd_consensus ON gene_disease(consensus_rank);

-- FTS5 over gene symbols (unicode61 for symbol prefix/substring matching).
CREATE VIRTUAL TABLE genes_fts USING fts5(
    gene_curie UNINDEXED,
    gene_symbol,
    tokenize = 'unicode61'
);

-- FTS5 over disease titles (porter stemming for natural-language disease names).
CREATE VIRTUAL TABLE diseases_fts USING fts5(
    disease_curie UNINDEXED,
    disease_title,
    tokenize = 'porter unicode61'
);

-- Single-row build provenance.
CREATE TABLE meta (
    id                      INTEGER PRIMARY KEY CHECK (id = 1),
    schema_version          TEXT NOT NULL,
    source_format           TEXT NOT NULL,
    source_url              TEXT NOT NULL,
    source_etag             TEXT,
    source_last_modified    TEXT,
    gencc_run_date          TEXT,
    row_count               INTEGER NOT NULL DEFAULT 0,
    gene_count              INTEGER NOT NULL DEFAULT 0,
    disease_count           INTEGER NOT NULL DEFAULT 0,
    submitter_count         INTEGER NOT NULL DEFAULT 0,
    build_utc               TEXT,
    build_duration_s        REAL
);
