# GenCC-Link — Design Spec

**Date:** 2026-06-12
**Status:** Approved for implementation (autonomous build)
**Author:** Claude (MCP engineer)

## 1. Purpose

`gencc-link` is a Model Context Protocol (MCP) server that grounds **gene–disease
validity** questions in the **Gene Curation Coalition (GenCC)** dataset. GenCC
aggregates curated gene–disease assertions from member organizations (ClinGen,
Genomics England PanelApp, Orphanet, Ambry, Invitae, Illumina, etc.), each
stating a **classification** (Definitive → Refuted) for a gene + disease + mode
of inheritance, with links to evidence (PMIDs, public reports, assertion
criteria).

The server's distinctive value over a raw download: it **harmonizes and
aggregates** assertions across submitters, surfaces **consensus and conflicts**
for each gene–disease pair, and serves it in a **fast, token-efficient,
agent-discoverable** way that matches the sibling `*-link` MCP family.

It is a research tool. **Not for clinical decision-making.**

## 2. Data source (researched 2026-06-12)

GenCC has **no live API yet** ("coming soon"). Access is via bulk export.

**Download URLs (new format — recommended):**
- TSV: `https://thegencc.org/download/action/submissions-export-tsv?format=new`
- CSV: `https://thegencc.org/download/action/submissions-export-csv?format=new`
- XLSX: `https://thegencc.org/download/action/submissions-export-xlsx?format=new`

**Verified properties (HEAD, 2026-06-12):**
- `Content-Type: text/tab-separated-values`, ~24.5 MB, filename `gencc-submissions.tsv`
- `ETag` (MD5) + `Last-Modified` present; `Accept-Ranges: bytes` (Range supported)
- Conditional requests supported: `If-None-Match` (ETag) and `If-Modified-Since`
- **Quota: 20 downloads / IP / day.** `304 Not Modified` does **not** count; `HEAD` is exempt.
- Per-minute soft limit visible via `X-RateLimit-*` headers (~60/min).
- Updated **weekly**.
- License: **CC0 1.0** (public domain) for the data; attribution requested. No OMIM
  disease names where licensing forbids (the `disease_original_*` OMIM fields are present
  but OMIM text is restricted — handle gracefully).

**TSV schema (31 columns, verified from live export):**

| # | column | meaning |
|---|--------|---------|
| 1 | `sgc_id` | stable submission id (e.g. `SGC-100001`) — primary key |
| 2 | `version_number` | submission version |
| 3 | `gene_curie` | harmonized gene id (`HGNC:10896`) |
| 4 | `gene_symbol` | harmonized symbol (`SKI`) |
| 5 | `disease_curie` | harmonized disease id (`MONDO:0008426`) |
| 6 | `disease_title` | harmonized disease label |
| 7 | `disease_original_curie` | as-submitted disease id (often `OMIM:...`) |
| 8 | `disease_original_title` | as-submitted disease label |
| 9 | `classification_curie` | harmonized classification id (`GENCC:100001`) |
| 10 | `classification_title` | Definitive / Strong / Moderate / Limited / Supportive / Disputed Evidence / Refuted Evidence / Animal Model Only / No Known Disease Relationship |
| 11 | `moi_curie` | mode of inheritance id (`HP:0000006`) |
| 12 | `moi_title` | e.g. Autosomal dominant |
| 13 | `submitter_curie` | harmonized submitter id (`GENCC:000101`) |
| 14 | `submitter_title` | e.g. Ambry Genetics |
| 15–24 | `submitted_as_*` | original (pre-harmonization) hgnc/disease/moi/submitter/classification id+name |
| 25 | `submitted_as_date` | submission date |
| 26 | `submitted_as_public_report_url` | evidence/report URL |
| 27 | `submitted_as_notes` | free-text notes |
| 28 | `submitted_as_pmids` | PMIDs (semicolon/`PMID:`-prefixed) |
| 29 | `submitted_as_assertion_criteria_url` | criteria URL |
| 30 | `submitted_as_submission_id` | submitter-local id |
| 31 | `submitted_run_date` | GenCC run/ingest date |

## 3. Architecture

Follows the established `*-link` family conventions (FastMCP 3.2+, FastAPI unified
server, Pydantic v2, `uv`, structlog, three transports). **Key divergence:** GenCC
is small bulk data, so the store is a **local SQLite + FTS5 artifact** built by an
ETL step — no Postgres, no embeddings, no live upstream at query time.

