# Data lifecycle

GenCC publishes a single bulk export (no live API) and rate-limits downloads to
**20 per IP per day**, where `304 Not Modified` and `HEAD` are exempt. GenCC-Link
therefore builds a local **SQLite + FTS5** artifact and keeps it current with a
two-part lifecycle:

1. **Build once on startup** — before the server accepts traffic, so the first
   request has predictable latency and never triggers a surprise download.
2. **Refresh on a schedule** — a *conditional* download (ETag / Last-Modified)
   that rebuilds only when the export actually changed, then **hot-reloads** the
   running server.

```
            ┌──────────────────────────── container / pod ────────────────────────────┐
 startup ──▶│ entrypoint: gencc-link-data refresh  (build if missing, else 304 no-op)  │
            │        │ writes data/gencc.sqlite (atomic os.replace under a file lock)   │
            │        ▼                                                                  │
            │   server (unified)  ──reads──▶ data/gencc.sqlite (read-only connection)  │
            │        ▲                                                                  │
            │   in-app scheduler (every 24h): conditional refresh ──changed?──▶ rebuild │
            │        └────────── on change: reset cached service ──▶ reopen (hot-reload)│
            └───────────────────────────────────────────────────────────────────────────┘
```

## Building blocks

- **`gencc-link-data` CLI** (`gencc_link/ingest/cli.py`) — the unit of work any
  scheduler calls:
  - `build` — force download + rebuild.
  - `refresh` — conditional; rebuilds only if the export changed (prints
    "up to date" on `304`).
  - `info` — print provenance of the existing database.
- **Build lock** (`gencc_link/ingest/lock.py`) — a POSIX `flock` on
  `data/.build.lock` serializes every builder (entrypoint, in-app scheduler,
  sidecar, CronJob) so they never download or rebuild concurrently. `ensure_database`
  uses double-checked locking.
- **Atomic swap** — the builder writes `gencc.sqlite.tmp` and `os.replace`s it
  into place, so readers always see a complete database.
- **Hot reload** (`gencc_link/mcp/service_adapters.py`) — each tool call does a
  cheap `stat`; when the database file's mtime changes (any builder swapped it),
  the read-only connection is reopened. This is what lets an *external* scheduler
  refresh the data and have the running server pick it up with no restart.
- **In-app scheduler** (`gencc_link/services/refresh.py`) — a dependency-free
  asyncio loop started from the FastAPI lifespan (unified/http only; never stdio).
  First run is one interval after startup; the blocking download+build runs in a
  worker thread. Surfaced in `get_gencc_diagnostics.refresh`.

## Choosing a refresh strategy

Pick **one** owner for the periodic refresh. All options share the build lock and
the hot-reload, so they are safe to mix only if exactly one is enabled.

| Strategy | When | How |
|----------|------|-----|
| **In-app scheduler** (default) | Single container / single deployment | `GENCC_LINK_DATA__REFRESH_ENABLED=true` (default). Nothing else to run. |
| **Cron sidecar** | Docker Compose, want separation of concerns | `docker compose -f docker/docker-compose.yml -f docker/docker-compose.cron.yml up -d` — disables the in-app loop and runs a `gencc-refresh` sidecar. |
| **k8s initContainer + in-app** | Kubernetes, single pod | `deploy/k8s/deployment.yaml` — initContainer builds on startup, in-app scheduler refreshes. ReadWriteOnce PVC is fine. |
| **k8s CronJob** | Kubernetes, external scheduler | `deploy/k8s/cronjob.yaml` — set `REFRESH_ENABLED=false` on the Deployment; needs a **ReadWriteMany** PVC. |
| **Host cron / systemd timer** | Bare VM | Disable the in-app loop and schedule `gencc-link-data refresh`. |

### Host cron example

```cron
# Weekly conditional refresh (GenCC updates weekly; 304s are quota-free).
17 3 * * 1  cd /opt/gencc-link && /opt/gencc-link/.venv/bin/gencc-link-data refresh >> /var/log/gencc-refresh.log 2>&1
```

### systemd timer example

```ini
# /etc/systemd/system/gencc-refresh.service
[Service]
Type=oneshot
WorkingDirectory=/opt/gencc-link
ExecStart=/opt/gencc-link/.venv/bin/gencc-link-data refresh
Environment=GENCC_LINK_DATA__DATA_DIR=/var/lib/gencc-link

# /etc/systemd/system/gencc-refresh.timer
[Timer]
OnCalendar=Mon *-*-* 03:17:00
Persistent=true
[Install]
WantedBy=timers.target
```

## Configuration

| Variable | Default | Meaning |
|----------|---------|---------|
| `GENCC_LINK_DATA__AUTO_BOOTSTRAP` | `true` (image: `false`) | Build lazily on first use if absent. The image sets `false` because the entrypoint builds on startup. |
| `GENCC_LINK_DATA__REFRESH_ENABLED` | `true` | Run the in-app scheduler (unified/http only). Set `false` when an external scheduler owns refresh. |
| `GENCC_LINK_DATA__REFRESH_INTERVAL_HOURS` | `24` | Hours between conditional checks. Daily is quota-safe (304 on unchanged days). |
| `GENCC_LINK_DATA__REFRESH_JITTER_SECONDS` | `300` | Random jitter added per cycle. |
| `GENCC_LINK_DATA__BUILD_LOCK_TIMEOUT` | `600` | Seconds to wait for the build lock before giving up. |

## Quota safety

The conditional `refresh` sends `If-None-Match` / `If-Modified-Since`. On an
unchanged export GenCC returns `304`, which does **not** count against the daily
quota. A real change costs at most one download per change (GenCC changes ~weekly),
so a daily schedule uses ≤ ~1 download/week and stays far under the 20/day cap.

## Observability

`get_gencc_diagnostics` returns build provenance plus a `refresh` block
(`enabled`, `interval_hours`, `scheduler_running`, and the scheduler `status`:
last check time, whether the last check changed the data, and any last error).
Structured logs record each scheduler decision (`refresh applied`,
`refresh check: source not modified`, or a warning on quota/download failure).
