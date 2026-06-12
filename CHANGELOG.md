# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

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
