# GenCC-Link

MCP + FastAPI server that grounds **gene-disease validity** questions in the
**Gene Curation Coalition (GenCC)** dataset — harmonized, aggregated, and served
with consensus and conflict detection.

> Research use only. **Not** for diagnosis, treatment, triage, patient
> management, or clinical decision support.

## Features

- **GenCC gene-disease validity** harmonized across member submitters (ClinGen,
  Genomics England PanelApp, Orphanet, Ambry, Invitae, Illumina, and others).
- **Consensus + conflict detection** — for each gene-disease pair, the consensus
  classification and a flag when supporting and against assertions coexist.
- **Local SQLite + FTS5 store** built from the weekly GenCC bulk export — fast,
  deterministic, no upstream API at query time.
- **10 MCP tools** with token-efficient `response_mode` shaping, plain-English
  headlines, and ready-to-call `_meta.next_commands` chains.
- **Three transports** from one codebase: `unified` (REST + MCP), `http`, `stdio`.
- **Agent-discoverable** — `gencc://` capabilities, usage, reference, license, and
  citation resources; typed error envelopes; verbatim recommended citation.

## Data source & license

GenCC has **no live API**; data is distributed as a single bulk export.

- **Source:** Gene Curation Coalition bulk submissions export (new format) from
  [thegencc.org](https://thegencc.org), ~24MB TSV, updated **weekly**.
- **Data license:** **CC0 1.0** (public domain). Attribution to GenCC and the
  contributing sources is **requested**.
- **OMIM restriction:** OMIM disease text is restricted where licensing forbids,
  so the `disease_original_*` OMIM fields may be absent — this is expected.
- **Not clinical:** GenCC data is not intended for direct diagnostic use or
  medical decision-making without review by a genetics professional.

## Quick start

```bash
# Install uv if needed
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install project and dev dependencies
uv sync

# Build the local SQLite database from the GenCC export (~24MB download)
make data

# Start the unified REST + MCP server on http://127.0.0.1:8000
make dev

# Or start the local stdio MCP server (for Claude Desktop)
make mcp-serve
```

The database is built into `<repo>/data/gencc.sqlite` by default. With
`GENCC_LINK_DATA__AUTO_BOOTSTRAP=true` (the default), the HTTP / unified server
also builds the database on first use if it is absent, so `make data` is optional
but recommended for a predictable first boot.

Database management commands:

```bash
make data          # gencc-link-data build   — force download + rebuild
make data-refresh  # gencc-link-data refresh — rebuild only if export changed
make data-info     # gencc-link-data info    — print build provenance
```

## Connecting Claude Code & Claude Desktop

See [`docs/MCP_CONNECTION_GUIDE.md`](docs/MCP_CONNECTION_GUIDE.md) for the full
guide. Streamable HTTP at `/mcp` is recommended; stdio is a local fallback.

### Claude Code (HTTP)

```bash
make dev
claude mcp add --transport http gencc-link http://127.0.0.1:8000/mcp
```

### Claude Desktop (HTTP)

```json
{
  "mcpServers": {
    "gencc-link": {
      "type": "http",
      "url": "http://127.0.0.1:8000/mcp"
    }
  }
}
```

### Claude Desktop (stdio)

```json
{
  "mcpServers": {
    "gencc-link": {
      "command": "gencc-link-mcp",
      "env": {
        "PYTHONUNBUFFERED": "1",
        "GENCC_LINK_LOG_LEVEL": "WARNING"
      }
    }
  }
}
```

Or run stdio from a checkout with `uv` (no install step):

```json
{
  "mcpServers": {
    "gencc-link": {
      "command": "uv",
      "args": ["run", "python", "mcp_server.py"],
      "cwd": "/absolute/path/to/gencc-link"
    }
  }
}
```

## Available MCP tools

| Tool | Purpose |
|------|---------|
| `get_server_capabilities` | Tool inventory, classification ranks, response modes, data freshness |
| `get_gencc_diagnostics` | Build provenance + row/gene/disease/submitter counts |
| `search_genes` | Resolve symbol / HGNC id / partial text to genes (FTS) |
| `search_diseases` | Resolve title / MONDO / OMIM id to diseases (FTS) |
| `get_gene_curations` | All gene-disease assertions for a gene, with consensus + conflict |
| `get_disease_curations` | All genes asserted for a disease, with consensus |
| `get_gene_disease_assertion` | One pair: per-submitter classifications, MOI, PMIDs, URLs + conflict analysis |
| `find_curations` | Filter assertions by classification/submitter/MOI/conflict |
| `list_submitters` | Submitting organizations + counts |
| `resolve_identifier` | Map free text to canonical HGNC/MONDO ids |

Tools whose payloads vary accept `response_mode`: `minimal` | `compact`
(default) | `standard` | `full`. See [`docs/usage.md`](docs/usage.md) for the
canonical workflows and the citation contract.

## Architecture

GenCC is small, slow-changing bulk data with no live API, so GenCC-Link builds a
local **SQLite + FTS5** artifact once and queries it in-process — no upstream
client, rate limiting, or caching against an external API at query time.

```
ingest (download -> parse -> aggregate -> build) -> SQLite + FTS5 store
  -> repository (read-only) -> service (search / curations / consensus)
  -> MCP tools  +  FastAPI (/health, /, /docs)
  -> transports: unified | http | stdio
```

Full details, the consensus/conflict model, and an ASCII diagram are in
[`docs/architecture.md`](docs/architecture.md).

## Configuration

Settings load from environment variables prefixed `GENCC_LINK_` (nested data
config uses a double underscore) and an optional `.env` file. Copy
[`.env.example`](.env.example) and adjust. Key variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `GENCC_LINK_HOST` | `127.0.0.1` | Server host |
| `GENCC_LINK_PORT` | `8000` | Server port |
| `GENCC_LINK_TRANSPORT` | `unified` | `unified` \| `http` \| `stdio` |
| `GENCC_LINK_MCP_PATH` | `/mcp` | MCP endpoint path |
| `GENCC_LINK_LOG_LEVEL` | `INFO` | Logging level |
| `GENCC_LINK_LOG_FORMAT` | `console` | `console` or `json` |
| `GENCC_LINK_DATA__SOURCE_FORMAT` | `new` | GenCC export format (`new` \| `legacy`) |
| `GENCC_LINK_DATA__DATA_DIR` | `<repo>/data` | Directory for the built database |
| `GENCC_LINK_DATA__DB_FILENAME` | `gencc.sqlite` | SQLite filename in the data dir |
| `GENCC_LINK_DATA__AUTO_BOOTSTRAP` | `true` (image: `false`) | Build the database lazily on first use if absent |
| `GENCC_LINK_DATA__REFRESH_ENABLED` | `true` | Run the in-app conditional-refresh scheduler (unified/http only) |
| `GENCC_LINK_DATA__REFRESH_INTERVAL_HOURS` | `24` | Hours between conditional refresh checks |
| `GENCC_LINK_DATA__REFRESH_JITTER_SECONDS` | `300` | Random jitter added to each refresh |
| `GENCC_LINK_DATA__BUILD_LOCK_TIMEOUT` | `600` | Seconds to wait for the cross-process build lock |
| `GENCC_LINK_DATA__DOWNLOAD_TIMEOUT` | `120` | Download timeout (seconds) |
| `GENCC_LINK_DATA__CACHE_SIZE` | `512` | Query cache entries (0 disables) |
| `GENCC_LINK_DATA__CACHE_TTL` | `3600` | Query cache TTL (seconds) |

See [`docs/data-lifecycle.md`](docs/data-lifecycle.md) for how the database is
built on startup and refreshed on a schedule (in-app scheduler, cron sidecar, or
Kubernetes CronJob).

## Development

```bash
make install      # install project + dev dependencies (uv sync --group dev)
make ci-local     # format-check, lint, file-size budget, typecheck, fast tests
make test         # run tests (excludes integration)
make test-cov     # run tests with coverage (gate: 85%)
make lint         # ruff lint
make lint-loc     # enforce the per-file line budget (scripts/check_file_size.py)
make typecheck    # mypy strict
```

`make ci-local` is the gate to run before every commit. The project uses `uv`,
Ruff (100 cols), mypy strict, and a per-file line budget enforced by
`scripts/check_file_size.py`. Integration tests (`-m integration`) hit the live
GenCC download endpoint and are excluded from the default runs. Agentic coding
tools should follow `AGENTS.md`; Claude Code also loads the lean `CLAUDE.md`.

## Docker deployment

```bash
make docker-build           # build the image
make docker-up              # start the unified server on host port 8000
curl http://localhost:8000/health
make docker-logs
make docker-down
```

The container's **entrypoint builds the database once on startup** (before the
server accepts traffic), and an **in-app scheduler** conditionally refreshes it
every 24h and hot-reloads the running server — so first-request latency is
predictable and the daily download quota is respected. The built ~24MB database
lives in the `gencc-data` named volume at `/app/data` and persists across
restarts (a restart re-uses it; the conditional request returns `304`).

