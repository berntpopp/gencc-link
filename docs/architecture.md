# GenCC-Link Architecture

GenCC-Link grounds **gene-disease validity** questions in the **Gene Curation
Coalition (GenCC)** dataset. GenCC aggregates curated gene-disease assertions
from member organizations (ClinGen, Genomics England PanelApp, Orphanet, Ambry,
Invitae, Illumina, and others), each stating a **classification**
(Definitive through Refuted) for a gene + disease + mode of inheritance, with
links to evidence (PMIDs, public reports, assertion criteria).

The server's value over a raw download: it **harmonizes and aggregates**
assertions across submitters, surfaces **consensus and conflicts** for each
gene-disease pair, and serves it in a fast, token-efficient, agent-discoverable
way that matches the sibling `*-link` MCP family.

It is a research tool. **Not for clinical decision-making.**

## Why SQLite (no live API)

GenCC has **no live API** — access is via a single weekly bulk export
(~24MB TSV, CC0). The data is small, slow-changing, and fully self-contained.
So instead of an upstream HTTP client with rate limiting and caching (the
pattern used by API-backed siblings like gtex-link), GenCC-Link builds a local
**SQLite + FTS5** artifact once and queries it in-process:

- queries are local, deterministic, and sub-millisecond — no network at query
  time, no upstream rate limits, no flaky external dependency;
- the build is an explicit, idempotent ETL step that can be refreshed weekly;
- aggregation (consensus, conflict) is precomputed at build time, so tools just
  read derived rows.

Embeddings / semantic search are out of scope: exact identifier resolution plus
FTS5 full-text search over symbols and disease titles is sufficient.

## Components and data flow

```
                 thegencc.org bulk export (weekly, ~24MB TSV, CC0)
                                  |
                                  v
  ingest/  ┌──────────────────────────────────────────────────────────┐
           │  downloader.py   conditional GET (ETag / Last-Modified),   │
           │                  quota-aware (20/IP/day; 304 + HEAD exempt)│
           │  parser.py       stream TSV -> typed rows (31-col schema)  │
           │  aggregates.py   per gene / disease / pair roll-ups        │
           │  builder.py      build gencc.sqlite.tmp, then atomic rename│
           │  cli.py          gencc-link-data build | refresh | info    │
           └──────────────────────────────────────────────────────────┘
                                  |
                                  v
  data/    ┌──────────────────────────────────────────────────────────┐
           │  SQLite + FTS5 store  (data/gencc.sqlite)                  │
           │   submissions   one row per sgc_id (31 typed columns)      │
           │   genes         derived: counts + max classification      │
           │   diseases      derived: counts + original-curie aggregates│
           │   submitters    derived: submission counts                 │
           │   gene_disease  AGGREGATED per (gene, disease):            │
           │                 consensus, has_conflict, submitter JSON,   │
           │                 classifications, MOIs, PMIDs               │
           │   genes_fts / diseases_fts   FTS5 (porter) full-text search│
           │   meta          single-row build provenance                │
           │  repository.py  GenCCRepository: read-only SQLite queries  │
           └──────────────────────────────────────────────────────────┘
                                  |
                                  v
  services/┌──────────────────────────────────────────────────────────┐
           │  consensus.py     submitter assertions -> consensus/conflict│
           │  gencc_service.py search, curations, resolution, filters   │
           │  shaping.py       response_mode shaping (minimal..full)    │
           └──────────────────────────────────────────────────────────┘
                                  |
                                  v
  mcp/     ┌──────────────────────────────────────────────────────────┐
           │  facade.py        create_gencc_mcp(): FastMCP + register   │
           │  capabilities.py  build_capabilities() + gencc:// resources│
           │  envelope.py      run_mcp_tool(), error classification     │
           │  next_commands.py ready-to-call {tool, arguments} chains   │
           │  tools/           discovery, genes, diseases, assertions,  │
           │                   submitters  (10 MCP tools)               │
           └──────────────────────────────────────────────────────────┘
                                  |
        ┌─────────────────────────┴─────────────────────────┐
        v                                                     v
  app.py (FastAPI: /health, /, /docs)            server_manager.py
        \                                          (transport dispatch)
         └──────────────► unified | http | stdio ◄┘
```

## Layers

1. **Ingest** (`gencc_link/ingest/`)
   - `downloader.py` — conditional GET with `If-None-Match` / `If-Modified-Since`,
     respects the GenCC daily download quota.
   - `parser.py` — streams the 31-column new-format TSV into typed rows, validating
     the header against the authoritative column order in `constants.py`.
   - `aggregates.py` — computes per-gene, per-disease, per-submitter, and
     per-(gene, disease) roll-ups.
   - `builder.py` — builds `gencc.sqlite.tmp` (schema, rows, aggregates, FTS5),
     then atomically renames it into place; writes the `meta` provenance row.
   - `cli.py` — the `gencc-link-data` console script (`build` / `refresh` / `info`).

