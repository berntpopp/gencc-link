# GenCC-Link Docker Deployment

Production-ready Docker setup for GenCC-Link with a multi-stage build, a non-root
runtime user, and Compose overlays for local and production deployments. The
container runs a single **unified** process that exposes the REST API on `/` and
the MCP endpoint on `/mcp` over one port (`8000`).

## Quick Start

```bash
make docker-build
make docker-up
curl http://localhost:8000/health
make docker-down
```

By default the host port matches the container port (`8000`). Override it when it
conflicts with a sibling project:

```bash
GENCC_LINK_HOST_PORT=8120 make docker-up
```

The container-internal port stays standard (`8000`), which keeps reverse-proxy
and container-to-container routing predictable.

## The Data Volume And First Build

GenCC-Link serves a local SQLite database built from the weekly GenCC bulk
export. The database is **not** baked into the image; it is built into the
directory named by `GENCC_LINK_DATA__DATA_DIR` (default `/data` in the
container).

- `docker-compose.yml` mounts the named volume `gencc-data` at `/data`, so
  the built ~24MB database persists across container restarts and is only
  downloaded once.
- With `GENCC_LINK_DATA__AUTO_BOOTSTRAP=true` (the default), the server
  downloads the GenCC export and builds the database **on first use** if the
  volume is empty. This first boot can take a couple of minutes, which is why the
  Compose health check uses a long `start_period`.
- To pre-build (or refresh) the database without serving traffic, run the data
  CLI inside the container:

  ```bash
  docker compose -f docker/docker-compose.yml run --rm gencc-link \
    gencc-link-data build
  ```

  `gencc-link-data refresh` rebuilds only if GenCC published a newer export;
  `gencc-link-data info` prints build provenance.

GenCC enforces a per-IP daily download quota (20/day; `304 Not Modified` and
`HEAD` are exempt). Persisting the volume avoids re-downloading on every restart.

## Compose Files

- `docker-compose.yml` — base unified service, published on host port `8000`,
  with the `gencc-data` named volume.
- `docker-compose.prod.yml` — production hardening overlay: no published host
  ports, `no-new-privileges`, dropped capabilities, PID limit and `init`,
  resource limits, and JSON log rotation.

Layer the overlays explicitly:

```bash
docker compose -f docker/docker-compose.yml -f docker/docker-compose.prod.yml config
```

`make docker-prod-config` renders the base Compose configuration as a validation
check (used in CI and release).

## Production Overlay

```bash
docker compose \
  -f docker/docker-compose.yml \
  -f docker/docker-compose.prod.yml \
  up -d --build
```

The production overlay:

- publishes no host ports by default (front it with a reverse proxy),
- sets `no-new-privileges` and drops all Linux capabilities,
- applies a PID limit and an `init` process,
- applies memory/CPU resource hints and JSON log rotation,
- keeps the `gencc-data` volume so the database persists.

Publish a port for local production testing by using only `docker-compose.yml`,
or by adding a local override file that publishes the desired host port.

The MCP streamable HTTP endpoint at `/mcp` is session-aware, so a plain
`GET /mcp` probe can return protocol errors. The Compose health check probes
`/health` over HTTP instead; use an MCP client for protocol-level verification.

## Image Build Notes

The Dockerfile uses a multi-stage `uv` build:

- the builder stage installs production dependencies into `/opt/venv` from the
  checked-in `uv.lock`,
- the runtime stage copies only the virtual environment and the required
  application files,
- the runtime user is non-root (`app`),
- the data directory (`/data`) is created and owned by `app`.

No secrets are copied into the image. Pass environment-specific settings through
Compose `env_file` or environment variables at runtime.

## Troubleshooting

**Port conflicts**

Set `GENCC_LINK_HOST_PORT` to another free port.

**Database not built / `data: unavailable` in `/health`**

The first request triggers an auto-build when `AUTO_BOOTSTRAP=true`. To build
eagerly:

```bash
docker compose -f docker/docker-compose.yml run --rm gencc-link gencc-link-data build
```

**Download quota exceeded**

GenCC allows 20 downloads per IP per day. Reuse the `gencc-data` volume so the
export is not re-downloaded on every restart, and prefer `gencc-link-data
refresh` (conditional) over `build` (forced).

**Build cache issues**

```bash
docker compose -f docker/docker-compose.yml build --no-cache
```

**Health checks**

- Unified server: `curl http://localhost:8000/health`
- MCP endpoint: session-aware at `/mcp`; use an MCP client for protocol-level
  verification.
