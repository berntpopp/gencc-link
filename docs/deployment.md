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

### Data in the container (pinned data release)

- A one-shot **`gencc-data-init`** service runs `gencc-link-data materialize-data`
  before the server starts. It downloads the image's pinned `data-gencc-*`
  GitHub release asset of this repository (`github.com` /
  `release-assets.githubusercontent.com` only), verifies the compressed and
  expanded SHA-256 and the schema, writes `/data/<digest>/gencc.sqlite`, and
  atomically points `/data/current` at it. A restart re-verifies the existing
  snapshot without downloading. Nothing is fetched from thegencc.org.
- The **server mounts the volume read-only**, serves
  `/data/current/gencc.sqlite`, and reports `release_identity.data_identity`
  (`expected` from its pin, `actual` re-proved from the served bytes) in
  `/health`. No in-app refresh, no upstream download.
- A new data release reaches production only through a reviewed re-pin and a new
  image (see [data-lifecycle.md](data-lifecycle.md#re-pinning-to-a-newer-data-release)).

### Operator steps (fleet host)

1. Pull the released image by digest and set `GENCC_LINK_IMAGE` as before.
2. `docker compose -f docker/docker-compose.npm.yml --env-file .env.docker up -d`.
   Compose starts `gencc-data-init` first (it needs outbound HTTPS to
   `github.com` and `release-assets.githubusercontent.com`), waits for it to exit
   `0`, then starts the server. No manual staging is required.
3. Verify: `docker compose -f docker/docker-compose.npm.yml logs gencc-data-init`
   shows `Materialized GenCC data release data-gencc-…`, and
   `curl -s -H 'Host: localhost' http://<container>:8000/health | jq .release_identity`
   shows `expected == actual` with the tag/digest from `container-release.json`.
4. Optional cleanup: the old upstream-live files in the existing `gencc-data`
   volume (`gencc.sqlite`, `gencc-submissions.tsv`, `download_cache.json`,
   `.build.lock`) are no longer read and may be deleted; the restore writes
   only `<digest>/` and `current`.
5. Air-gapped host: run `gencc-data-init` once where `github.com` is reachable and
   copy the volume, or pre-create `<volume>/<digest>/` from the release assets
   (`gunzip gencc.sqlite.gz`, `chmod 0444`, the `identity.json` written by
   `materialize-data`) and the `current` link; the init service then re-verifies
   it without downloading.

The Compose health check probes `/health`, not `/mcp`: the MCP streamable-HTTP
endpoint is session-aware, so a plain `GET /mcp` can legitimately return a
protocol error.

## Compose overlays

| File | Purpose |
|------|---------|
| `docker/docker-compose.yml` | Base: `gencc-data-init` restore service + unified server (loopback-published, read-only `gencc-data` volume). |
| `docker/docker-compose.prod.yml` | Hardening overlay: no published host ports, `no-new-privileges`, all capabilities dropped, PID limit + `init`, resource limits, JSON log rotation. |
| `docker/docker-compose.npm.yml` | Nginx Proxy Manager overlay — **self-contained**, not layered: no published ports (`expose` only), routed by container name on the external `npm_default` network. |

```bash
# Production hardening (front it with a reverse proxy)
docker compose -f docker/docker-compose.yml -f docker/docker-compose.prod.yml up -d --build

# Nginx Proxy Manager (standalone)
docker compose -f docker/docker-compose.npm.yml --env-file .env.docker up -d --build
```

Behind a proxy you MUST add the public hostname to `GENCC_LINK_ALLOWED_HOSTS`
(the NPM overlay ships `gencc-link.genefoundry.org`) — the request guard accepts
exact `Host` values only, and rejects everything else.

### Fleet deploy contract

`container-release.json` declares `service.deployed_compose_files:
["docker/docker-compose.npm.yml"]` — the exact Compose file the fleet
controller (`strato_v6_docker_npm`) deploys, standalone (not layered on the
base/prod files). The shared reusable release workflow
(`_container-release.yml`, pinned in `.github/workflows/container-release.yml`)
runs `container_release.py validate-deployed-overlay` against that declared
file before every release, checking the numeric `user`, restart policy,
healthcheck `start_period`, `expose`, and the absence of top-level `x-*` keys.
Self-check locally:

```bash
docker compose -f docker/docker-compose.npm.yml config --format json > /tmp/gencc-link-rendered.json
# from a genefoundry-router checkout:
uv run python scripts/container_release.py validate-deployed-overlay \
  --config /path/to/gencc-link/container-release.json --project-dir /path/to/gencc-link
```

## Kubernetes

[`deploy/k8s/deployment.yaml`](../deploy/k8s/deployment.yaml): an initContainer
runs `gencc-link-data materialize-data`, the server mounts the PVC read-only.

## Troubleshooting

- **Tools return `data_unavailable` / `/health` has no `release_identity`** —
  the restore did not complete. Check `docker compose logs gencc-data-init`: a
  digest/identity error means the volume holds a different or damaged snapshot
  under the same digest directory (delete that `<digest>/` directory and restart);
  a download error means `github.com` is unreachable from the init container.
- **HTTP endpoint unreachable** — confirm the server runs in `unified` mode
  (`http` is REST-only, with no `/mcp`) and that the proxy forwards `POST /mcp`.
- **Proxied requests rejected** — the public hostname is missing from
  `GENCC_LINK_ALLOWED_HOSTS`.
- **Port conflict** — set `GENCC_LINK_HOST_PORT`.
- **Download quota exceeded (local dev only)** — reuse `data/`; use `make data-refresh`, not `make data`.
