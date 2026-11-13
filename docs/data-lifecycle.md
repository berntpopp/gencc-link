# Data lifecycle

GenCC publishes a single bulk export (no live API) and rate-limits downloads to
**20 per IP per day**. GenCC-Link turns that export into a local **SQLite + FTS5**
index. Since v0.9.0 the deployed server never downloads from thegencc.org: it
serves one **pinned, published data release** (`external-reference` mode,
genefoundry-router#63 option A), so every release proves the exact data it serves.

```
 weekly  ┌─ .github/workflows/data-release.yml (main only) ────────────────────────┐
 (Mon)   │ gencc-link-data build --reproducible  (ONE upstream download)            │
         │ gencc-link-data package  → data-gencc-<sha16>: gencc.sqlite.gz,          │
         │   manifest.json, data-authorization.json, SHA256SUMS                     │
         │ unchanged export → same bytes → same tag → no-op                         │
         │ new tag → waits on the `data-release` environment (owner) → attest →     │
         │   draft → verify every asset digest → publish (immutable)                │
         └──────────────────────────────────────────────────────────────────────────┘
 reviewed PR: pin tag + digests in gencc_link/config.py AND container-release.json
 app release vX.Y.Z: the release gate boots the image and checks /health
   release_identity == container-release.json (Runtime Data Identity v1)
 deploy  ┌─ compose stack ──────────────────────────────────────────────────────────┐
         │ gencc-data-init: gencc-link-data materialize-data                        │
         │   GitHub release asset → sha256(gz) → gunzip → sha256(sqlite) →          │
         │   schema check → /data/<gz-sha256>/ → atomic /data/current link → exit   │
         │ gencc-link: reads /data/current/gencc.sqlite from a READ-ONLY mount;     │
         │   /health reports expected + actual release identity                     │
         └──────────────────────────────────────────────────────────────────────────┘
```

## Reproducibility

`build --reproducible` pins the `meta.build_utc` field to the export's
`Last-Modified` and stores no build duration, and the snapshot uses a rollback
journal (not WAL). The same export therefore always builds to the same SQLite
bytes, and `package` gzips with a zero timestamp, so the release tag
(`data-gencc-` + the first 16 hex of the SQLite SHA-256) is content-addressed.
The manifest records the upstream URL, ETag, Last-Modified, raw TSV SHA-256,
GenCC run date, record counts, the transformation commit, licence, attribution
and the authorization record.

## Licence and authorization

GenCC data are CC0 1.0 ([terms](https://thegencc.org/terms)); GenCC requests
attribution to GenCC and the contributing sources, and its download excludes
OMIM data. `release/data-authorization.json` records the repository owner's
2026-11-13 decision to publish the derived research-use snapshot (the owner's
determination, not a GenCC approval) and the attribution every release carries.

## Re-pinning to a newer data release

1. The weekly workflow (or a manual dispatch on `main`) publishes a new
   `data-gencc-*` release after the owner approves the `data-release` gate.
2. In one PR, set `DATA_RELEASE_TAG`, `DATA_COMPRESSED_SHA256` (= the
   `gencc.sqlite.gz` SHA-256 = `manifest.json` `compressed_sha256`) and
   `DATA_EXPANDED_SHA256` in `gencc_link/config.py`, and the same tag + `sha256:`
   digest in `container-release.json` `data`. `tests/test_data_release_identity.py`
   fails if they disagree.
3. Release the app (`vX.Y.Z`); the release workflow's runtime data identity
   check is the proof.

## Local development

The upstream path stays available for local work only:
`make data` (`gencc-link-data build`), `make data-refresh` (conditional, ETag /
Last-Modified, `304` is quota-free) and `make data-info`. Run without Docker,
`GENCC_LINK_DATA__AUTO_BOOTSTRAP` and the in-app refresh scheduler
(`GENCC_LINK_DATA__REFRESH_ENABLED`) still default to on; the image turns both
off. A local build reports `data: ready` in `/health` but no `release_identity`.
