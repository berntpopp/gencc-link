# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.0] - 2026-06-12

Consumer-uplift release: resolves every finding in `docs/MCP-ASSESSMENT.md`
(scored 9/10) — see `docs/superpowers/specs/2026-06-12-mcp-consumer-uplift-9.5-design.md`.

### Fixed

- `get_gene_disease_assertion` `minimal` mode is now summary-only; verbosity is
  strictly `minimal <= compact <= standard <= full` (was `compact < minimal ==
  standard`). (D1)
- Argument-validation failures (invalid `response_mode`, unknown argument names)
  now return the structured `invalid_input` envelope with `error_code`,
  `field_errors`, and `next_commands` instead of a raw Pydantic/JSON-RPC dump,
  via a new `InputValidationMiddleware`. (D2a)
- Every `invalid_input` envelope now carries `_meta.next_commands` (empty query,
  >20 batch, bad offset, no-filter `find_curations`). (D2b)
- Case-insensitive, multi-suggestion "did you mean" filter hints; `moi="Recessive"`
  now surfaces `Autosomal recessive` rather than `X-linked recessive`. (D6)

### Added

- `find_curations` opaque, release-bound pagination `cursor` + `truncated.next_cursor`;
  the page-forward continuation is the first `_meta.next_commands` entry, so large
  sweeps are autonomous and refresh-safe (a stale cursor is rejected, not silently
  skipped/duplicated). (D3, D4)
- `resolve_identifier` accepts `identifier` as an alias for `query`.
- Capabilities/reference now document `field_errors`, `cursor`/`next_cursor`, the
  `ambiguous_query` trigger, and the `gencc://research-use` resource. (D5, D6)

### Changed

- Token efficiency: `standard` mode now uses `citation_ref` + `citation_short`
  (cite-by-ref); the verbatim `recommended_citation` is reserved for `full` mode.
  No information loss — the full citation stays at `gencc://citation`.

## [0.2.0] - 2026-06-12

### Changed

- **BREAKING:** renamed the gene-disease output field `consensus_classification`
  to `strongest_classification` — it is the highest-rank assertion, not an
  agreement measure (assessment F3). The SQLite column is unchanged; the rename is
  at the model/mapping/shaping boundary, and `has_conflict` / `min_classification`
  carry the disagreement and range.
- Multi-result `search_genes` / `search_diseases` headlines now summarize the set
  ("2 genes match 'COL': COL1A1, COL2A1") instead of naming only the first hit (F1).
- `_meta.next_commands` now fans out across every resolved entity on multi-result
  and batch responses (capped at 5), keeping the unresolved-recovery hint as an
  addition rather than the only entry (F2).
- `minimal` mode keeps `n_submitters` so the headline's submitter count matches the
  structured payload (F6).

### Added

- **Consumer-uplift (assessment `docs/mcp-consumer-assessment.md`, target >9.5/10):**
  - Typed `outputSchema` on all 12 tools — FastMCP now validates every structured
    response against it; clients can validate/introspect field shapes (F4).
  - `submitted_as_date_iso` (normalized ISO-8601 date) alongside the verbatim
    `submitted_as_date` in standard/full (F5).
  - `_meta.citation_short` one-line attribution stub in minimal/compact so a
    sourced answer can be cited without a round-trip (F7).
  - Reachable `ambiguous_query`: `resolve_identifier(kind='auto')` now errors when a
    query matches both a gene and a disease, with disambiguation recovery commands.
- **Batch curation tools** (closes `MCP-UX-ASSESSMENT.md`, target >9.5/10):
  - `get_genes_curations(genes=[...])` / `get_diseases_curations(diseases=[...])`
    collapse multi-entity questions into a single call (max 20; per-entity limit;
    partial-failure `unresolved` list — a single bad input never drops the rest).
  - `find_curations` gains an `ids_only` mode returning just
    `{gene_curie, disease_curie}` pairs for near-zero-token paging.
  - `get_gencc_diagnostics` echoes `server_version` + `capabilities_version` as a
    near-zero-token drift probe (re-fetch the full capabilities doc only on change).
