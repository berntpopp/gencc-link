# Adopt GeneFoundry Tool-Naming Standard v1 + dependency bumps — design

> Historical record — this document records the design or plan as of its date. Current behavior is
> defined by implemented code, standards, release evidence, and tests.

Date: 2026-06-15
Issue: #3 (Adopt GeneFoundry Tool-Naming Standard v1)
Supersedes (stale dependabot): PR #1 (docker python 3.14-slim), PR #2 (uv group)
Target version: **0.5.0** (pre-1.0; contains a BREAKING argument rename)

## Context

GenCC-Link is being federated behind the `genefoundry-router` gateway alongside
the rest of the `*-link` fleet. The router (`../genefoundry-router`) is the
reference implementation of **Tool-Naming Standard v1**:

- `servers.yaml` maps this server as `{ name: gencc, namespace: gencc }` with **no
  `transform`** block (unlike `pubtator`, which still needs `strip_prefix`). So at
  the gateway, leaf tools surface as `gencc_<leaf>` with no double-prefixing.
- `genefoundry_router/cli.py:check_leaf_name` + `tests/unit/test_strict_naming.py`
  define the exact lint contract every leaf must satisfy:
  - `LEAF_NAME_RE = ^[a-z0-9_]{1,50}$`
  - `CANONICAL_VERBS = {get, search, list, resolve, find, compare, compute}`
  - `ACTION_VERB_EXCEPTIONS = {predict, analyze, annotate, submit, export, generate, download}`

Issue #3's own analysis concludes **all 12 gencc-link tool names are already
compliant** (verbs used: `get`, `search`, `find`, `list`, `resolve`; longest name
`get_gene_disease_assertion` = 26 chars). So this work is **guardrails + docs +
argument-canon alignment**, not tool renames.

## Decisions (confirmed with maintainer)

1. **Argument canon: split the polymorphic `gene` into fleet-canonical
   `gene_symbol` + `hgnc_id`.** The maintainer confirmed the project is pre-alpha
   and breaking changes are acceptable, which removes the only objection the issue
   raised (the breaking-change cost). Splitting fully satisfies DoD item
   "Argument names aligned to the fleet canon" (Rule 4) and is faithful: the two
   optional params together represent exactly what the old polymorphic `gene`
   accepted (an approved symbol **or** an HGNC CURIE).
2. **One feature branch**, reimplementing both stale dependabot bumps from current
   `main` (PR #1/#2 branched from the 0.1.0 era and would corrupt `main` if
   merged). The stale PRs will be noted as superseded / closeable.

## Scope of the argument split

The split happens **only at the MCP tool boundary**. The service/repository layer
keeps its existing polymorphic `gene: str` parameter — the tool layer validates
the two new params and forwards the single provided value inward. This keeps the
blast radius small and the resolver semantics unchanged.

| Tool | Before | After |
| --- | --- | --- |
| `get_gene_curations` | `gene: str` (required) | `gene_symbol: str \| None`, `hgnc_id: str \| None` — **exactly one required** |
| `get_gene_disease_assertion` | `gene: str` (required) + `disease` | `gene_symbol`/`hgnc_id` (exactly one) + `disease` |
| `find_curations` | `gene: str \| None` (optional filter) | `gene_symbol`/`hgnc_id` (optional filter, **at most one**) |
| `get_genes_curations` (batch) | `genes: list[str]` | **unchanged** — `genes` stays a polymorphic list (no fleet-canon plural exists; two parallel lists would be unusable). Documented as accepting symbols or HGNC CURIEs. |

`disease` / `diseases` are unchanged (the issue confirms no fleet-canon disease
identifier exists). `resolve_identifier`'s `query`/`identifier` alias is unchanged
(the issue rates it "acceptable").

Validation contract (raises `InvalidInputError` → `invalid_input` envelope):
- Required-gene tools: neither provided → error (`field="gene_symbol"`); both
  provided → error (`field="hgnc_id"`).
- `find_curations` (optional filter): both provided → error; neither → no gene
  filter (unchanged behaviour).

A small shared helper `coalesce_gene(gene_symbol, hgnc_id, *, required)` in
`gencc_link/mcp/tools/_args.py` centralises this (used by `genes.py` and
`assertions.py`).

