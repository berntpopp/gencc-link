#!/bin/sh
# GenCC-Link container entrypoint.
#
# Idempotent data bootstrap: build the GenCC SQLite database once before the
# server starts, so the first request has predictable latency and never triggers
# a surprise download. `gencc-link-data refresh` is safe to run on every start:
#   - missing database  -> downloads the export and builds it
#   - existing database -> conditional request; an unchanged export returns 304
#     (no rebuild, no download-quota cost)
# It is intentionally non-fatal: if the network is down but a database already
# exists in the mounted volume, we serve the existing data; if no database
# exists yet, the server still starts and tools report `data_unavailable` until
# the next refresh succeeds.
set -eu

echo "[entrypoint] ensuring GenCC database is present and current..."
if gencc-link-data refresh; then
    echo "[entrypoint] database ready."
else
    echo "[entrypoint] WARNING: initial refresh failed; starting with existing data if any." >&2
fi

# Hand off (PID 1) to the server command (CMD).
exec "$@"
