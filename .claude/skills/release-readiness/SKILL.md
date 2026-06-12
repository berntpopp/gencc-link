---
name: release-readiness
description: Use when preparing a versioned release of gencc-link. Walks through the pre-release checklist — ci-local green, CHANGELOG, version bump, valid docker config — then tagging and watching the release workflow.
---

# Release readiness

## Pre-flight checklist

1. Confirm `main` is green: the latest CI run (`ci.yml`) succeeded.
2. Verify there are no outstanding Dependabot PRs that should land first.
3. Confirm `CHANGELOG.md` has an `[Unreleased]` (or current) section listing all
   user-visible changes since the last tag.
4. Run the gate locally and confirm it passes:
   ```bash
   make ci-local
   make test-cov     # coverage gate is 85%
   ```
5. Validate the Docker config and image build the release workflow will run:
   ```bash
   docker compose -f docker/docker-compose.yml -f docker/docker-compose.prod.yml config
   docker build -f docker/Dockerfile -t gencc-link:release .
   ```
6. Sanity-check the data path: `make data` builds a fresh database and
   `make data-info` reports sensible provenance and counts.

## Bump

1. Open `pyproject.toml` and bump `version` (semver: MAJOR for breaking, MINOR
   for features, PATCH for fixes). Keep `gencc_link/__init__.py` `__version__`
   and the `user_agent` default in `config.py` in sync if they reference it.
2. In `CHANGELOG.md`, rename the `[Unreleased]` heading to `[X.Y.Z] - YYYY-MM-DD`
   and add a fresh empty `[Unreleased]` section above it. Update the link
   references at the bottom.
3. Commit: `chore(release): bump to X.Y.Z`.

## Tag and push

```bash
git tag vX.Y.Z
git push origin main vX.Y.Z
```

## Watch

`release.yml` runs on `v*` tag pushes. It installs deps, runs `make ci-local`,
validates the production Compose config, and builds the release Docker image.

## Roll forward

If `release.yml` fails, fix on `main`, bump to `vX.Y.(Z+1)`, and retag. Do not
move or delete a published tag.