- **MCP evaluation hardening** (closes `docs/mcp-evaluation.md`, target >9.5/10):
  - `find_curations` **validates** `classification`/`submitter`/`moi`: out-of-vocabulary
    or wrong-case values return `invalid_input` with the accepted set + a "did you
    mean" hint instead of a misleading empty result. `submitter`/`moi` valid-sets
    are data-derived (so GenCC's own quirky titles like `"Y-linked inheritance"`
    are accepted); `classification` uses the controlled vocabulary.
  - Each submission-filtered `find_curations` row carries a `matched` field naming
    the triggering submission(s).
  - **Error envelopes** now include `_meta.next_commands` recovery steps (e.g. a
    `not_found` hands back the matching `search_*` call); zero-result searches
    propagate the original query instead of an empty one.
  - Capabilities exposes data-derived `inheritance_modes`, `data_notes`, an `moi`
    convention, and documents `matched`/`citation_ref`/`request_id` response fields.
  - Every `_meta` carries `request_id` + `elapsed_ms`; `minimal`/`compact` drop the
    redundant parent id from list rows and use a cacheable
    `_meta.citation_ref = "gencc://citation"` instead of the full citation.
  - `get_gencc_diagnostics` reports daily download-quota headroom
    (`used_today` / `daily_quota` / `remaining`).
- **Data lifecycle**: build the database once on container startup (idempotent
  entrypoint running `gencc-link-data refresh`), then refresh it on a schedule.
- **In-app refresh scheduler** (dependency-free asyncio loop, unified/http only)
  that runs a conditional refresh every `GENCC_LINK_DATA__REFRESH_INTERVAL_HOURS`
  (default 24) and **hot-reloads** the running server on change.
- **Hot reload**: the read path reopens the SQLite connection when the database
  file is atomically swapped, so any builder (in-app, cron sidecar, k8s CronJob,
  host cron) is picked up live with no restart.
- **Cross-process build lock** (`flock`) so concurrent builders never clobber or
  waste download quota; `ensure_database` uses double-checked locking.
- `rebuild` now returns a `RebuildResult` (`changed` / `not_modified`).
- Deployment artifacts: container entrypoint, `docker-compose.cron.yml`
  (refresh sidecar), `deploy/k8s/` (initContainer Deployment + CronJob), and
  [`docs/data-lifecycle.md`](docs/data-lifecycle.md).
- Refresh status surfaced in `get_gencc_diagnostics`.

### Changed

- **`find_curations` latency**: the access path is rewritten so cost is bounded by
  page size, not match-set size. The flagged ~59 ms outlier (a `gene_disease` full
  scan) drops to ~7.5 ms for the documented workflow; broad single-filter queries
  drop to ~7-12 ms. Covering submission indexes
  (`idx_sub_classification` / `idx_sub_submitter_title` / `idx_sub_moi_nocase`)
  make resolving the matching pairs an index-only scan. No `schema_version` bump
  (indexes do not change results); the query helpers moved to
  `gencc_link/data/find.py`.
- Docker image builds the database in the entrypoint and sets
  `AUTO_BOOTSTRAP=false`, so the request path never triggers a lazy build.

## [0.1.0] - 2026-06-12

### Added

- Initial release of GenCC-Link, an MCP + FastAPI server for Gene Curation
  Coalition (GenCC) gene-disease validity data.
- Local **SQLite + FTS5** store built from the weekly GenCC bulk export (new
  format), with full-text search over gene symbols and disease titles.
- **Ingest pipeline** with conditional download (ETag / `Last-Modified`),
  daily-quota awareness, streaming TSV parsing, build-time aggregation, and an
  atomic build into `data/gencc.sqlite`; exposed via the `gencc-link-data`
  console script (`build` / `refresh` / `info`).
- **Consensus and conflict detection** per gene-disease pair: a consensus
  classification from ranked submitter assertions, and a conflict flag when
  supporting (Definitive / Strong / Moderate) and against (Disputed / Refuted /
  No Known Disease Relationship) assertions coexist.
- **10 MCP tools**: `get_server_capabilities`, `get_gencc_diagnostics`,
  `search_genes`, `search_diseases`, `get_gene_curations`,
  `get_disease_curations`, `get_gene_disease_assertion`, `find_curations`,
  `list_submitters`, and `resolve_identifier`.
- Token-efficient `response_mode` shaping (minimal / compact / standard / full),
  plain-English headlines, `_meta.next_commands` chaining, and a verbatim
  recommended citation.
- `gencc://` MCP resources: `capabilities`, `usage`, `reference`, `license`,
  `citation`, and `research-use`.
- **Three transports** (`unified`, `http`, `stdio`) via a single
  `UnifiedServerManager`; console scripts `gencc-link`, `gencc-link-mcp`, and
  `gencc-link-data`.
- FastAPI surface with `/health` (data-status aware), `/`, and OpenAPI docs.
- Optional auto-bootstrap: the server builds the database on first use when
  `GENCC_LINK_DATA__AUTO_BOOTSTRAP=true` (default).
- Docker multi-stage build (non-root `app` user), Compose dev and production
  overlays with a persistent `gencc-data` volume, CI and release workflows,
  Dependabot config, and project documentation.

[0.1.0]: https://github.com/berntpopp/gencc-link/releases/tag/v0.1.0
