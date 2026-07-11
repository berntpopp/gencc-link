# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.7.0] - 2026-07-11

### Security

- **BREAKING -- `get_gene_disease_assertion`'s `submissions[].notes` is now a
  typed `untrusted_text` object.** Response-Envelope Standard v1.1
  untrusted-content fencing: a submitting organization's free-text intake
  note (only present at `response_mode=full`) is emitted as
  `{kind: "untrusted_text", text, provenance: {source, record_id,
  retrieved_at}, raw_sha256}` instead of a bare string, so hosts/models treat
  retrieved GenCC prose as typed evidence data, never as instructions. A
  missing note stays `null` rather than being wrapped. Defense in depth;
  research use only, mirrors upstream GenCC disclaimers. Consumers reading
  `submissions[].notes` as a plain string must update to read `.text`.
- Added `gencc_link/mcp/untrusted_content.py` (copied byte-identical from the
  released `pubtator-link` reference) plus a limits helper
  (`enforce_untrusted_text_limits`) enforcing the v1.1 ceilings (2 MiB/object,
  128 objects, 8 MiB total) as an explicit `untrusted_text_limit_exceeded`
  error, never a masked `internal_error`.

## [0.6.1] - 2026-07-10

### Security

- Harden GenCC export acquisition with redirect rejection, configurable
  Content-Length and streamed-byte limits, a monotonic deadline, same-directory
  atomic replacement, and preservation of the previous valid export on failure.

## [0.6.0] - 2026-07-10

### Security

- Replace the disabled FastMCP Host/Origin protection with strict validation on
  the outer ASGI application and the native MCP transport. Untrusted Host values
  are rejected across root, health, and MCP routes; browser Origin values must be
  same-origin or explicitly approved.
- Reject wildcard Host patterns and declare the production proxy hostname and
  loopback health-check Host explicitly in the supplied Compose profiles.

### Changed

- **BREAKING -- proxy Host configuration.** Custom reverse-proxy deployments must
  add their exact public hostname to `GENCC_LINK_ALLOWED_HOSTS`. JSON lists are
  accepted; the safe default permits only localhost and loopback addresses.

## [0.5.4] - 2026-07-10

### Fixed

- Preserve the structured `invalid_input` MCP envelope with FastMCP 3.4.4 by unwrapping only
  framework validation errors whose cause is a Pydantic argument-validation failure. Unrelated
  FastMCP validation errors continue to propagate instead of being misclassified.

### Build

- Upgrade FastMCP to 3.4.4, Uvicorn to 0.51.0, Ruff to 0.15.21, mypy to 2.2.0, and the
  `astral-sh/setup-uv` workflows to the immutable v8.3.2 commit.

## [0.5.3] - 2026-07-07

### Security

- **CORS credentials are now forced off.** This backend is unauthenticated by design
  (no cookies or session), so CORS credentials are meaningless; the `allow_credentials`
  default is now `False` and the middleware always installs with credentials disabled.
  The dangerous wildcard-origin + credentials combination now fails loud at startup
  (`RuntimeError`) instead of being silently downgraded, tightening the Container
  Hardening Standard v1 posture.

## [0.5.2] - 2026-07-03

### Fixed

- **MCP `serverInfo.version` now advertises the package version.** The `initialize`
  handshake previously reported the FastMCP framework version (`3.4.2`) because the
  `FastMCP(...)` constructor was created without a `version=` argument; it now passes
  the metadata-derived `gencc_link.__version__`, so `serverInfo.version` matches
  `/health` and the installed package version. Added a single-source guard
  (`tests/unit/test_version_single_source.py`) tying `pyproject` -> installed metadata
  -> `__version__` -> `serverInfo.version` to one value.

## [0.5.1] - 2026-06-29

### Security

- Adopt GeneFoundry Container & Deployment Hardening Standard v1: digest-pinned base
  image, new `.dockerignore`, `prod` overlay now sets a read-only rootfs + tmpfs with
  writes confined to the `/app/data` database volume (closing the prior `read_only`
  gap), CORS no longer combines wildcard origins with credentials, and a CI container
  scan (Trivy) + SBOM workflow.

## [0.5.0] - 2026-06-15

