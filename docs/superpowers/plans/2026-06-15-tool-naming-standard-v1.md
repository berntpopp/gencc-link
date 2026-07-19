# Tool-Naming Standard v1 + dependency bumps — Implementation Plan

> Historical record — this document records the design or plan as of its date. Current behavior is
> defined by implemented code, standards, release evidence, and tests.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring gencc-link into GeneFoundry Tool-Naming Standard v1 compliance (CI lint guard, fleet-canonical `gene_symbol`/`hgnc_id` args, namespace docs) and land the two stale dependabot bumps cleanly, shipping as 0.5.0.

**Architecture:** Tool names are already compliant, so the core is a CI guard mirroring the router's `check_leaf_name` contract. The polymorphic `gene` arg is split into canonical `gene_symbol`+`hgnc_id` at the MCP tool boundary only; the service layer keeps `gene: str`. Dependency bumps are reimplemented from current `main` (the dependabot branches are stale).

**Tech Stack:** Python 3.12, FastMCP 3.x, pydantic 2, pytest(-asyncio), uv, Ruff, mypy, Docker.

---

## File Structure

- `pyproject.toml` — dep floors + version bump (modify)
- `uv.lock` — regenerated (modify via `make lock`)
- `docker/Dockerfile` — 3.12-slim → 3.14-slim (modify)
- `tests/test_tool_naming.py` — NEW CI lint guard
- `gencc_link/mcp/tools/_args.py` — NEW shared gene-arg coalescer
- `gencc_link/mcp/tools/genes.py` — split `gene` → `gene_symbol`/`hgnc_id` (modify)
- `gencc_link/mcp/tools/assertions.py` — same split (modify)
- `gencc_link/mcp/next_commands.py` — emit `hgnc_id`; `gene_kwargs`; recovery (modify)
- `gencc_link/mcp/capabilities.py` — `parameter_conventions` + workflows (modify)
- `tests/test_tools.py`, `tests/test_next_commands.py`, `tests/test_envelope.py` — migrate call sites (modify)
- `README.md` — federation/namespace section + arg examples (modify)
- `CHANGELOG.md` — `[0.5.0]` entry (modify)

---

## Task 1: Dependency bumps (supersede PR #2)

**Files:**
- Modify: `pyproject.toml:33,41`
- Modify: `uv.lock` (regenerated)

- [ ] **Step 1: Raise the two floors**

