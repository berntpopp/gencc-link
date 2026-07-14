# Deployment

How GenCC-Link is run in a container, how its database gets there, and how it is
fronted by a reverse proxy. Image-build internals live in
[`docker/README.md`](../docker/README.md); the refresh strategies live in
[data-lifecycle.md](data-lifecycle.md); every environment variable is in
[configuration.md](configuration.md).

## Hosted endpoint

The GeneFoundry fleet runs GenCC-Link at `https://gencc-link.genefoundry.org/mcp`,
federated behind [genefoundry-router](https://github.com/berntpopp/genefoundry-router).
Backends are **unauthenticated by design**: the router owns edge auth at the trust
boundary, so a `-link` server must only ever be reachable through the router or a
reverse proxy — never published directly.

## Docker

```bash
make docker-build           # build the image
make docker-up              # start the unified server on host port 8000
curl http://localhost:8000/health
make docker-logs
make docker-down
make docker-prod-config     # render the Compose configuration (validation check)
```

The base `docker/docker-compose.yml` binds the published port to **loopback**
(`127.0.0.1:${GENCC_LINK_HOST_PORT:-8000}:8000`) so copying it to a server never
exposes the unauthenticated backend on the public IP. Override the host port with
`GENCC_LINK_HOST_PORT=8120 make docker-up`; the container-internal port stays
`8000`.

### Data lifecycle in the container

- The **entrypoint builds the database once on startup**, before the server
  accepts traffic (`gencc-link-data refresh`: builds if missing, else issues a
  conditional request that returns `304` at no quota cost). It is deliberately
  non-fatal — if the network is down but the volume already holds a database, the
  server serves the existing data.
- An **in-app scheduler** conditionally refreshes every 24h and **hot-reloads**
  the running server, so first-request latency is predictable and the daily
  download quota is respected.
- The built ~24MB database lives in the `gencc-data` named volume at `/data`
  (`GENCC_LINK_DATA__DATA_DIR`) and persists across restarts; a restart re-uses it.
  Because the image builds eagerly in the entrypoint, it sets
  `GENCC_LINK_DATA__AUTO_BOOTSTRAP=false`.

The Compose health check probes `/health`, not `/mcp`: the MCP streamable-HTTP
endpoint is session-aware, so a plain `GET /mcp` can legitimately return a
protocol error. The first boot builds the database, hence the long
`start_period`.

## Compose overlays

| File | Purpose |
|------|---------|
| `docker/docker-compose.yml` | Base unified service, loopback-published, `gencc-data` volume. |
| `docker/docker-compose.prod.yml` | Hardening overlay: no published host ports, `no-new-privileges`, all capabilities dropped, PID limit + `init`, resource limits, JSON log rotation. |
| `docker/docker-compose.cron.yml` | Dedicated-scheduler overlay: disables the in-app loop and runs a `gencc-refresh` sidecar sharing the data volume. |
| `docker/docker-compose.npm.yml` | Nginx Proxy Manager overlay — **self-contained**, not layered: no published ports (`expose` only), routed by container name on the external `npm_default` network. |

```bash
# Production hardening (front it with a reverse proxy)
docker compose -f docker/docker-compose.yml -f docker/docker-compose.prod.yml up -d --build

# Cron sidecar instead of the in-app refresh loop
docker compose -f docker/docker-compose.yml -f docker/docker-compose.cron.yml up -d

# Nginx Proxy Manager (standalone)
docker compose -f docker/docker-compose.npm.yml --env-file .env.docker up -d --build
```

Behind a proxy you MUST add the public hostname to `GENCC_LINK_ALLOWED_HOSTS`
(the NPM overlay ships `gencc-link.genefoundry.org`) — the request guard accepts
exact `Host` values only, and rejects everything else.

## Kubernetes

Manifests are in [`deploy/k8s/`](../deploy/k8s):

- [`deployment.yaml`](../deploy/k8s/deployment.yaml) — initContainer builds the
  database on startup, the in-app scheduler refreshes it. A ReadWriteOnce PVC is
  fine.
- [`cronjob.yaml`](../deploy/k8s/cronjob.yaml) — external scheduler. Set
  `GENCC_LINK_DATA__REFRESH_ENABLED=false` on the Deployment; needs a
  **ReadWriteMany** PVC.

## Download quota

GenCC rate-limits the bulk export to **20 downloads per IP per day**; `304 Not
Modified` and `HEAD` are exempt. Persist the `gencc-data` volume and prefer the
conditional `gencc-link-data refresh` over the forced `build`, and the quota is
never a concern (~1 real download per week). `get_gencc_diagnostics` reports the
remaining headroom.

## Troubleshooting

- **Tools return `data_unavailable` / `/health` reports `data: unavailable`** —
  the database is not built. Run `make data`, or in the container
  `docker compose -f docker/docker-compose.yml run --rm gencc-link gencc-link-data build`.
- **HTTP endpoint unreachable** — confirm the server runs in `unified` mode
  (`http` is REST-only, with no `/mcp`) and that the proxy forwards `POST /mcp`.
- **Proxied requests rejected** — the public hostname is missing from
  `GENCC_LINK_ALLOWED_HOSTS`.
- **Port conflict** — set `GENCC_LINK_HOST_PORT`.
- **Download quota exceeded** — reuse the volume; use `refresh`, not `build`.
