# Configuration

Settings load from environment variables prefixed `GENCC_LINK_` and an optional
`.env` file. **Nested data config uses a double underscore** (e.g.
`GENCC_LINK_DATA__DB_FILENAME`). Copy [`.env.example`](../.env.example) and adjust.

## Server

| Variable | Default | Description |
|----------|---------|-------------|
| `GENCC_LINK_HOST` | `127.0.0.1` | Server host |
| `GENCC_LINK_PORT` | `8000` | Server port |
| `GENCC_LINK_TRANSPORT` | `unified` | `unified` \| `http` \| `stdio` |
| `GENCC_LINK_MCP_PATH` | `/mcp` | MCP endpoint path |
| `GENCC_LINK_LOG_LEVEL` | `INFO` | Logging level |
| `GENCC_LINK_LOG_FORMAT` | `console` | `console` or `json` |

Three transports are served from one codebase: `unified` (FastAPI REST on `/`
**and** MCP streamable HTTP on `/mcp`, one port), `http` (FastAPI REST only), and
`stdio` (FastMCP over stdio, also shipped as the `gencc-link-mcp` console script
via `mcp_server.py`). See [architecture.md](architecture.md#transports).

## Request guard (Host / Origin)

| Variable | Default | Description |
|----------|---------|-------------|
| `GENCC_LINK_ALLOWED_HOSTS` | `["localhost","127.0.0.1","::1"]` | Exact `Host` values accepted by the MCP request guard |
| `GENCC_LINK_ALLOWED_ORIGINS` | `[]` | Browser `Origin` values accepted by the MCP request guard |

Both are **JSON lists of exact values** — wildcards are not accepted. In
production you MUST add the public reverse-proxy hostname to
`GENCC_LINK_ALLOWED_HOSTS` (the NPM overlay ships
`gencc-link.genefoundry.org`), or every proxied request is rejected.
`GENCC_LINK_ALLOWED_ORIGINS` gates *browser* origins only; same-origin requests
and requests without an `Origin` header (an MCP client, `curl`) remain valid, so
the default empty list is safe for non-browser deployments.

## Data source and local store

| Variable | Default | Description |
|----------|---------|-------------|
| `GENCC_LINK_DATA__SOURCE_FORMAT` | `new` | GenCC export format (`new` \| `legacy`) |
| `GENCC_LINK_DATA__DATA_DIR` | `<repo>/data` (image: `/data`) | Directory for the built database |
| `GENCC_LINK_DATA__DB_FILENAME` | `gencc.sqlite` | SQLite filename in the data dir |
| `GENCC_LINK_DATA__AUTO_BOOTSTRAP` | `true` (image: `false`) | Build the database lazily on first use if absent |
| `GENCC_LINK_DATA__REFRESH_ENABLED` | `true` | Run the in-app conditional-refresh scheduler (`unified`/`http` only) |
| `GENCC_LINK_DATA__REFRESH_INTERVAL_HOURS` | `24` | Hours between conditional refresh checks |
| `GENCC_LINK_DATA__REFRESH_JITTER_SECONDS` | `300` | Random jitter added to each refresh |
| `GENCC_LINK_DATA__BUILD_LOCK_TIMEOUT` | `600` | Seconds to wait for the cross-process build lock |
| `GENCC_LINK_DATA__DOWNLOAD_TIMEOUT` | `120` | Download timeout (seconds) |
| `GENCC_LINK_DATA__CACHE_SIZE` | `512` | Query cache entries (0 disables) |
| `GENCC_LINK_DATA__CACHE_TTL` | `3600` | Query cache TTL (seconds) |

`AUTO_BOOTSTRAP` differs between the checkout and the image on purpose: locally
the `unified`/`http` server lazily builds the database on first use if it is
absent (so `make data` is optional, though recommended for a predictable first
boot); in the container the **entrypoint** builds it before the server accepts
traffic, so lazy bootstrap is switched off.

`REFRESH_ENABLED` must be owned by exactly one scheduler. Set it to `false`
whenever an external scheduler (cron sidecar, Kubernetes CronJob, systemd timer)
owns the refresh — see [data-lifecycle.md](data-lifecycle.md#choosing-a-refresh-strategy).

## Docker-only variables

| Variable | Default | Description |
|----------|---------|-------------|
| `GENCC_LINK_HOST_PORT` | `8000` | Host port published by `docker/docker-compose.yml` (container port stays `8000`) |
| `REFRESH_INTERVAL_SECONDS` | `86400` | Seconds between refreshes in the `gencc-refresh` cron-sidecar overlay |

See [deployment.md](deployment.md) for the Compose overlays and
[`.env.docker.example`](../.env.docker.example).
