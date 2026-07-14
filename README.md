# gencc-link

[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![CI](https://github.com/berntpopp/gencc-link/actions/workflows/ci.yml/badge.svg)](https://github.com/berntpopp/gencc-link/actions/workflows/ci.yml)
[![Conformance](https://github.com/berntpopp/gencc-link/actions/workflows/conformance.yml/badge.svg)](https://github.com/berntpopp/gencc-link/actions/workflows/conformance.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

An **MCP** (Model Context Protocol) server that grounds gene-disease validity
questions in the **Gene Curation Coalition ([GenCC](https://thegencc.org))**
dataset — harmonized across member submitters, with consensus and conflict
detection per gene-disease pair.

> [!IMPORTANT]
> Research use only. Not clinical decision support. Do not use for diagnosis,
> treatment, triage, or patient management.

## Why

GenCC has **no live API**. It ships as a single ~24MB bulk TSV, republished
weekly and rate-limited to 20 downloads per IP per day — so an agent cannot query
it at all, and a naive integration burns the quota re-downloading it.

Worse, the export is *submission-level*: one row per submitter assertion. It
answers "who said what", never "what does the field think". The judgement a
clinician or curator actually wants — *is this gene-disease pair settled, and do
the curators disagree?* — has to be computed.

GenCC-Link builds a local **SQLite + FTS5** artifact from that export (fetched
conditionally, so an unchanged week costs a `304` and no quota), and precomputes
per pair the `strongest_classification` (highest rank across submitters) and a
`has_conflict` flag when supporting and against assertions coexist. Queries are
local, deterministic, and need no upstream at query time.

## Quick start

Hosted, no install:

```bash
claude mcp add --transport http gencc-link https://gencc-link.genefoundry.org/mcp
```

Locally (Python 3.12+, [uv](https://github.com/astral-sh/uv)) — **`make data` is
the one required step**, the server has no data until the export is downloaded
and the database built:

```bash
uv sync --group dev
make data                     # download the GenCC export, build data/gencc.sqlite
make dev                      # unified REST + MCP server on http://127.0.0.1:8000
claude mcp add --transport http gencc-link http://127.0.0.1:8000/mcp
```

`make mcp-serve` starts the stdio server instead (Claude Desktop; see the
[MCP connection guide](docs/MCP_CONNECTION_GUIDE.md)). `AUTO_BOOTSTRAP` is on by
default outside the container, so the HTTP server *will* build the database on
first use if you skip `make data` — at the cost of a slow, surprising first
request. `make data-refresh` rebuilds only if GenCC published a newer export;
`make data-info` prints build provenance.

## Tools

| Tool | Purpose |
|------|---------|
| `get_server_capabilities` | Tool inventory, classification ranks, response modes, data freshness |
| `get_gencc_diagnostics` | Build provenance, row/gene/disease/submitter counts, download-quota headroom |
| `search_genes` | Resolve symbol / HGNC id / partial text to genes (FTS) |
| `search_diseases` | Resolve title / MONDO / OMIM id to diseases (FTS) |
| `resolve_identifier` | Map free text to canonical HGNC / MONDO ids |
| `get_gene_curations` | Every gene-disease assertion for a gene, with strongest classification + conflict |
| `get_disease_curations` | Every gene asserted for a disease, with strongest classification + conflict |
| `get_genes_curations` | Batch `get_gene_curations`: up to 20 genes per call (misses in `unresolved`) |
| `get_diseases_curations` | Batch `get_disease_curations`: up to 20 diseases per call (misses in `unresolved`) |
| `get_gene_disease_assertion` | One pair: per-submitter classifications, MOI, PMIDs, URLs + conflict analysis |
| `find_curations` | Filter assertions by classification / submitter / MOI / conflict (validated enums, `ids_only` paging, refresh-safe `cursor`) |
| `list_submitters` | Submitting organizations and their submission counts |

Leaf names are unprefixed per **Tool-Naming Standard v1** — namespacing is the
gateway's job. Behind [genefoundry-router](https://github.com/berntpopp/genefoundry-router)
they surface as `gencc_<tool>` (e.g. `gencc_search_genes`). Tools whose payloads
vary accept `response_mode`: `minimal` | `compact` (default) | `standard` |
`full`; see [usage](docs/usage.md) for the workflows, the validated filters, and
the citation contract.

## Data & provenance

- **Source:** the GenCC bulk submissions export (new format) from
  [thegencc.org](https://thegencc.org) — ~24MB TSV, republished **weekly**, no
  live API.
- **Refresh:** conditional (`ETag` / `Last-Modified`). An in-app scheduler checks
  daily and hot-reloads on change; a cron sidecar or Kubernetes CronJob can own it
  instead. Unchanged exports return `304`, which is exempt from GenCC's
  **20 downloads per IP per day** quota — as is `HEAD`. See
  [data lifecycle](docs/data-lifecycle.md).
- **Data licence:** **CC0 1.0** (public domain). Attribution to GenCC and its
  contributing member organizations (ClinGen, Genomics England PanelApp,
  Orphanet, Ambry, Invitae, Illumina, and others) is **requested**.
- **OMIM restriction:** OMIM disease text is withheld where licensing forbids it,
  so `disease_original_*` OMIM fields may be absent. Expected, not a bug.
- **Not clinical:** GenCC data is not intended for direct diagnostic use or
  medical decision-making without review by a genetics professional.

Cite GenCC as:

> DiStefano MT, et al. The Gene Curation Coalition. Genet Med.
> 2022;24(8):1732-1742. doi:10.1016/j.gim.2022.04.017

## Documentation

- [Usage](docs/usage.md) — canonical workflows, `response_mode`, conflict reading, citation contract, `gencc://` resources.
- [MCP connection guide](docs/MCP_CONNECTION_GUIDE.md) — Claude Code and Claude Desktop (HTTP and stdio) configs, verification, troubleshooting.
- [Architecture](docs/architecture.md) — why SQLite, the consensus/conflict model, transports, error taxonomy, the federation contract.
- [Configuration](docs/configuration.md) — every `GENCC_LINK_*` variable (a test owns that claim), the Host/Origin request guard, and CORS.
- [Deployment](docs/deployment.md) — Docker, Compose overlays, Kubernetes, reverse proxy, quota safety.
- [Data lifecycle](docs/data-lifecycle.md) — build-on-startup, refresh strategies, hot reload.
- [Changelog](CHANGELOG.md) · [AGENTS.md](AGENTS.md) — engineering conventions for agentic tools.

## Contributing

See [`AGENTS.md`](AGENTS.md) for engineering conventions, the domain notes, and
the file-size budget. `make ci-local` is the definition-of-done gate: format,
lint, line budget, README standard, mypy, and tests.

## License

[MIT](LICENSE) © GenCC-Link Contributors. GenCC **data** is
[CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/) (public domain)
from [thegencc.org](https://thegencc.org); attribution requested.