Adopts the **GeneFoundry Tool-Naming & Normalization Standard v1** (issue #3) and
lands two dependency bumps. See
`docs/superpowers/specs/2026-06-15-tool-naming-standard-v1-design.md`. All 12 tool
names were already compliant (canonical verbs, unprefixed, <=50 chars), so this
release adds the guardrail, aligns argument names to the fleet canon, and
documents the gateway namespace.

### Changed

- **BREAKING -- fleet-canonical gene arguments.** `get_gene_curations`,
  `get_gene_disease_assertion`, and `find_curations` no longer accept `gene`. Pass
  `gene_symbol` (approved symbol, e.g. `SKI`) **or** `hgnc_id` (HGNC CURIE, e.g.
  `HGNC:10896`) instead -- exactly one is required on the first two tools; at most
  one acts as a filter on `find_curations`. There is no deprecation alias (the
  project is pre-1.0). Batch `get_genes_curations` keeps its polymorphic `genes`
  list (symbols or HGNC CURIEs; no fleet-canon plural exists). `_meta.next_commands`
  and error-recovery commands now emit `hgnc_id` for resolved identifiers.
- `parameter_conventions` in the capabilities surface documents `gene_symbol` /
  `hgnc_id` in place of `gene` (this changes `capabilities_version`).

### Added

- **Tool-Naming Standard v1 CI guard** (`tests/test_tool_naming.py`): asserts
  every registered tool name matches `^[a-z0-9_]{1,50}$`, starts with a canonical
  verb (`get`/`search`/`list`/`resolve`/`find`/`compare`/`compute`, plus the
  documented action-verb exceptions), and carries a domain tag -- mirroring
  `genefoundry-router`'s `check_leaf_name` so the gateway and every leaf agree.
- **README "GeneFoundry federation" section** documenting the `gencc` gateway
  namespace token, the `serverInfo.name`, the unprefixed-leaf policy, and the
  canonical argument names.

### Build

- `uvicorn[standard]` floor raised to `0.49.0`; `mcp[cli]` floor raised to
  `1.27.2` (`uv.lock` regenerated; supersedes dependabot PR #2).
- Docker base image bumped `python:3.12-slim` -> `python:3.14-slim`; trove
  classifiers advertise Python 3.14 (supersedes dependabot PR #1).

## [0.4.0] - 2026-06-12

Consumer-uplift release (target >9.5/10): resolves every finding in the fresh
v0.3.0 consumer assessment (`docs/mcp-consumer-assessment-v0.3.0.md`, scored
9/10) — see `docs/superpowers/specs/2026-06-12-mcp-consumer-uplift-v0.4.0-design.md`.
No functional bugs were found; the changes are token-efficiency, paging
consistency, message accuracy, and documentation completeness.

### Changed

- **Full-mode payload de-duplication (the biggest token win).**
  `get_gene_disease_assertion` full mode no longer emits a pair-level union
  `pmids` (it triplicated per-submitter PMIDs), and the raw `submissions[]` array
  is slimmed to raw-extras only (`sgc_id`, `notes`, original disease ids,
  `version_number`, `submitted_run_date`, per-row classification/MOI/PMIDs) — the
  harmonized fields and pair-constant disease identity now come from
  `submitters[]`/the parent. `get_gene_curations`/`get_disease_curations` full
  mode likewise drop the per-pair union `pmids`. Correlate a submission row to a
  submitter via `submitter_title`. (Assessment Part-1 #1, Part-2 #5)
- **Error envelopes carry `citation_ref` only** — no verbatim
  `recommended_citation` and no `citation_short` (an error has no claim to cite).
  `data_license` is now emitted in per-call `_meta` only in `full` mode (it is
  session-invariant, already in `citation_short` and the capabilities contract);
  `unsafe_for_clinical_use` still rides every envelope. (Part-1 #2/#3, Part-2 #6)

### Added

- **Uniform refresh-safe paging.** `search_genes`, `search_diseases`,
  `get_gene_curations`, and `get_disease_curations` now accept a release-bound,
  opaque `cursor` and mint `truncated.next_cursor` (surfaced as the first
  `_meta.next_commands` entry), matching `find_curations`. A cursor minted under a
  prior GenCC release is rejected as `invalid_input` so a weekly refresh can't
  silently skip or duplicate rows mid-sweep. Batch `get_genes_curations` /
  `get_diseases_curations` remain non-paged. (Part-2 #4)
- **Batch dedup observability.** `get_genes_curations` / `get_diseases_curations`
  echo `received` (raw input length) and a `duplicates[]` block of folded values;
  the headline notes folding. (Part-2 #2)
- **Capabilities documentation.** `tool_defaults` (per-tool default
  `response_mode`), `conflict_semantics` (supporting/against/excluded tiers),
  annotated `error_codes` (`operational_only` flags for ingest/quota-only codes)
  plus a back-compat `error_codes_list`, and a reachable `ambiguous_query_example`.
  (Part-1 #5, Part-2 #7, #8)

### Fixed

- `resolve_identifier` not-found message now reflects the `kind` scope
  ("…to a GenCC disease." for `kind='disease'`), not always "gene or disease".
  (Part-2 #1)
- `resolve_identifier` rejects conflicting `query`/`identifier` aliases with
  `invalid_input` instead of silently dropping `identifier`. (Part-2 #3)

### Internal

- Shared `decode_paged_cursor` (release-stale rejection) in `services/cursor.py`;
  `find_curations` refactored onto it. Pure batch hygiene extracted to
  `services/batch.py` to keep `gencc_service.py` under the 600-line cap.

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
