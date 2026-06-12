---
name: ci-failure-triage
description: Use when CI fails on a PR or main in gencc-link. Walks through reproducing make ci-local locally and root-causing without bypassing checks.
---

# CI failure triage

## Classify the failure

Look at the GitHub Actions log and decide which stage failed. `make ci-local`
runs `format-check`, `lint-ci`, `lint-loc`, `typecheck-fast`, and `test-fast`;
the CI job then runs `test-cov`.

- **Format check** (`make format-check`) — Ruff disagrees with the committed
  formatting.
- **Lint** (`make lint-ci`) — a Ruff lint rule.
- **File-size budget** (`make lint-loc`) — `scripts/check_file_size.py` flags a
  file over the per-file line budget (see AGENTS.md "File Size Discipline").
- **Typecheck** (`make typecheck-fast`) — mypy strict.
- **Tests** (`make test-fast`) — a failing or erroring test.
- **Coverage** (`make test-cov`) — coverage fell below the 85% gate.
- **Release** (`release.yml`) — `make ci-local`, the Compose config validation,
  or the Docker image build failed.

## Reproduce locally

Run the same Make target that failed:

```bash
make format-check
make lint-ci
make lint-loc
make typecheck-fast
make test-fast
make test-cov
# release-only:
docker compose -f docker/docker-compose.yml -f docker/docker-compose.prod.yml config
docker build -f docker/Dockerfile -t gencc-link:ci .
```

Tests that need the live GenCC download are marked `integration` and are excluded
from `test-fast` / `test-cov`. Most unit tests build SQLite from the
`tests/fixtures/` sample TSV and do not hit the network.

## Fix at root cause

- Do not add `# type: ignore` or `# noqa` to silence a check unless the behavior
  is genuinely correct and the tool is wrong.
- Do not use `git commit --no-verify` to bypass pre-commit.
- If `lint-loc` fails, split the oversized file rather than raising the budget.
- For a flaky test, rerun once to confirm flakiness, then mark it `slow` (or
  `integration` if it needs the network) and open a follow-up issue rather than
  disabling it.

## Confirm fix

Run `make ci-local` locally. Push. Watch the workflow re-run.