## next_commands / recovery impact

`gencc_link/mcp/next_commands.py` builders emit `cmd(...)` argument dicts. Every
gene value they carry is a resolved **HGNC CURIE** (`gene_curie`, e.g.
`HGNC:10896`), so those become `hgnc_id=<curie>` (semantically exact). The error
`recovery_commands` reads user-supplied input, which may be a symbol or a CURIE; a
tiny `gene_kwargs(value)` helper maps `HGNC:`-prefixed values to `hgnc_id` and
everything else to `gene_symbol`. `recovery_commands` also reads the gene input
from the error context, which will now carry `gene_symbol`/`hgnc_id` keys.

## Deliverables

### A. CI tool-name lint guard (issue Rule 8 / DoD)
`tests/test_tool_naming.py` — introspects the **live** registered tools from
`create_gencc_mcp()` and asserts, for every tool:
- name matches `^[a-z0-9_]{1,50}$`,
- name starts with a canonical verb (same `CANONICAL_VERBS` +
  `ACTION_VERB_EXCEPTIONS` sets as the router, copied verbatim so the fleet
  contract is identical),
- at least one domain `tag` is present (Rule 6 / DoD "Domain tags").

It also cross-checks the live tool set against the static `capabilities.TOOLS`
tuple (drift guard). Runs inside `make test-fast` → `make ci-local` → CI. A
`check_leaf_name(leaf)` helper mirrors the router's, so adding a non-compliant
tool in the future fails CI.

### B. Argument-canon split
Tool signatures, descriptions, validation, `next_commands`, error contexts, and
`capabilities.parameter_conventions` / `recommended_workflows` updated per the
table above.

### C. README federation/namespace docs (issue Rule 5 / DoD)
New "GeneFoundry federation" subsection documenting:
- `serverInfo.name = "gencc-link"` (stable identity, already set),
- canonical gateway **namespace token `gencc`** → tools surface as `gencc_<leaf>`
  at the router,
- leaves are intentionally **unprefixed** (namespacing is the gateway's job),
- the canonical argument names (`gene_symbol`, `hgnc_id`, `disease`,
  `response_mode`, `limit`/`offset`).
Update any `gene`-argument examples in README/docs to the new names.

### D. Dependency bumps (supersede #1/#2)
- `pyproject.toml`: `uvicorn[standard]>=0.49.0`, `mcp[cli]>=1.27.2`; regenerate
  `uv.lock` via `make lock`. (No `version`/`find.py` changes — those were stale
  divergence in PR #2.)
- `docker/Dockerfile`: both `FROM python:3.12-slim` → `python:3.14-slim`. Verify a
  container build (deps must have cp314 wheels; `requires-python` is `>=3.12`).

### E. Release plumbing
- `pyproject.toml` version `0.4.0` → `0.5.0`.
- `CHANGELOG.md` — new `[0.5.0]` entry with a prominent **BREAKING** callout for
  the `gene` → `gene_symbol`/`hgnc_id` rename, plus the lint guard, namespace
  docs, and dep bumps.
- `tests/test_tools.py` `EXPECTED_TOOLS` is unchanged (no tool renames); the
  per-tool call sites that pass `{"gene": ...}` migrate to the new arg names.

## Testing strategy (TDD)

1. New `tests/test_tool_naming.py` (the guard) — write first, watch it pass for
   the current compliant names, and add a negative unit test on `check_leaf_name`.
2. Migrate `tests/test_tools.py`, `tests/test_next_commands.py`,
   `tests/test_envelope.py` MCP-boundary calls to `gene_symbol`/`hgnc_id`; add
   tests for the exactly-one / at-most-one validation and for `hgnc_id` input.
3. `make ci-local` green (format, lint, lint-loc, typecheck, test-fast).
4. Best-effort `docker build` of the 3.14 image to de-risk PR #1.

Service-layer tests (`test_service.py`, `test_repository.py`) keep `gene=` — the
service signature does not change.

## Out of scope

- Renaming any tool (none needed).
- `disease`/`diseases`/`query`/`identifier`/`cursor`/`limit_per_*` argument names.
- Router-side changes (the router already maps `gencc` with no transform).
- Bumping to 1.0.0 (project is pre-alpha; breaking changes ride a 0.x minor).