For a dedicated scheduler instead of the in-app loop, use the cron sidecar
overlay:

```bash
docker compose -f docker/docker-compose.yml -f docker/docker-compose.cron.yml up -d
```

Kubernetes manifests (initContainer + in-app scheduler, or an external CronJob)
are in [`deploy/k8s/`](deploy/k8s/). The full strategy and all scheduling options
are documented in [`docs/data-lifecycle.md`](docs/data-lifecycle.md). See
[`docker/README.md`](docker/README.md) for the production overlay.

## License & citation

- **Code:** MIT — see [`LICENSE`](LICENSE).
- **Data:** **CC0 1.0** (public domain), from GenCC ([thegencc.org](https://thegencc.org));
  attribution requested.

Cite GenCC as:

> DiStefano MT, et al. The Gene Curation Coalition. Genet Med. 2022;24(8):1732-1742.
> doi:10.1016/j.gim.2022.04.017

## Acknowledgments

- [Gene Curation Coalition (GenCC)](https://thegencc.org) and its contributing
  member organizations.
- [Model Context Protocol](https://modelcontextprotocol.io/),
  [FastMCP](https://github.com/jlowin/fastmcp),
  [FastAPI](https://fastapi.tiangolo.com/), and
  [Pydantic](https://pydantic.dev/).

---

**Research use only.** GenCC-Link is a research tool and must not be used for
diagnosis, treatment, triage, patient management, or clinical decision support.
GenCC data is not intended for direct diagnostic use or medical decision-making
without review by a genetics professional.
