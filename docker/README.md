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

## The Data Volume (pinned data release)

The database is **not** baked into the image and is **not** downloaded from
thegencc.org at boot. The one-shot `gencc-data-init` service runs
`gencc-link-data materialize-data`: it restores the image's pinned
`data-gencc-*` GitHub release asset of this repository into the `gencc-data`
volume (digest-verified, selected atomically as `/data/current`), and the server
mounts that volume **read-only**. See [docs/data-lifecycle.md](../docs/data-lifecycle.md)
and [docs/deployment.md](../docs/deployment.md#operator-steps-fleet-host).

`gencc-link-data info` (run in the server container) prints the served build
provenance. Building from upstream (`make data`) is a local-development path only.

## Compose Files

- `docker-compose.yml` — `gencc-data-init` restore service + base unified
  service, published on loopback port `8000`, with the `gencc-data` named volume.
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
- keeps the `gencc-data` volume (written only by `gencc-data-init`, read-only in
  the server).

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

**`data: unavailable` / no `release_identity` in `/health`**

The restore did not complete: `docker compose -f docker/docker-compose.yml logs gencc-data-init`.

**Build cache issues**

```bash
docker compose -f docker/docker-compose.yml build --no-cache
```

**Health checks**

- Unified server: `curl http://localhost:8000/health`
- MCP endpoint: session-aware at `/mcp`; use an MCP client for protocol-level
  verification.
