# AGENTS.md

Shared repository instructions for agentic coding tools working in GenCC-Link.

## Project

GenCC-Link is a Python FastAPI + MCP server that grounds gene-disease validity
questions in the Gene Curation Coalition (GenCC) dataset. GenCC harmonizes
curated gene-disease assertions (Definitive ... Refuted) from member
organizations (ClinGen, Genomics England PanelApp, Orphanet, Ambry, Invitae,
Illumina, and others). GenCC has no live API yet, so the server downloads the
bulk submissions export and serves it from a local SQLite + FTS5 database; the
analytical value-add is per-pair consensus and conflict detection across
submitters.

Primary areas:

- `gencc_link/` - Python package: config, models, data store, services, MCP code
  - `ingest/` - download + parse + build the SQLite database
  - `data/` - schema.sql, read-only repository, repository Protocol (`base.py`)
  - `services/` - consensus aggregation, response shaping, orchestration
  - `mcp/` - facade, tools, capabilities, envelope, next_commands, resources
- `tests/` - unit and integration tests; fixtures under `tests/fixtures/`
- `docker/` - Dockerfile and Compose deployment files
- `docs/` - architecture, usage, and design specs (`docs/superpowers/`)
- `.claude/skills/` - repo-local Claude Code workflows for recurring tasks

## Source Of Truth

- Use this file for shared repo-wide agent guidance.
- Keep `CLAUDE.md` lean and Claude-specific; it should reference this file.
- Prefer `Makefile` targets over ad hoc commands.
- Use `uv.lock` as the dependency lock source of truth.
- The GenCC export schema and classification ranks live in
  `gencc_link/constants.py`; the SQLite schema in `gencc_link/data/schema.sql`.

## Working Rules

- Do not revert or overwrite changes you did not make unless explicitly asked.
- Keep edits scoped to the task and avoid unrelated refactors.
- Prefer existing code patterns over new abstractions.
- Put tests under `tests/`; do not create alternate test roots.
- Use ASCII unless a file already requires non-ASCII content.
- Keep public hosted MCP tools read-only and research-use scoped.
- Respect the GenCC download quota (20/IP/day): use HEAD + conditional requests
  (ETag / Last-Modified); never poll the full export in a loop.

## Commands

Required check before claiming completion:

- `make ci-local`

Useful focused commands:

- `make install` / `make lock`
- `make format` / `make lint` / `make lint-fix` / `make lint-loc`
- `make typecheck` / `make typecheck-fast`
- `make test` / `make test-fast` / `make test-unit` / `make test-integration`
- `make test-cov`
- `make data` / `make data-refresh` / `make data-info`
- `make dev` / `make mcp-serve`
- `make docker-build` / `make docker-up` / `make docker-down`

## Coding Standards

- Use `uv` for dependency management; do not use direct `pip` installs.
- Use modern Python typing: `list[str]`, `dict[str, int]`, `str | None`.
- Format and lint Python with Ruff (100-char line length).
- Type check with mypy targeting Python 3.12 (strict mode).
- Cover services and the repository with unit tests built from
  `tests/fixtures/sample.tsv`; use `respx` to mock the GenCC download in tests.

## File Size Discipline

Hard cap: **600 lines per Python module** in `gencc_link/`, `server.py`, and
`mcp_server.py`. Enforced by `make lint-loc`, wired into `make ci-local`. Tests
are exempt. When a file approaches 500 lines, plan a cohesive split before
adding more behavior. Grandfather only via `.loc-allowlist`.

## Testing Notes

- `make test` is the fast default (excludes integration).
- `make test-fast` runs in parallel via pytest-xdist.
- `make test-cov` runs coverage; gate is 85%.
- Integration tests hit the live GenCC endpoint; run them sparingly.

## GenCC Domain Notes

- Download (new format): `https://thegencc.org/download/action/submissions-export-tsv?format=new`
- Updated weekly; CC0 1.0 data (attribution requested); no OMIM disease text.
- Identifiers: gene = HGNC CURIE (HGNC:10896) / symbol; disease = MONDO CURIE.
- Classification ranks (strong -> weak): Definitive, Strong, Moderate, Supportive,
  Limited, Disputed Evidence, Refuted Evidence, Animal Model Only, No Known
  Disease Relationship. A pair has a conflict when supporting (Definitive/Strong/
  Moderate) and against (Disputed/Refuted/No Known Disease Relationship) coexist.
- Standard test data: gene SKI / disease MONDO:0008426 (Shprintzen-Goldberg).
- Research use only; not for clinical decision support.