2. **Data store** (`gencc_link/data/`)
   - `schema.sql` — DDL for `submissions`, `genes`, `diseases`, `submitters`,
     the aggregated `gene_disease` table, the `genes_fts` / `diseases_fts` FTS5
     indexes, and the single-row `meta` table.
   - `repository.py` — `GenCCRepository`, a read-only SQLite query layer opened
     with `mode=ro`.

3. **Services** (`gencc_link/services/`)
   - `consensus.py` — turns a set of submitter assertions into a consensus
     classification and a conflict flag (see the consensus/conflict model below).
   - `gencc_service.py` — business logic: gene/disease search, gene and disease
     curations, single-pair assertion detail, filtered curation search,
     submitter listing, identifier resolution.
   - `shaping.py` — `response_mode` shaping across minimal / compact / standard / full.

4. **MCP layer** (`gencc_link/mcp/`)
   - `facade.py` — builds the FastMCP server and registers all tools, resources,
     and annotations.
   - `capabilities.py` — `build_capabilities()` and the `gencc://` resource family
     (`capabilities`, `usage`, `reference`, `license`, `citation`, `research-use`).
   - `envelope.py` — wraps every tool in a typed response envelope with error
     classification and a base `_meta` block.
   - `next_commands.py` — builds the `_meta.next_commands` ready-to-call chains.
   - `tools/` — the 10 MCP tools grouped by concern (discovery, genes, diseases,
     assertions, submitters).

5. **Server** (`gencc_link/app.py`, `gencc_link/server_manager.py`)
   - `app.py` — FastAPI factory exposing `/health` (and `/api/health`), `/`,
     `/docs`, `/redoc`, `/openapi.json`, with CORS.
   - `server_manager.py` — `UnifiedServerManager`, the single entry point for the
     three transports.

6. **Configuration** (`gencc_link/config.py`)
   - Pydantic-settings with the `GENCC_LINK_` env prefix and nested `data` config
     (`GENCC_LINK_DATA__*`, double-underscore delimiter).

## Transports

`server.py` (or the `gencc-link` console script) dispatches three transports via
`UnifiedServerManager`:

- **`unified`** (default) — FastAPI REST on `/` and MCP streamable HTTP on `/mcp`
  over a single port (`8000`).
- **`http`** — FastAPI REST only.
- **`stdio`** — FastMCP over stdio, for Claude Desktop and similar local clients
  (also exposed as the `gencc-link-mcp` console script via `mcp_server.py`).

## Consensus / conflict model

Each GenCC harmonized classification has a numeric rank (high = strong positive
evidence, low = evidence against). Animal-model-only and no-known-relationship
get sentinel low ranks so they never win a consensus:

| Classification | Rank |
|----------------|------|
| Definitive | 6 |
| Strong | 5 |
| Moderate | 4 |
| Supportive | 3 |
| Limited | 2 |
| Disputed Evidence | 1 |
| Refuted Evidence | 0 |
| Animal Model Only | -1 |
| No Known Disease Relationship | -2 |

For each gene-disease pair:

- **`strongest_classification`** = the classification with the highest rank among
  all submitters for that pair (it is *not* an agreement measure — read
  `has_conflict` and `min_classification` for disagreement and the range). Surfaced
  to consumers under this name; the underlying `gene_disease` DB column is still
  named `consensus_classification`.
- **`has_conflict`** = `true` when at least one submitter asserts a *supporting*
  classification (Definitive / Strong / Moderate) **and** at least one other
  submitter asserts an *against* classification (Disputed Evidence /
  Refuted Evidence / No Known Disease Relationship). `Animal Model Only` is
  excluded from both sides — it is weak/orthogonal evidence, not a contradiction.

Conflict detection is the headline differentiator: it is precomputed into the
`gene_disease` table and surfaced prominently in each tool's `headline` and in
`_meta`.

## Bootstrap and refresh

- The ETL is explicit: `make data` runs `gencc-link-data build` (forced download +
  rebuild). `gencc-link-data refresh` rebuilds only if GenCC published a newer
  export (conditional request). `gencc-link-data info` prints provenance.
- On server startup, if the database is missing and
  `GENCC_LINK_DATA__AUTO_BOOTSTRAP=true` (default), the server builds it on first
  use by downloading the export. Otherwise data-dependent tools return a typed
  `data_unavailable` envelope telling the agent to run `make data`.
- The `meta` row records the source ETag, `Last-Modified`, GenCC run date, row /
  gene / disease / submitter counts, schema version, and build timestamp.
  `get_gencc_diagnostics` reports this freshness.

## Error taxonomy

`invalid_input`, `not_found`, `ambiguous_query`, `data_unavailable`,
`upstream_unavailable` (download), `rate_limited` (quota), `internal_error`.
Error details are masked; the base `_meta` carries the research-use and license
markers.