```
gencc-link/
├── server.py                 # unified entry (FastAPI + MCP http/stdio dispatch)
├── mcp_server.py             # stdio-only entry (silenced stdout)
├── gencc_link/
│   ├── __init__.py           # __version__
│   ├── config.py             # Settings (GENCC_LINK_* env, pydantic-settings)
│   ├── logging_config.py
│   ├── server_manager.py     # UnifiedServerManager: unified/http/stdio
│   ├── app.py                # FastAPI app factory (health + optional REST)
│   ├── exceptions.py         # typed errors (InvalidInput, NotFound, DataUnavailable…)
│   ├── constants.py          # classification rank, submitter list, download URLs
│   ├── ingest/
│   │   ├── downloader.py      # conditional GET (ETag/Last-Modified), quota-aware
│   │   ├── parser.py          # stream TSV → typed rows
│   │   ├── builder.py         # build SQLite (schema, aggregates, FTS5) atomically
│   │   └── cli.py             # `gencc-link-data build|refresh|info`
│   ├── data/
│   │   ├── schema.sql         # DDL: submissions, genes, diseases, submitters,
│   │   │                      #      gene_disease (aggregated), *_fts, meta
│   │   └── repository.py      # GenCCRepository: read-only SQLite queries
│   ├── services/
│   │   ├── gencc_service.py   # business logic: search, curations, consensus
│   │   ├── consensus.py       # aggregate submitter assertions → consensus/conflict
│   │   └── shaping.py         # response_mode shaping (minimal/compact/standard/full)
│   ├── models/
│   │   ├── enums.py           # Classification, ResponseMode
│   │   └── records.py         # Pydantic: Gene, Disease, Submission, GeneDisease…
│   └── mcp/
│       ├── facade.py          # create_gencc_mcp(): FastMCP + register all
│       ├── annotations.py     # READ_ONLY_OPEN_WORLD
│       ├── envelope.py        # run_mcp_tool(), error classification, _BASE_META
│       ├── next_commands.py   # cmd() + chain builders
│       ├── capabilities.py    # build_capabilities() + gencc:// resources
│       ├── resources.py       # usage / license / citation text
│       └── tools/
│           ├── discovery.py   # get_server_capabilities, get_gencc_diagnostics
│           ├── genes.py       # search_genes, get_gene_curations
│           ├── diseases.py    # search_diseases, get_disease_curations
│           ├── assertions.py  # get_gene_disease_assertion, find_curations
│           └── submitters.py  # list_submitters
├── tests/ (unit + integration)
├── docker/ (Dockerfile + compose variants)
├── scripts/check_file_size.py
├── .github/workflows/ (ci.yml, release.yml)
├── AGENTS.md, CLAUDE.md, Makefile, pyproject.toml, README.md, CHANGELOG.md
└── .pre-commit-config.yaml, .gitignore, .env.example
```

### Data store (SQLite)

Built artifact `data/gencc.sqlite` (gitignored; a tiny `tests/fixtures/sample.tsv`
+ built `sample.sqlite` ships for tests). Tables:

- **`submissions`** — one row per `sgc_id`, all 31 columns typed; indexed on
  `gene_curie`, `gene_symbol`, `disease_curie`, `submitter_curie`,
  `classification_title`, `moi_title`.
- **`genes`** — derived: `gene_curie`, `gene_symbol`, `n_submissions`,
  `n_diseases`, `max_classification`.
- **`diseases`** — derived: `disease_curie`, `disease_title`, `n_submissions`,
  `n_genes`, original-curie aggregates.
- **`submitters`** — derived: `submitter_curie`, `submitter_title`, `n_submissions`.
- **`gene_disease`** — **aggregated** one row per (gene_curie, disease_curie):
  `consensus_classification`, `max_classification`, `min_classification`,
  `n_submitters`, `submitter_titles` (JSON), `classifications` (JSON list),
  `moi_titles` (JSON), `has_conflict` (bool), `pmids` (JSON).
- **`genes_fts`, `diseases_fts`** — FTS5 over symbol/aliases and disease titles
  (porter tokenizer) for fast fuzzy search.
- **`meta`** — single-row build provenance: `source_etag`, `source_last_modified`,
  `gencc_run_date`, `row_count`, `gene_count`, `disease_count`, `build_utc`,
  `schema_version`, `format` (`new`).

### Consensus model

GenCC classification rank (high→low), used for consensus + conflict:
`Definitive(6) > Strong(5) > Moderate(4) > Supportive(3)/Limited(3) >
Disputed Evidence(1) > Refuted Evidence(0) > Animal Model Only(NA) >
No Known Disease Relationship(NA)`.

For each gene–disease pair: `consensus = max rank among submitters`;
`has_conflict = (a submitter asserts Definitive/Strong/Moderate) AND (another
asserts Disputed/Refuted)`. Conflict detection is the headline differentiator —
exposed prominently in `_meta` and `headline`.

### Bootstrap / refresh

