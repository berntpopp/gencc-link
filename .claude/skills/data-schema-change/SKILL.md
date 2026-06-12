---
name: data-schema-change
description: Use when changing the GenCC SQLite schema. Coordinates schema.sql, the ingest builder/aggregates, and the repository together, then rebuilds the database and updates tests and fixtures.
---

# Data schema change

Use this skill when changing the shape of the local SQLite store — columns,
tables, indexes, FTS5 config, or the aggregated `gene_disease` roll-up. These
three layers must change together or queries will break at runtime.

## The three coupled layers

1. **`gencc_link/data/schema.sql`** — the DDL: `submissions`, `genes`,
   `diseases`, `submitters`, the aggregated `gene_disease` table, the
   `genes_fts` / `diseases_fts` FTS5 indexes, and the single-row `meta` table.
2. **`gencc_link/ingest/`** — the builder that populates the schema:
   - `parser.py` parses the 31-column TSV (header validated against the column
     order in `gencc_link/constants.py`);
   - `aggregates.py` computes per-gene / per-disease / per-submitter and
     per-(gene, disease) roll-ups, including consensus and conflict;
   - `builder.py` writes rows + aggregates + FTS, sets the `meta` row, and does
     the atomic rename.
3. **`gencc_link/data/repository.py`** (+ `queries.py`) — the read-only query
   layer that selects from those tables. Every changed column/table must be
   reflected in the SQL here.

## Checklist

1. **Bump the schema version.** If the change is not backward compatible with an
   existing built database, bump `SCHEMA_VERSION` in `gencc_link/constants.py`
   so stale databases are detected.

2. **Edit `schema.sql`.** Add/alter the table, column, index, or FTS definition.
   Keep FTS5 columns and tokenizer consistent with the search queries.

3. **Update the ingest builder.** Adjust `parser.py` (if the source columns
   changed — also update `SUBMISSION_COLUMNS` in `constants.py`),
   `aggregates.py` (if a derived/aggregated value changed — consensus and
   conflict logic lives in `gencc_link/services/consensus.py` and is applied at
   build time), and `builder.py` (the INSERT/index/FTS population).

4. **Update the repository.** Edit `repository.py` / `queries.py` so reads match
   the new schema. Update the service layer (`gencc_link/services/`) and any
   Pydantic records (`gencc_link/models/records.py`) consuming the new fields.

5. **Rebuild.** Run `make data` (`gencc-link-data build`) to rebuild the live
   database, then `make data-info` to confirm provenance and counts. Regenerate
   the test fixture database if the schema changed (see the `tests/fixtures/`
   sample TSV + built SQLite).

6. **Tests.** Update unit tests that assert table shape, repository results,
   aggregates, consensus/conflict, and shaping. Run `make test`.

7. **Docs.** Update the data-store and consensus sections of
   `docs/architecture.md` if the change is user-visible, and add a
   `CHANGELOG.md` entry.

8. **CI.** Run `make ci-local`.