In `pyproject.toml` `dependencies`:
```toml
    "uvicorn[standard]>=0.49.0,<1.0.0",
    "mcp[cli]>=1.27.2,<2.0.0",
```
(Leave `version`, `find.py` ruff ignore, and everything else untouched — those
were stale divergence in PR #2.)

- [ ] **Step 2: Regenerate the lock**

Run: `make lock`
Expected: `uv.lock` updates; `uvicorn` resolves to ≥0.49.0, `mcp` to ≥1.27.2.

- [ ] **Step 3: Verify install + import still work**

Run: `uv sync && uv run python -c "import uvicorn, mcp, fastmcp; print(uvicorn.__version__)"`
Expected: prints a version ≥ 0.49.0, no import error.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "build(deps): bump uvicorn floor to 0.49.0 and mcp to 1.27.2 (uv group; supersedes #2)"
```

---

## Task 2: Docker base image 3.14-slim (supersede PR #1)

**Files:**
- Modify: `docker/Dockerfile:4,30`

- [ ] **Step 1: Bump both FROM lines**

Change `FROM python:3.12-slim AS builder` → `FROM python:3.14-slim AS builder`
and `FROM python:3.12-slim AS production` → `FROM python:3.14-slim AS production`.

- [ ] **Step 2: Commit (build verified in Task 11)**

```bash
git add docker/Dockerfile
git commit -m "build(deps): bump docker python base to 3.14-slim (supersedes #1)"
```

---

## Task 3: CI tool-name lint guard

**Files:**
- Create: `tests/test_tool_naming.py`

- [ ] **Step 1: Write the guard test**

```python
"""Tool-Naming Standard v1 guard — every registered MCP tool must be fleet-compliant.

Contract mirrors genefoundry-router's cli.check_leaf_name (CANONICAL_VERBS,
ACTION_VERB_EXCEPTIONS, LEAF_NAME_RE) so the gateway and every -link leaf agree.
"""

from __future__ import annotations

import re

import pytest

from gencc_link.mcp.capabilities import TOOLS
from gencc_link.mcp.facade import create_gencc_mcp

pytestmark = pytest.mark.mcp

# Verbatim copy of the router's Tool-Naming Standard v1 contract.
LEAF_NAME_RE = re.compile(r"^[a-z0-9_]{1,50}$")
CANONICAL_VERBS = {"get", "search", "list", "resolve", "find", "compare", "compute"}
ACTION_VERB_EXCEPTIONS = {
    "predict", "analyze", "annotate", "submit", "export", "generate", "download",
}


def check_leaf_name(leaf: str) -> list[str]:
    """Return Tool-Naming Standard v1 violations for one leaf tool name."""
    issues: list[str] = []
    if not LEAF_NAME_RE.match(leaf):
        issues.append(f"charset/length: {leaf!r} must match ^[a-z0-9_]{{1,50}}$")
    verb = leaf.split("_", 1)[0]
    if verb not in CANONICAL_VERBS and verb not in ACTION_VERB_EXCEPTIONS:
        issues.append(f"verb: {leaf!r} starts with non-canonical verb {verb!r}")
    return issues


async def _registered_tools() -> dict[str, object]:
    return await create_gencc_mcp().get_tools()


async def test_every_tool_name_is_standard_v1_compliant() -> None:
    tools = await _registered_tools()
    assert tools, "no tools registered"
    violations = {name: issues for name in tools if (issues := check_leaf_name(name))}
    assert not violations, f"Tool-Naming Standard v1 violations: {violations}"


async def test_every_tool_has_a_domain_tag() -> None:
    tools = await _registered_tools()
    untagged = [name for name, tool in tools.items() if not getattr(tool, "tags", None)]
    assert not untagged, f"tools missing a domain tag: {untagged}"


async def test_live_tools_match_capabilities_TOOLS() -> None:
    live = set((await _registered_tools()).keys())
    assert live == set(TOOLS), f"capabilities.TOOLS drift: {live ^ set(TOOLS)}"


def test_check_leaf_name_flags_violations() -> None:
    # prefixed + camelCase + non-canonical verb
    assert check_leaf_name("gnomad_fetchVariant")
    # >50 chars
    assert any("50" in i for i in check_leaf_name("get_" + "x" * 60))
    # compliant
    assert check_leaf_name("get_gene_curations") == []
```

- [ ] **Step 2: Run the guard**

Run: `uv run pytest tests/test_tool_naming.py -v`
Expected: PASS (all 12 names already compliant). If `get_tools()` is not the
FastMCP 3.x API, adjust to the correct introspection call and re-run.

- [ ] **Step 3: Commit**

```bash
git add tests/test_tool_naming.py
git commit -m "test(naming): add Tool-Naming Standard v1 CI guard (issue #3 Rule 8)"
```

---

## Task 4: Shared gene-arg coalescer

**Files:**
- Create: `gencc_link/mcp/tools/_args.py`
- Test: `tests/test_tool_naming.py` (append unit tests) — or a focused test in Task 5

- [ ] **Step 1: Write the helper**

```python
"""Shared MCP-tool argument helpers."""

from __future__ import annotations

from gencc_link.exceptions import InvalidInputError


def coalesce_gene(
    gene_symbol: str | None, hgnc_id: str | None, *, required: bool
) -> str | None:
    """Collapse the canonical gene_symbol/hgnc_id pair into one resolver input.

    Exactly one may be supplied. Returns the supplied value (forwarded to the
    polymorphic service `gene` parameter) or None when neither is given and the
    caller permits an absent gene filter.
    """
    if gene_symbol is not None and hgnc_id is not None:
        raise InvalidInputError(
            "Pass only one of `gene_symbol` / `hgnc_id`, not both.", field="hgnc_id"
        )
    value = gene_symbol if gene_symbol is not None else hgnc_id
    if value is None and required:
        raise InvalidInputError(
            "Provide `gene_symbol` (approved symbol) or `hgnc_id` (HGNC CURIE).",
            field="gene_symbol",
        )
    return value
```

- [ ] **Step 2: Write a focused unit test** (`tests/test_filters.py` already exists for arg/validation — append, or create `tests/test_args.py`)

```python
import pytest
from gencc_link.exceptions import InvalidInputError
from gencc_link.mcp.tools._args import coalesce_gene


def test_coalesce_prefers_either_single_value():
    assert coalesce_gene("SKI", None, required=True) == "SKI"
    assert coalesce_gene(None, "HGNC:10896", required=True) == "HGNC:10896"


def test_coalesce_rejects_both():
    with pytest.raises(InvalidInputError):
        coalesce_gene("SKI", "HGNC:10896", required=True)


def test_coalesce_required_missing_raises():
    with pytest.raises(InvalidInputError):
        coalesce_gene(None, None, required=True)


def test_coalesce_optional_missing_is_none():
    assert coalesce_gene(None, None, required=False) is None
```

- [ ] **Step 3: Run**

Run: `uv run pytest tests/test_args.py -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add gencc_link/mcp/tools/_args.py tests/test_args.py
git commit -m "feat(mcp): add coalesce_gene helper for gene_symbol/hgnc_id args"
```

---

## Task 5: Split `gene` in genes.py + migrate its tests

**Files:**
- Modify: `gencc_link/mcp/tools/genes.py:94-120` (`get_gene_curations`)
- Modify: `tests/test_tools.py` (`get_gene_curations` call sites)

- [ ] **Step 1: Update `get_gene_curations` signature + body**

Replace the `gene: str = ""` param with the canonical pair and coalesce:
```python
    async def get_gene_curations(
        gene_symbol: str | None = None,
        hgnc_id: str | None = None,
        response_mode: _MODE = "compact",
        limit: int = 50,
        offset: int = 0,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        gene = coalesce_gene(gene_symbol, hgnc_id, required=True)
        async def call() -> dict[str, Any]:
            payload = get_gencc_service().get_gene_curations(
                gene, response_mode=response_mode, limit=limit, offset=offset, cursor=cursor
            )
            gene_arg = payload.get("gene", {}).get("gene_curie", gene)
            disease_curies = [d["disease_curie"] for d in payload.get("diseases", [])]
            nexts: list[dict[str, Any]] = []
            trunc = payload.get("truncated") or {}
            if trunc.get("next_cursor"):
                nexts.append(cmd("get_gene_curations", hgnc_id=gene_arg, cursor=trunc["next_cursor"]))
            nexts.extend(after_gene_curations(gene_arg, disease_curies))
            payload["_meta"] = {"next_commands": nexts[:5]}
            return payload

        return await run_mcp_tool(
            "get_gene_curations",
            call,
            context=McpErrorContext(
                "get_gene_curations", arguments={"gene_symbol": gene_symbol, "hgnc_id": hgnc_id}
            ),
            response_mode=response_mode,
        )
```
Add import: `from gencc_link.mcp.tools._args import coalesce_gene`. Update the
tool `description` to say it takes `gene_symbol` (approved symbol) or `hgnc_id`
(HGNC CURIE). `coalesce_gene` runs **outside** `call()` so a validation error is
raised before the body and still flows through `run_mcp_tool`'s envelope (it is
inside the awaited tool function; `run_mcp_tool` wraps the raise). If the raise
must be inside the wrapped scope, move the `gene = coalesce_gene(...)` line to the
first line of `call()`.

- [ ] **Step 2: Migrate test_tools.py call sites for get_gene_curations**

Change `{"gene": "SKI"}` → `{"gene_symbol": "SKI"}` in `test_get_gene_curations_success`
and any other `get_gene_curations` calls. Add:
```python
async def test_get_gene_curations_by_hgnc_id(mcp_client) -> None:
    result = await mcp_client.call_tool("get_gene_curations", {"hgnc_id": "HGNC:10896"})
    assert result.structured_content["success"] is True


async def test_get_gene_curations_requires_a_gene(mcp_client) -> None:
    result = await mcp_client.call_tool("get_gene_curations", {})
    assert result.structured_content["success"] is False
    assert result.structured_content["error"]["code"] == "invalid_input"
```

- [ ] **Step 3: Run**

Run: `uv run pytest tests/test_tools.py -v -k gene_curations`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add gencc_link/mcp/tools/genes.py tests/test_tools.py
git commit -m "feat(naming)!: get_gene_curations takes gene_symbol/hgnc_id (fleet canon)"
```

---

## Task 6: Split `gene` in assertions.py + migrate tests

**Files:**
- Modify: `gencc_link/mcp/tools/assertions.py:45-69` (`get_gene_disease_assertion`), `:95-146` (`find_curations`)
- Modify: `tests/test_tools.py` (`get_gene_disease_assertion` / `find_curations` call sites)

- [ ] **Step 1: `get_gene_disease_assertion`**

```python
    async def get_gene_disease_assertion(
        disease: str,
        gene_symbol: str | None = None,
        hgnc_id: str | None = None,
        response_mode: _MODE = "standard",
    ) -> dict[str, Any]:
        gene = coalesce_gene(gene_symbol, hgnc_id, required=True)
        async def call() -> dict[str, Any]:
            payload = get_gencc_service().get_gene_disease_assertion(
                gene, disease, response_mode=response_mode
            )
            assertion = payload.get("assertion", {})
            payload["_meta"] = {
                "next_commands": after_assertion(
                    assertion.get("gene_curie", gene), assertion.get("disease_curie", disease)
                )
            }
            return payload

        return await run_mcp_tool(
            "get_gene_disease_assertion",
            call,
            context=McpErrorContext(
                "get_gene_disease_assertion",
                arguments={"gene_symbol": gene_symbol, "hgnc_id": hgnc_id, "disease": disease},
            ),
            response_mode=response_mode,
        )
```
(`disease` becomes the first positional param so the required arg keeps a clean
schema; clients call by keyword anyway.)

- [ ] **Step 2: `find_curations`** — change `gene: str | None = None` to the pair (optional filter):

```python
    async def find_curations(
        gene_symbol: str | None = None,
        hgnc_id: str | None = None,
        disease: str | None = None,
        classification: list[str] | None = None,
        submitter: list[str] | None = None,
        moi: str | None = None,
        has_conflict: bool | None = None,
        response_mode: _MODE = "compact",
        ids_only: bool = False,
        limit: int = 50,
        offset: int = 0,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        gene = coalesce_gene(gene_symbol, hgnc_id, required=False)
        async def call() -> dict[str, Any]:
            payload = get_gencc_service().find_curations(
                gene=gene,
                disease=disease,
                classification=classification,
                submitter=submitter,
                moi=moi,
                has_conflict=has_conflict,
                response_mode=response_mode,
                ids_only=ids_only,
                limit=limit,
                offset=offset,
                cursor=cursor,
            )
            # ... unchanged next_commands body ...
```
Add `from gencc_link.mcp.tools._args import coalesce_gene` import. Update both
descriptions to reference `gene_symbol`/`hgnc_id`.

- [ ] **Step 3: Migrate test_tools.py**

`get_gene_disease_assertion` calls: `{"gene": "GLA", "disease": ...}` →
`{"gene_symbol": "GLA", "disease": ...}`. `find_curations` calls using `gene=` →
`gene_symbol=`. Add an `hgnc_id` variant + a "both provided → invalid_input" test.

- [ ] **Step 4: Run**

Run: `uv run pytest tests/test_tools.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add gencc_link/mcp/tools/assertions.py tests/test_tools.py
git commit -m "feat(naming)!: assertion/find tools take gene_symbol/hgnc_id"
```

---

## Task 7: next_commands emit hgnc_id + recovery

**Files:**
- Modify: `gencc_link/mcp/next_commands.py`
- Modify: `tests/test_next_commands.py`

- [ ] **Step 1: Add `gene_kwargs` helper at top of next_commands.py**

```python
def gene_kwargs(value: str) -> dict[str, str]:
    """Map a gene value to the canonical arg: HGNC CURIE -> hgnc_id else gene_symbol."""
    return {"hgnc_id": value} if value.upper().startswith("HGNC:") else {"gene_symbol": value}
```

- [ ] **Step 2: Replace every `gene=<value>` in `cmd("get_gene_curations"/"get_gene_disease_assertion", gene=...)`**

The builders carry resolved `gene_curie` values, so emit `hgnc_id=`:
- `after_search_genes`: `cmd("get_gene_curations", hgnc_id=c)`
- `after_gene_curations`: `cmd("get_gene_disease_assertion", hgnc_id=gene, disease=...)`
- `after_disease_curations`: `cmd("get_gene_disease_assertion", hgnc_id=gene_curies[0], disease=disease)`
- `after_genes_curations` / `after_diseases_curations`: `hgnc_id=gene["gene_curie"]` / `hgnc_id=genes[0]["gene_curie"]`
- `after_assertion`: `cmd("get_gene_curations", hgnc_id=gene)`

- [ ] **Step 3: Update `recovery_commands`** to read the new keys and emit canonical args:

```python
    gene_in = arguments.get("hgnc_id") or arguments.get("gene_symbol") or arguments.get("gene")
    if error_code == "not_found":
        if tool == "get_gene_curations" and gene_in:
            return [cmd("search_genes", query=gene_in)]
        if tool == "get_disease_curations" and arguments.get("disease"):
            return [cmd("search_diseases", query=arguments["disease"])]
        if tool == "get_gene_disease_assertion":
            out: list[dict[str, Any]] = []
            if gene_in:
                out.append(cmd("get_gene_curations", **gene_kwargs(gene_in)))
            if arguments.get("disease"):
                out.append(cmd("get_disease_curations", disease=arguments["disease"]))
            return out
        # resolve_identifier branch unchanged
    if error_code == "ambiguous_query" and tool == "resolve_identifier" and arguments.get("query"):
        return [
            cmd("get_gene_curations", **gene_kwargs(arguments["query"])),
            cmd("get_disease_curations", disease=arguments["query"]),
        ]
    # ... rest unchanged ...
```
Also `resolve_identifier`'s success path (`assertions.py:181`) emits
`cmd("get_gene_curations", gene=...)` → `cmd("get_gene_curations", **gene_kwargs(curie))`
or simply `hgnc_id=curie` (the value is a `gene_curie`). Use `hgnc_id=`.

- [ ] **Step 4: Migrate test_next_commands.py**

Update assertions that expect `{"gene": ...}` in emitted arguments to `{"hgnc_id": ...}`
(resolved-curie cases) and add a `gene_kwargs` unit test.

- [ ] **Step 5: Run**

Run: `uv run pytest tests/test_next_commands.py tests/test_envelope.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add gencc_link/mcp/next_commands.py gencc_link/mcp/tools/assertions.py tests/test_next_commands.py
git commit -m "feat(naming): next_commands/recovery emit canonical gene args"
```

---

## Task 8: capabilities parameter_conventions + workflows

**Files:**
- Modify: `gencc_link/mcp/capabilities.py:90-111`
- Modify: `tests/test_capabilities.py` (if it asserts `parameter_conventions` keys)

- [ ] **Step 1: Update `parameter_conventions`**

Replace the `gene` key with `gene_symbol` and `hgnc_id`:
```python
            "gene_symbol": "approved gene symbol (SKI); exact match",
            "hgnc_id": "HGNC CURIE (HGNC:10896); exact match",
            "genes": "list of gene symbols or HGNC CURIEs (max 20); batch form",
```
Update `recommended_workflows` strings that say `get_gene_curations` to reflect
the arg (e.g. `gene symbol -> search_genes -> get_gene_curations(gene_symbol=...)`).
Note: this changes `capabilities_version` (expected; it is a content hash).

- [ ] **Step 2: Run capabilities + tools tests**

Run: `uv run pytest tests/test_capabilities.py tests/test_tools.py -v`
Expected: PASS (fix any hard-coded `parameter_conventions` assertion).

- [ ] **Step 3: Commit**

```bash
git add gencc_link/mcp/capabilities.py tests/test_capabilities.py
git commit -m "docs(capabilities): document gene_symbol/hgnc_id arg canon"
```

---

## Task 9: README federation/namespace docs

**Files:**
- Modify: `README.md` (after "Available MCP tools" or "Data source & license")

- [ ] **Step 1: Add the section**

```markdown
## GeneFoundry federation

GenCC-Link is part of the **GeneFoundry** `*-link` MCP fleet, federated behind the
[`genefoundry-router`](https://github.com/berntpopp/genefoundry-router) gateway.

- **`serverInfo.name`:** `gencc-link` (stable identity).
- **Gateway namespace token:** `gencc`. The router mounts this server with
  `namespace="gencc"`, so tools surface at the gateway as `gencc_<tool>` (e.g.
  `gencc_search_genes`). Standalone MCP clients namespace it as
  `mcp__gencc-link__<tool>`.
- **Unprefixed leaves:** tool names are intentionally **not** server-prefixed —
  namespacing is the gateway's job (Tool-Naming Standard v1, Rule 1). A CI guard
  (`tests/test_tool_naming.py`) enforces `^[a-z0-9_]{1,50}$` + a canonical verb on
  every tool.
- **Canonical arguments:** `gene_symbol` (approved symbol) / `hgnc_id` (HGNC
  CURIE), `disease` (MONDO/OMIM CURIE or title), `response_mode`, `limit`/`offset`.
```

- [ ] **Step 2: Update any `gene` examples** in README/docs to `gene_symbol`/`hgnc_id`.
Run: `grep -rnE "\"gene\"|gene=" README.md docs/usage.md`
Fix each gene-arg example. (No `"gene"` matches found in current README; check docs/usage.md.)

- [ ] **Step 3: Commit**

```bash
git add README.md docs/
git commit -m "docs(readme): document GeneFoundry namespace token + arg canon (issue #3 Rule 5)"
```

---

## Task 10: Release plumbing — 0.5.0

**Files:**
- Modify: `pyproject.toml:7` (version)
- Modify: `CHANGELOG.md` (new entry at top)

- [ ] **Step 1: Bump version**

`version = "0.4.0"` → `version = "0.5.0"` in `pyproject.toml`.

- [ ] **Step 2: Add CHANGELOG entry**

```markdown
## [0.5.0] - 2026-06-15

Adopts the GeneFoundry Tool-Naming Standard v1 (issue #3) and lands two
dependency bumps. See
`docs/superpowers/specs/2026-06-15-tool-naming-standard-v1-design.md`.

### Changed

- **BREAKING — fleet-canonical gene arguments.** `get_gene_curations`,
  `get_gene_disease_assertion`, and `find_curations` no longer accept `gene`;
  pass `gene_symbol` (approved symbol) **or** `hgnc_id` (HGNC CURIE) instead
  (exactly one on the first two; at most one on `find_curations`). Batch
  `get_genes_curations` keeps `genes` (a polymorphic symbol/HGNC list). No
  deprecation alias (pre-1.0). `_meta.next_commands` now emit `hgnc_id`.
- `parameter_conventions` in the capabilities surface documents
  `gene_symbol`/`hgnc_id` (this changes `capabilities_version`).

### Added

- **Tool-Naming Standard v1 CI guard** (`tests/test_tool_naming.py`): every
  registered tool must match `^[a-z0-9_]{1,50}$`, start with a canonical verb,
  and carry a domain tag — mirroring `genefoundry-router`'s `check_leaf_name`.
- **README "GeneFoundry federation" section** documenting the `gencc` gateway
  namespace token and unprefixed-leaf policy.

### Build

- `uvicorn[standard]` floor → 0.49.0; `mcp[cli]` floor → 1.27.2 (supersedes #2).
- Docker base image → `python:3.14-slim` (supersedes #1).
```

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml CHANGELOG.md
git commit -m "release(0.5.0): version bump + changelog (Tool-Naming Standard v1)"
```

---

## Task 11: Final verification

- [ ] **Step 1: Full local CI**

Run: `make ci-local`
Expected: format-check, lint-ci, lint-loc, typecheck-fast, test-fast all PASS.
Fix anything that fails (re-run after each fix).

- [ ] **Step 2: Coverage gate (CI also runs this)**

Run: `make test-cov`
Expected: ≥85% coverage, PASS.

- [ ] **Step 3: Docker 3.14 build smoke test**

Run: `docker build -f docker/Dockerfile -t gencc-link:3.14-test .`
Expected: build succeeds (deps resolve cp314 wheels). If it fails on a missing
3.14 wheel, report the offending package and revert Task 2 to 3.13-slim, noting
the blocker. (Skip gracefully if Docker is unavailable in the environment.)

- [ ] **Step 4: Push branch + open PR**

```bash
git push -u origin feat/tool-naming-standard-v1
gh pr create --title "feat: adopt Tool-Naming Standard v1 + dep bumps (0.5.0)" --body "..."
```
PR body: closes #3; notes that stale dependabot PRs #1 and #2 are superseded and
can be closed.

---

## Self-Review

- **Spec coverage:** A=Task 3; B=Tasks 4–8; C=Task 9; D=Tasks 1,2; E=Task 10;
  verification=Task 11. All spec sections mapped.
- **Placeholders:** none — every code step shows the code; PR body text is the one
  free-form artifact (acceptable).
- **Type consistency:** `coalesce_gene(gene_symbol, hgnc_id, *, required)` and
  `gene_kwargs(value)` signatures used consistently across Tasks 4–8.
- **Risk note:** `coalesce_gene` raising before `call()` — confirm `run_mcp_tool`
  still wraps the raise into an envelope; if not, move the call to the first line
  inside `call()` (noted in Task 5 Step 1).