- ETL is explicit: `make data` → `gencc-link-data build`. Downloads with
  conditional request, builds to `gencc.sqlite.tmp`, atomically renames.
- Server startup: if DB missing and `GENCC_AUTO_BOOTSTRAP=true` (default true for
  http/unified), build synchronously with a clear log; otherwise raise a typed
  `DataUnavailableError` whose envelope tells the agent to run `make data`.
- `meta` row exposes freshness; `get_gencc_diagnostics` reports it.

## 4. MCP tools (10)

All tools: read-only, `READ_ONLY_OPEN_WORLD`, `response_mode` where payloads vary,
`_meta.next_commands` chaining, `recommended_citation`, typed error envelopes.

1. **`get_server_capabilities`** — inventory, classifications, submitters, MOIs,
   response modes, error codes, data freshness, citation. Mirrors `gencc://capabilities`.
2. **`get_gencc_diagnostics`** — build provenance, row counts, source ETag/date,
   staleness flag.
3. **`search_genes`** — free text / symbol / HGNC id → ranked genes with assertion
   summary (n_diseases, max classification). FTS-backed.
4. **`search_diseases`** — free text / MONDO / OMIM id → diseases with gene counts.
5. **`get_gene_curations`** — all gene–disease assertions for a gene, grouped by
   disease, each with consensus + per-submitter breakdown (depth by response_mode).
6. **`get_disease_curations`** — all genes curated for a disease, with consensus.
7. **`get_gene_disease_assertion`** — deep dive on one gene+disease: every
   submitter's classification, MOI, PMIDs, report URL, criteria URL, dates +
   consensus & conflict analysis.
8. **`find_curations`** — filter assertions by classification(s), submitter(s),
   MOI, gene/disease, with pagination (e.g. "Definitive AD genes from ClinGen").
9. **`list_submitters`** — submitting organizations + submission counts.
10. **`resolve_identifier`** — map gene symbol↔HGNC and disease label↔MONDO to
    canonical ids (lightweight; complements search for exact resolution).

### Token efficiency
- `response_mode`: `minimal` (ids+headline) | `compact` (default) | `standard` |
  `full` (raw submission rows incl. notes).
- Plain-English `headline` per response (e.g. "BRCA1 — 3 diseases; 2 Definitive,
  1 conflict").
- Pagination (`limit`/`offset`) on search & `find_curations`; truncation contract
  (`truncated` block with re-call hint).
- `_meta.next_commands` ready-to-call chains; `recommended_citation` verbatim.

### Resources
`gencc://capabilities` (JSON), `gencc://usage`, `gencc://license` (CC0 + sources),
`gencc://citation`, `gencc://reference` (classification ranks, error taxonomy,
field glossary, submitter list).

## 5. Conventions (match family)

Python ≥3.12; FastMCP ≥3.2; FastAPI+uvicorn; Pydantic v2 + pydantic-settings;
httpx; structlog; orjson; typer; `uv` + hatchling; Ruff (100 cols) + mypy strict;
600-LOC/file budget (`scripts/check_file_size.py`); pytest + pytest-asyncio +
pytest-xdist + respx, coverage gate **85%**; `make ci-local`; multi-stage Docker;
`.github` CI; AGENTS.md + thin CLAUDE.md; `.claude/skills/`. **Code: MIT. Data: CC0.**

## 6. Error taxonomy
`invalid_input`, `not_found`, `ambiguous_query`, `data_unavailable`,
`upstream_unavailable` (download), `rate_limited` (quota), `internal_error`.
`mask_error_details=True`; `_BASE_META` carries `unsafe_for_clinical_use: true`,
`gencc_release` (run date), `license: CC0-1.0`.

## 7. Testing
- Unit: build SQLite from `tests/fixtures/sample.tsv` (curated ~30 rows covering
  consensus, conflict, multi-submitter, OMIM-restricted disease); assert
  repository, service, consensus, shaping, every tool, envelope, next_commands.
- Integration (`@pytest.mark.integration`): live HEAD + conditional download +
  full build; quota-respecting (single run).
- Fakes: in-memory SQLite repository fixture.

## 8. Out of scope (YAGNI)
Live GenCC API (doesn't exist yet — add when released), embeddings/semantic search
(exact + FTS suffices), write/curation operations, OMIM disease text, auth.

## 9. Build phases
1. Scaffold + conventions + contracts (models, schema, interfaces).
2. Ingest pipeline (download + parse + build SQLite).
3. Repository + service + consensus + shaping.
4. MCP layer (facade, tools, capabilities, next_commands, resources, envelope).
5. Server wiring (entrypoints, transports, bootstrap) + tests + coverage.
6. Docker, CI, docs, smoke test, verification.
