# Batch Tools, find_curations Latency & Version Probe — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Push the GenCC-Link MCP server from 9/10 to >9.5/10 by adding batch curation tools, fixing the `find_curations` latency at its true root cause, completing the index coverage, echoing a version hash for cheap drift detection, and adding `ids_only` paging.

**Architecture:** All changes follow existing patterns — tools in `gencc_link/mcp/tools/` delegate to `GenCCService` (`gencc_link/services/gencc_service.py`), which calls the read-only `GenCCRepository`. The latency fix is a pure query rewrite in the repository; batch tools are service orchestration over existing repository methods; the version probe and `ids_only` are additive fields/params.

**Tech Stack:** Python 3.12, FastMCP, SQLite + FTS5, pydantic v2, pytest (+ pytest-asyncio, respx), Ruff, mypy strict, `uv`.

**Reference docs:**
- Spec: `docs/superpowers/specs/2026-06-12-mcp-ux-batch-and-latency-design.md`
- Repo skills: `.claude/skills/mcp-tool-change`, `.claude/skills/data-schema-change`
- Conventions: `AGENTS.md` (600-line cap, ASCII, `make ci-local`)

**Final check after every task:** the touched module stays ≤600 lines (`make lint-loc`).

---

## Task 1: Fix `find_curations` latency (P1 — query rewrite, no schema change)

The 59 ms outlier is `_gene_disease_rows_for_pairs` running `SELECT * FROM gene_disease ORDER BY …` (full scan of 14,131 rows + temp-B-tree sort). Replace it with a targeted primary-key lookup over only the matched pairs, and push `has_conflict` into SQL.

**Files:**
- Modify: `gencc_link/data/repository.py` (`_gene_disease_rows_for_pairs`, ~514-528)
- Test: `tests/test_repository.py`

- [ ] **Step 1: Write a failing test that pins the matched-pair result + ordering + has_conflict in SQL.**

Add to `tests/test_repository.py` (inside the find-assertions test class):

```python
def test_find_assertions_pair_lookup_matches_and_orders(self, repository: GenCCRepository) -> None:
    # Refuted Evidence exists for the GLA conflict pair in the fixture.
    page, total, matched = repository.find_assertions(
        classification=["Refuted Evidence"], limit=50, offset=0
    )
    assert total == len(page)
    assert page, "expected at least one Refuted Evidence pair"
    # Every returned pair is present in the matched map (submission-level filter active).
    for a in page:
        assert (a.gene_curie, a.disease_curie) in matched
    # Ordering is by consensus_rank DESC then gene_symbol then disease_title.
    ranks = [a.consensus_rank for a in page if a.consensus_rank is not None]
    assert ranks == sorted(ranks, reverse=True)

def test_find_assertions_has_conflict_filter_with_submission_filter(
    self, repository: GenCCRepository
) -> None:
    # GLA's Refuted pair conflicts; has_conflict=False must exclude it.
    confl, _t1, _m1 = repository.find_assertions(
        classification=["Refuted Evidence"], has_conflict=True, limit=50, offset=0
    )
    noconfl, _t2, _m2 = repository.find_assertions(
        classification=["Refuted Evidence"], has_conflict=False, limit=50, offset=0
    )
    assert all(a.has_conflict for a in confl)
    assert all(not a.has_conflict for a in noconfl)
    # matched map is pruned to the rows that survived the conflict filter.
    keys = {(a.gene_curie, a.disease_curie) for a in confl}
    assert all(k in keys for k in _m1)
```

- [ ] **Step 2: Run to verify the new tests pass against current code (they encode existing behaviour — this is a refactor guard, not new behaviour).**

Run: `uv run pytest tests/test_repository.py -k "pair_lookup_matches_and_orders or has_conflict_filter_with_submission_filter" -v`
Expected: PASS (current full-scan code already satisfies them). These lock behaviour before the rewrite.

- [ ] **Step 3: Rewrite `_gene_disease_rows_for_pairs` to a targeted PK lookup.**

Replace the method body in `gencc_link/data/repository.py`:

```python
def _gene_disease_rows_for_pairs(
    self, pairs: set[tuple[str, str]], *, has_conflict: bool | None
) -> list[sqlite3.Row]:
    """Fetch ``gene_disease`` rows for an explicit set of pairs via the primary key.

    Uses a row-value ``IN (VALUES …)`` so SQLite resolves each pair through the
    ``(gene_curie, disease_curie)`` primary-key index instead of scanning the
    whole table. ``SQLITE_LIMIT_VARIABLE_NUMBER`` (>=250k here) comfortably
    covers the worst case (all rows of ``gene_disease``).
    """
    if not pairs:
        return []
    values = ",".join("(?,?)" for _ in pairs)
    params: list[object] = [value for pair in pairs for value in pair]
    where = f"(gene_curie, disease_curie) IN (VALUES {values})"
    if has_conflict is not None:
        where += " AND has_conflict = ?"
        params.append(1 if has_conflict else 0)
    sql = (
        f"SELECT * FROM gene_disease WHERE {where} "
        "ORDER BY consensus_rank DESC, gene_symbol, disease_title"
    )
    return self._conn.execute(sql, params).fetchall()
```

Then in `find_assertions`, the `has_conflict` post-filter is now handled in SQL; keep the matched-pruning step (it still drops matched entries for pairs removed by the conflict filter) — no other change needed:

```python
        if submission_filtered:
            matched = self._matched_from_submissions(
                gene_curie=gene_curie,
                disease_curie=disease,
                classification=classification,
                submitter=submitter,
                moi=moi,
            )
            if not matched:
                return [], 0, {}
            rows = self._gene_disease_rows_for_pairs(set(matched), has_conflict=has_conflict)
            kept = {(r["gene_curie"], r["disease_curie"]) for r in rows}
            matched = {k: v for k, v in matched.items() if k in kept}
```

- [ ] **Step 4: Run the full repository + service + tool suites to confirm no regression.**

Run: `uv run pytest tests/test_repository.py tests/test_service.py tests/test_tools.py -q`
Expected: PASS (all existing find_curations / find_assertions tests still green).

- [ ] **Step 5: Manually verify the performance win against the real database (evidence, not a CI test).**

Run:

```bash
uv run python - <<'PY'
import sqlite3, time, statistics
from gencc_link.data.repository import GenCCRepository
repo = GenCCRepository("data/gencc.sqlite")
def med(fn, n=15):
    ts=[]
    for _ in range(n):
        t=time.perf_counter(); fn(); ts.append((time.perf_counter()-t)*1000)
    return round(min(ts),3), round(statistics.median(ts),3)
fn = lambda: repo.find_assertions(classification=["Definitive"], submitter=["ClinGen"], moi="Autosomal dominant", limit=50, offset=0)
print("classification+submitter+moi min/med ms:", med(fn))
con = sqlite3.connect("data/gencc.sqlite")
plan = " ".join(r[3] for r in con.execute(
    "EXPLAIN QUERY PLAN SELECT * FROM gene_disease WHERE (gene_curie,disease_curie) IN (VALUES (?,?)) "
    "ORDER BY consensus_rank DESC, gene_symbol, disease_title", ["HGNC:1101","MONDO:0008426"]))
print("plan:", plan)
assert "SCAN gene_disease" not in plan, plan
repo.close(); con.close()
PY
```

Expected: median well under 3 ms (was ~59 ms) and the plan shows `SEARCH gene_disease USING INDEX sqlite_autoindex_gene_disease_1`, not `SCAN gene_disease`.

- [ ] **Step 6: Commit.**

```bash
git add gencc_link/data/repository.py tests/test_repository.py
git commit -m "perf(find_curations): targeted PK lookup instead of gene_disease full scan

Replace the SELECT * FROM gene_disease full scan in _gene_disease_rows_for_pairs
with a row-value IN (VALUES ...) lookup over only the matched pairs, and push
has_conflict into SQL. The flagged 59ms outlier (classification/submitter/moi
filters) drops to <3ms against the live 14k-row database. No schema change.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## Task 2: Complete index coverage (P2 — schema indexes; uses data-schema-change skill)

Submitter-only and moi-only filters still `SCAN submissions` because `idx_sub_submitter` is on `submitter_curie` and `idx_sub_moi` (BINARY) cannot serve `COLLATE NOCASE`. Add two indexes. No `schema_version` bump (indexes do not change results).

**Files:**
- Modify: `gencc_link/data/schema.sql` (after line 50, the `submissions` indexes)
- Test: `tests/test_repository.py`
- One-off: migrate the live `data/gencc.sqlite` in place (no download)

- [ ] **Step 1: Write a failing test that the two indexes exist in the built schema.**

Add to `tests/test_repository.py`:

```python
def test_submission_filter_indexes_present(self, repository: GenCCRepository) -> None:
    names = {
        row[0]
        for row in repository._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        )
    }
    assert "idx_sub_submitter_title" in names
    assert "idx_sub_moi_nocase" in names
```

- [ ] **Step 2: Run to verify it fails.**

Run: `uv run pytest tests/test_repository.py -k submission_filter_indexes_present -v`
Expected: FAIL (indexes do not exist yet).

- [ ] **Step 3: Add the indexes to `schema.sql`.**

After `CREATE INDEX idx_sub_gene_disease ON submissions(gene_curie, disease_curie);` add:

```sql
CREATE INDEX idx_sub_submitter_title ON submissions(submitter_title);
CREATE INDEX idx_sub_moi_nocase ON submissions(moi_title COLLATE NOCASE);
```

- [ ] **Step 4: Run the test (the conftest rebuilds the fixture DB from schema.sql each session, so the indexes appear automatically).**

Run: `uv run pytest tests/test_repository.py -k submission_filter_indexes_present -v`
Expected: PASS.

- [ ] **Step 5: Migrate the live database in place (no network — indexes build from existing rows) and verify the moi index is used on the real DB.**

Run:

```bash
uv run python - <<'PY'
import sqlite3
con = sqlite3.connect("data/gencc.sqlite")
con.execute("CREATE INDEX IF NOT EXISTS idx_sub_submitter_title ON submissions(submitter_title)")
con.execute("CREATE INDEX IF NOT EXISTS idx_sub_moi_nocase ON submissions(moi_title COLLATE NOCASE)")
con.commit()
moi_plan = " ".join(r[3] for r in con.execute(
    "EXPLAIN QUERY PLAN SELECT gene_curie,disease_curie FROM submissions WHERE moi_title = ? COLLATE NOCASE",
    ("Autosomal dominant",)))
print("moi plan:", moi_plan)
assert "idx_sub_moi_nocase" in moi_plan, moi_plan
sub_plan = " ".join(r[3] for r in con.execute(
    "EXPLAIN QUERY PLAN SELECT gene_curie,disease_curie FROM submissions "
    "WHERE (submitter_title IN (?) OR submitter_curie IN (?))", ("ClinGen","ClinGen")))
print("submitter plan:", sub_plan)  # informational: OR-union may or may not engage
con.close()
PY
```

Expected: the moi plan contains `idx_sub_moi_nocase` (provable index use). The submitter plan is informational — the P1 fix already removed the dominant cost, so a residual scan there is acceptable.

- [ ] **Step 6: Commit.**

```bash
git add gencc_link/data/schema.sql tests/test_repository.py
git commit -m "perf(schema): index submitter_title and moi (NOCASE) for find_curations

Add idx_sub_submitter_title and idx_sub_moi_nocase so submitter-only and
moi-only find_curations filters use an index instead of scanning submissions.
No schema_version bump (indexes do not change query results); the live DB is
migrated in place with CREATE INDEX (no download).

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## Task 3: Batch service methods (B1 — `get_genes_curations` / `get_diseases_curations`)

Add the orchestration to `GenCCService`, reusing single-entity logic per item with partial-failure semantics.

**Files:**
- Modify: `gencc_link/services/gencc_service.py` (add `_BATCH_MAX`; two methods after `get_disease_curations`, ~213)
- Test: `tests/test_service.py`

- [ ] **Step 1: Write failing tests.**

Add to `tests/test_service.py`:

```python
class TestBatchCurations:
    def test_genes_curations_two_hits(self, service: GenCCService) -> None:
        out = service.get_genes_curations(["SKI", "GLA"])
        assert out["requested"] == 2
        assert out["count"] == 2
        symbols = {b["gene"]["gene_symbol"] for b in out["results"]}
        assert {"SKI", "GLA"} <= symbols
        assert "unresolved" not in out  # omitted when empty

    def test_genes_curations_dedupes_preserving_order(self, service: GenCCService) -> None:
        out = service.get_genes_curations(["SKI", "ski", "SKI"])
        assert out["requested"] == 1
        assert out["count"] == 1

    def test_genes_curations_partial_unresolved(self, service: GenCCService) -> None:
        out = service.get_genes_curations(["SKI", "NOTAGENE"])
        assert out["count"] == 1
        assert out["unresolved"] == [{"input": "NOTAGENE", "reason": "not_found"}]

    def test_genes_curations_all_unresolved_still_succeeds(self, service: GenCCService) -> None:
        out = service.get_genes_curations(["NOPE1", "NOPE2"])
        assert out["count"] == 0
        assert len(out["unresolved"]) == 2

    def test_genes_curations_empty_raises(self, service: GenCCService) -> None:
        import pytest

        from gencc_link.exceptions import InvalidInputError

        with pytest.raises(InvalidInputError):
            service.get_genes_curations([])

    def test_genes_curations_over_cap_raises(self, service: GenCCService) -> None:
        import pytest

        from gencc_link.exceptions import InvalidInputError

        with pytest.raises(InvalidInputError):
            service.get_genes_curations([f"G{i}" for i in range(21)])

    def test_diseases_curations_two_hits(self, service: GenCCService) -> None:
        out = service.get_diseases_curations(["MONDO:0008426", "MONDO:0010526"])
        assert out["requested"] == 2
        assert out["count"] >= 1
        assert all("genes" in b for b in out["results"])
```

- [ ] **Step 2: Run to verify they fail.**

Run: `uv run pytest tests/test_service.py -k TestBatchCurations -v`
Expected: FAIL (`AttributeError: 'GenCCService' object has no attribute 'get_genes_curations'`).

- [ ] **Step 3: Implement the batch methods.**

In `gencc_link/services/gencc_service.py`, add the cap constant near `_MAX_LIMIT = 200`:

```python
_BATCH_MAX = 20
```

Add a private helper and the two methods after `get_disease_curations`:

```python
    @staticmethod
    def _dedupe_batch(items: list[str], *, field: str) -> list[str]:
        if not items:
            raise InvalidInputError(f"{field} must not be empty.", field=field)
        if len(items) > _BATCH_MAX:
            raise InvalidInputError(
                f"Too many values ({len(items)}); max {_BATCH_MAX} per call.", field=field
            )
        seen: set[str] = set()
        ordered: list[str] = []
        for raw in items:
            if not isinstance(raw, str) or not raw.strip():
                raise InvalidInputError(f"each {field} value must be a non-empty string.", field=field)
            value = raw.strip()
            if value.lower() in seen:
                continue
            seen.add(value.lower())
            ordered.append(value)
        return ordered

    def get_genes_curations(
        self, genes: list[str], *, response_mode: str = "compact", limit_per_gene: int = 50
    ) -> dict[str, Any]:
        mode = self._validate_mode(response_mode)
        ordered = self._dedupe_batch(genes, field="genes")
        limit = self._clamp_limit(limit_per_gene)
        results: list[dict[str, Any]] = []
        unresolved: list[dict[str, str]] = []
        for gene in ordered:
            summary = self._repo.resolve_gene(gene)
            if summary is None:
                unresolved.append({"input": gene, "reason": "not_found"})
                continue
            pairs = self._repo.get_gene_disease_pairs(summary.gene_curie)
            total = len(pairs)
            page = pairs[:limit]
            block: dict[str, Any] = {
                "gene": shaping.gene_summary_dict(summary, mode),
                "headline": shaping.gene_headline(summary),
                "count": len(page),
                "total": total,
                "diseases": [shaping.assertion_dict(a, mode, omit_gene=True) for a in page],
            }
            trunc = shaping.truncation_block(total, limit, 0)
            if trunc:
                block["truncated"] = trunc
            results.append(block)
        payload: dict[str, Any] = {
            "headline": (
                f"Curations for {len(results)} of {len(ordered)} requested gene(s) "
                f"({len(unresolved)} unresolved)."
            ),
            "requested": len(ordered),
            "count": len(results),
            "results": results,
        }
        if unresolved:
            payload["unresolved"] = unresolved
        return payload

    def get_diseases_curations(
        self, diseases: list[str], *, response_mode: str = "compact", limit_per_disease: int = 50
    ) -> dict[str, Any]:
        mode = self._validate_mode(response_mode)
        ordered = self._dedupe_batch(diseases, field="diseases")
        limit = self._clamp_limit(limit_per_disease)
        results: list[dict[str, Any]] = []
        unresolved: list[dict[str, str]] = []
        for disease in ordered:
            summary = self._repo.resolve_disease(disease)
            if summary is None:
                unresolved.append({"input": disease, "reason": "not_found"})
                continue
            pairs = self._repo.get_disease_gene_pairs(summary.disease_curie)
            total = len(pairs)
            page = pairs[:limit]
            block: dict[str, Any] = {
                "disease": shaping.disease_summary_dict(summary, mode),
                "headline": shaping.disease_headline(summary),
                "count": len(page),
                "total": total,
                "genes": [shaping.assertion_dict(a, mode, omit_disease=True) for a in page],
            }
            trunc = shaping.truncation_block(total, limit, 0)
            if trunc:
                block["truncated"] = trunc
            results.append(block)
        payload: dict[str, Any] = {
            "headline": (
                f"Curations for {len(results)} of {len(ordered)} requested disease(s) "
                f"({len(unresolved)} unresolved)."
            ),
            "requested": len(ordered),
            "count": len(results),
            "results": results,
        }
        if unresolved:
            payload["unresolved"] = unresolved
        return payload
```

- [ ] **Step 4: Run to verify the tests pass.**

Run: `uv run pytest tests/test_service.py -k TestBatchCurations -v`
Expected: PASS.

- [ ] **Step 5: Commit.**

```bash
git add gencc_link/services/gencc_service.py tests/test_service.py
git commit -m "feat(service): batch get_genes_curations / get_diseases_curations

Orchestrate per-entity curations with dedupe, a 20-item cap, partial-failure
unresolved list, and per-entity limit + truncation. Reuses single-entity
resolve + pair lookups; no new repository method.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## Task 4: Batch tools + registration + next_commands + capabilities (B1)

Expose the batch service methods as MCP tools, wire next_commands, and register them in the capabilities `TOOLS` tuple. Uses the `mcp-tool-change` skill checklist (tool module, facade registration, capabilities, tests, docs).

**Files:**
- Modify: `gencc_link/mcp/next_commands.py` (two helpers)
- Modify: `gencc_link/mcp/tools/genes.py` (register `get_genes_curations`)
- Modify: `gencc_link/mcp/tools/diseases.py` (register `get_diseases_curations`)
- Modify: `gencc_link/mcp/capabilities.py` (`TOOLS`, hints, workflow, conventions)
- Test: `tests/test_tools.py`, `tests/test_capabilities.py`

- [ ] **Step 1: Write failing tool + capabilities tests.**

In `tests/test_tools.py`, update the tool-count expectations and add batch tests:

```python
EXPECTED_TOOLS = {
    "get_server_capabilities",
    "get_gencc_diagnostics",
    "search_genes",
    "search_diseases",
    "get_gene_curations",
    "get_disease_curations",
    "get_genes_curations",
    "get_diseases_curations",
    "get_gene_disease_assertion",
    "find_curations",
    "list_submitters",
    "resolve_identifier",
}
```

Change `test_capabilities_tool` `len(data["tools"]) == 10` to `== 12`. Then add:

```python
class TestBatchTools:
    async def test_genes_curations_multi(self, mcp_client) -> None:
        result = await mcp_client.call_tool(
            "get_genes_curations", {"genes": ["SKI", "GLA"]}
        )
        data = result.structured_content
        assert data["success"] is True
        assert data["count"] == 2
        assert data["_meta"]["citation_ref"] == "gencc://citation"
        assert data["_meta"]["next_commands"]

    async def test_genes_curations_partial_next_command(self, mcp_client) -> None:
        result = await mcp_client.call_tool(
            "get_genes_curations", {"genes": ["SKI", "NOTAGENE"]}
        )
        data = result.structured_content
        assert data["success"] is True
        assert data["unresolved"][0]["input"] == "NOTAGENE"
        assert data["_meta"]["next_commands"][0] == {
            "tool": "search_genes",
            "arguments": {"query": "NOTAGENE"},
        }

    async def test_genes_curations_over_cap_invalid(self, mcp_client) -> None:
        result = await mcp_client.call_tool(
            "get_genes_curations", {"genes": [f"G{i}" for i in range(21)]}
        )
        data = result.structured_content
        assert data["success"] is False
        assert data["error_code"] == "invalid_input"

    async def test_diseases_curations_multi(self, mcp_client) -> None:
        result = await mcp_client.call_tool(
            "get_diseases_curations",
            {"diseases": ["MONDO:0008426", "MONDO:0010526"]},
        )
        data = result.structured_content
        assert data["success"] is True
        assert data["count"] >= 1
```

In `tests/test_capabilities.py`, change both `== 10` assertions in `test_ten_tools` to `== 12` and rename to `test_twelve_tools`; add:

```python
    def test_batch_tools_listed(self) -> None:
        caps = build_capabilities()
        assert "get_genes_curations" in caps["tools"]
        assert "get_diseases_curations" in caps["tools"]
```

- [ ] **Step 2: Run to verify they fail.**

Run: `uv run pytest tests/test_tools.py tests/test_capabilities.py -q`
Expected: FAIL (tools not registered; counts mismatch).

- [ ] **Step 3: Add next_commands helpers.**

In `gencc_link/mcp/next_commands.py`, add after `after_disease_curations`:

```python
def after_genes_curations(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """After a batch of genes: retry the first miss, else drill into the first hit."""
    unresolved = payload.get("unresolved") or []
    if unresolved:
        return [cmd("search_genes", query=unresolved[0]["input"])]
    results = payload.get("results") or []
    if results:
        top = results[0]
        diseases = top.get("diseases") or []
        if diseases:
            return [
                cmd(
                    "get_gene_disease_assertion",
                    gene=top["gene"]["gene_curie"],
                    disease=diseases[0]["disease_curie"],
                )
            ]
    return []


def after_diseases_curations(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """After a batch of diseases: retry the first miss, else drill into the first hit."""
    unresolved = payload.get("unresolved") or []
    if unresolved:
        return [cmd("search_diseases", query=unresolved[0]["input"])]
    results = payload.get("results") or []
    if results:
        top = results[0]
        genes = top.get("genes") or []
        if genes:
            return [
                cmd(
                    "get_gene_disease_assertion",
                    gene=genes[0]["gene_curie"],
                    disease=top["disease"]["disease_curie"],
                )
            ]
    return []
```

- [ ] **Step 4: Register `get_genes_curations` in `genes.py`.**

Add the import and tool. Update the import line:

```python
from gencc_link.mcp.next_commands import (
    after_gene_curations,
    after_genes_curations,
    after_search_genes,
)
```

Add inside `register_gene_tools`, after `get_gene_curations`:

```python
    @mcp.tool(
        name="get_genes_curations",
        title="Get Curations for Many Genes",
        annotations=READ_ONLY_OPEN_WORLD,
        tags={"gene", "batch"},
        description=(
            "Batch form of get_gene_curations: pass a list of gene symbols or HGNC "
            "ids (max 20) and get each gene's disease assertions in one call. "
            "Unresolvable inputs are returned in `unresolved` (the call still "
            "succeeds). Use limit_per_gene to cap diseases per gene."
        ),
    )
    async def get_genes_curations(
        genes: list[str],
        response_mode: _MODE = "compact",
        limit_per_gene: int = 50,
    ) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            payload = get_gencc_service().get_genes_curations(
                genes, response_mode=response_mode, limit_per_gene=limit_per_gene
            )
            payload["_meta"] = {"next_commands": after_genes_curations(payload)}
            return payload

        return await run_mcp_tool(
            "get_genes_curations",
            call,
            context=McpErrorContext("get_genes_curations", arguments={"genes": genes}),
            response_mode=response_mode,
        )
```

- [ ] **Step 5: Register `get_diseases_curations` in `diseases.py`.**

Update the import line:

```python
from gencc_link.mcp.next_commands import (
    after_disease_curations,
    after_diseases_curations,
    after_search_diseases,
)
```

Add inside `register_disease_tools`, after `get_disease_curations`:

```python
    @mcp.tool(
        name="get_diseases_curations",
        title="Get Curations for Many Diseases",
        annotations=READ_ONLY_OPEN_WORLD,
        tags={"disease", "batch"},
        description=(
            "Batch form of get_disease_curations: pass a list of disease ids or "
            "titles (max 20) and get each disease's gene assertions in one call. "
            "Unresolvable inputs are returned in `unresolved` (the call still "
            "succeeds). Use limit_per_disease to cap genes per disease."
        ),
    )
    async def get_diseases_curations(
        diseases: list[str],
        response_mode: _MODE = "compact",
        limit_per_disease: int = 50,
    ) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            payload = get_gencc_service().get_diseases_curations(
                diseases, response_mode=response_mode, limit_per_disease=limit_per_disease
            )
            payload["_meta"] = {"next_commands": after_diseases_curations(payload)}
            return payload

        return await run_mcp_tool(
            "get_diseases_curations",
            call,
            context=McpErrorContext("get_diseases_curations", arguments={"diseases": diseases}),
            response_mode=response_mode,
        )
```

- [ ] **Step 6: Register both in the capabilities `TOOLS` tuple and add hints/workflow/conventions.**

In `gencc_link/mcp/capabilities.py`, update `TOOLS` (insert after `get_disease_curations`):

```python
    "get_disease_curations",
    "get_genes_curations",
    "get_diseases_curations",
    "get_gene_disease_assertion",
```

Add to `token_cost_hints`:

```python
            "get_genes_curations": "~2-5kB per resolved gene (compact); scales with the list",
            "get_diseases_curations": "~2-5kB per resolved disease (compact); scales with the list",
```

Add to `recommended_workflows` (append):

```python
            "multiple genes at once -> get_genes_curations(genes=['BRCA2','NAA10'])",
```

Add to `parameter_conventions`:

```python
            "genes": "list of gene symbols or HGNC ids (max 20); batch form of `gene`",
            "diseases": "list of disease ids or titles (max 20); batch form of `disease`",
```

- [ ] **Step 7: Run the tool + capabilities suites.**

Run: `uv run pytest tests/test_tools.py tests/test_capabilities.py -q`
Expected: PASS.

- [ ] **Step 8: Commit.**

```bash
git add gencc_link/mcp/next_commands.py gencc_link/mcp/tools/genes.py \
        gencc_link/mcp/tools/diseases.py gencc_link/mcp/capabilities.py \
        tests/test_tools.py tests/test_capabilities.py
git commit -m "feat(mcp): get_genes_curations / get_diseases_curations batch tools

Collapse multi-entity questions into one call. Register in TOOLS, add
token_cost_hints, a batch workflow, parameter conventions, and next_commands
(retry first miss, else drill into first hit).

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## Task 5: Version probe in diagnostics (V1)

Echo `capabilities_version` + `server_version` into `get_gencc_diagnostics` so a warm client can poll a small payload for drift instead of fetching the 4 kB capabilities doc.

**Files:**
- Modify: `gencc_link/mcp/capabilities.py` (add public `server_version()`)
- Modify: `gencc_link/mcp/tools/discovery.py` (echo into diagnostics)
- Modify: `gencc_link/mcp/capabilities.py` (document under `response_fields`)
- Test: `tests/test_tools.py`

- [ ] **Step 1: Write a failing test.**

Add to `tests/test_tools.py` (in `TestDiagnosticsQuota` or a new class):

```python
async def test_diagnostics_has_version_probe(self, mcp_client) -> None:
    import re

    result = await mcp_client.call_tool("get_gencc_diagnostics", {})
    data = result.structured_content
    assert re.fullmatch(r"[0-9a-f]{16}", data["capabilities_version"])
    assert isinstance(data["server_version"], str)
```

- [ ] **Step 2: Run to verify it fails.**

Run: `uv run pytest tests/test_tools.py -k test_diagnostics_has_version_probe -v`
Expected: FAIL (`KeyError: 'capabilities_version'`).

- [ ] **Step 3: Add a public `server_version()` to `capabilities.py`.**

After `capabilities_version()`:

```python
def server_version() -> str:
    """Installed package version (mirrors the capabilities surface)."""
    return str(_static_surface()["server_version"])
```

- [ ] **Step 4: Echo both into the diagnostics result.**

In `gencc_link/mcp/tools/discovery.py`, inside `get_gencc_diagnostics`'s `call()`, add the import and fields. Add at the top of `call()`:

```python
            from gencc_link.mcp.capabilities import capabilities_version, server_version
```

And add the two keys to the `result` dict (before `"data"`):

```python
            result: dict[str, Any] = {
                "headline": (
                    f"GenCC data: {meta.row_count} submissions, {meta.gene_count} genes, "
                    f"{meta.disease_count} diseases from {meta.submitter_count} submitters; "
                    f"run date {meta.gencc_run_date or 'unknown'}."
                ),
                "server_version": server_version(),
                "capabilities_version": capabilities_version(),
                "data": meta.model_dump(),
                "refresh": refresh,
            }
```

- [ ] **Step 5: Document under `response_fields` in `capabilities.py`.**

Add to the `response_fields` dict:

```python
            "capabilities_version": "16-char content hash of the static surface; also "
            "echoed by get_gencc_diagnostics for a near-zero-token drift probe",
```

- [ ] **Step 6: Run the diagnostics + capabilities tests.**

Run: `uv run pytest tests/test_tools.py tests/test_capabilities.py -q`
Expected: PASS.

- [ ] **Step 7: Commit.**

```bash
git add gencc_link/mcp/capabilities.py gencc_link/mcp/tools/discovery.py tests/test_tools.py
git commit -m "feat(diagnostics): echo capabilities_version + server_version probe

get_gencc_diagnostics now carries capabilities_version and server_version so a
warm client polls a small payload for drift instead of re-fetching the 4kB
capabilities document.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## Task 6: `ids_only` paging for `find_curations` (T1)

Add an `ids_only` flag that returns just `{gene_curie, disease_curie}` pairs for cheap paging.

**Files:**
- Modify: `gencc_link/services/gencc_service.py` (`find_curations`)
- Modify: `gencc_link/mcp/tools/assertions.py` (`find_curations` tool param)
- Modify: `gencc_link/mcp/capabilities.py` (document under `parameter_conventions`)
- Test: `tests/test_service.py`, `tests/test_tools.py`

- [ ] **Step 1: Write failing tests.**

Add to `tests/test_service.py` (in the find_curations test class):

```python
def test_ids_only_returns_just_pairs(self, service: GenCCService) -> None:
    full = service.find_curations(classification=["Definitive"])
    ids = service.find_curations(classification=["Definitive"], ids_only=True)
    assert ids["total"] == full["total"]
    assert ids["results"], "expected matches"
    for row in ids["results"]:
        assert set(row.keys()) == {"gene_curie", "disease_curie"}
```

Add to `tests/test_tools.py`:

```python
async def test_find_curations_ids_only(mcp_client) -> None:
    result = await mcp_client.call_tool(
        "find_curations", {"classification": ["Definitive"], "ids_only": True}
    )
    data = result.structured_content
    assert data["success"] is True
    assert all(set(r.keys()) == {"gene_curie", "disease_curie"} for r in data["results"])
```

- [ ] **Step 2: Run to verify they fail.**

Run: `uv run pytest tests/test_service.py tests/test_tools.py -k ids_only -v`
Expected: FAIL (`TypeError: unexpected keyword argument 'ids_only'`).

- [ ] **Step 3: Add `ids_only` to the service `find_curations`.**

In `gencc_link/services/gencc_service.py`, add the parameter to the signature:

```python
    def find_curations(
        self,
        *,
        gene: str | None = None,
        disease: str | None = None,
        classification: list[str] | None = None,
        submitter: list[str] | None = None,
        moi: str | None = None,
        has_conflict: bool | None = None,
        response_mode: str = "compact",
        ids_only: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
```

Replace the row-shaping block with an `ids_only` branch:

```python
        rows: list[dict[str, Any]] = []
        if ids_only:
            rows = [{"gene_curie": a.gene_curie, "disease_curie": a.disease_curie} for a in results]
        else:
            for a in results:
                row = shaping.assertion_dict(a, mode)
                if matched and mode != "minimal":
                    row["matched"] = matched.get((a.gene_curie, a.disease_curie), [])
                rows.append(row)
```

- [ ] **Step 4: Add `ids_only` to the tool.**

In `gencc_link/mcp/tools/assertions.py`, add the parameter to `find_curations` (after `response_mode`):

```python
    async def find_curations(
        gene: str | None = None,
        disease: str | None = None,
        classification: list[str] | None = None,
        submitter: list[str] | None = None,
        moi: str | None = None,
        has_conflict: bool | None = None,
        response_mode: _MODE = "compact",
        ids_only: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
```

And pass it through in the service call:

```python
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
            )
```

Extend the tool description's final sentence:

```python
            "with the accepted set (see get_server_capabilities / list_submitters). "
            "Pass ids_only=true to return only {gene_curie, disease_curie} pairs for "
            "cheap paging."
```

- [ ] **Step 5: Document under `parameter_conventions` in `capabilities.py`.**

```python
            "ids_only": "find_curations only: return just {gene_curie, disease_curie} "
            "pairs (no per-row detail) for cheap paging",
```

- [ ] **Step 6: Run the find_curations tests.**

Run: `uv run pytest tests/test_service.py tests/test_tools.py -k "find or ids_only" -q`
Expected: PASS.

- [ ] **Step 7: Commit.**

```bash
git add gencc_link/services/gencc_service.py gencc_link/mcp/tools/assertions.py \
        gencc_link/mcp/capabilities.py tests/test_service.py tests/test_tools.py
git commit -m "feat(find_curations): ids_only paging mode

ids_only=true returns just {gene_curie, disease_curie} pairs so an LLM can page
a large match set cheaply, then fetch detail only for the pairs it wants.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## Task 7: Docs, MCP instructions, CHANGELOG

Update the human/agent-facing surfaces to match the new tools (mcp-tool-change skill: README + connection-guide tables; plus the server instructions string and CHANGELOG).

**Files:**
- Modify: `gencc_link/mcp/facade.py` (server instructions string — read it first)
- Modify: `README.md` (tool table, ~135-145)
- Modify: `docs/MCP_CONNECTION_GUIDE.md` (tool table, ~132-141)
- Modify: `docs/usage.md` (if it enumerates tools)
- Modify: `CHANGELOG.md` (`[Unreleased] / Added`)

- [ ] **Step 1: Read the facade instructions string and the doc tables to match wording.**

Run: `sed -n '1,40p' gencc_link/mcp/facade.py; sed -n '130,150p' README.md; sed -n '128,145p' docs/MCP_CONNECTION_GUIDE.md`

- [ ] **Step 2: Add the batch tools to the server instructions string in `facade.py`.**

In the instructions/canonical-workflow text, after the sentence describing `get_gene_curations` / `get_disease_curations`, add:

```
Use get_genes_curations / get_diseases_curations to resolve many genes or diseases in one call (max 20; unresolvable inputs come back in `unresolved`).
```

- [ ] **Step 3: Add rows to the README tool table** (under `get_disease_curations`):

```markdown
| `get_genes_curations` | Batch get_gene_curations: many genes (max 20) in one call |
| `get_diseases_curations` | Batch get_disease_curations: many diseases (max 20) in one call |
```

- [ ] **Step 4: Add the same rows to `docs/MCP_CONNECTION_GUIDE.md`** (under `get_disease_curations`):

```markdown
| `get_genes_curations` | Batch get_gene_curations: many genes (max 20) in one call |
| `get_diseases_curations` | Batch get_disease_curations: many diseases (max 20) in one call |
```

- [ ] **Step 5: If `docs/usage.md` lists the tools, add the two batch tools there too** (grep first: `grep -n get_gene_curations docs/usage.md`). Mirror the table/list style already present.

- [ ] **Step 6: Add a CHANGELOG entry** under `## [Unreleased] / ### Added` (top of the list):

```markdown
- **Batch curation tools** `get_genes_curations(genes=[...])` /
  `get_diseases_curations(diseases=[...])` collapse multi-entity questions into a
  single call (max 20; partial-failure `unresolved` list; per-entity limit).
- **find_curations latency**: targeted primary-key lookup replaces a
  `gene_disease` full scan (the flagged ~59 ms outlier drops to <3 ms);
  `idx_sub_submitter_title` + `idx_sub_moi_nocase` bring submitter/moi filters
  onto an index.
- **find_curations `ids_only`** mode returns just `{gene_curie, disease_curie}`
  pairs for cheap paging.
- **get_gencc_diagnostics** echoes `capabilities_version` + `server_version` as a
  near-zero-token drift probe.
```

- [ ] **Step 7: Commit.**

```bash
git add gencc_link/mcp/facade.py README.md docs/MCP_CONNECTION_GUIDE.md docs/usage.md CHANGELOG.md
git commit -m "docs: batch tools, latency, ids_only, version probe (tables + CHANGELOG)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## Task 8: Full verification (`make ci-local`) and evidence capture

**Files:** none (verification only); fix any failures in their owning module.

- [ ] **Step 1: Run the full local CI gate.**

Run: `make ci-local`
Expected: format clean, ruff clean, mypy strict clean, `make lint-loc` clean (all modules ≤600 lines), all tests pass, coverage ≥85%.

- [ ] **Step 2: If `make lint-loc` flags `repository.py` (was 580) or `gencc_service.py` over 600, split the smallest cohesive unit** (e.g. move the batch methods to a `gencc_link/services/batch.py` helper imported by the service, or the dedupe helper). Re-run `make ci-local`. Record what moved.

- [ ] **Step 3: Re-confirm the end-to-end batch + latency behaviour through a live client** (sanity beyond unit tests):

```bash
uv run python - <<'PY'
import asyncio
from fastmcp import Client
from gencc_link.mcp.facade import create_gencc_mcp

async def main():
    async with Client(create_gencc_mcp()) as c:
        r = await c.call_tool("get_genes_curations", {"genes": ["BRCA2", "NAA10"]})
        d = r.structured_content
        print("batch count:", d["count"], "requested:", d["requested"])
        print("next:", d["_meta"]["next_commands"][:1])
        r2 = await c.call_tool("get_gencc_diagnostics", {})
        print("caps_version:", r2.structured_content["capabilities_version"])
asyncio.run(main())
PY
```

Expected: `batch count: 2 requested: 2`, a non-empty next_command, and a 16-hex `caps_version`. (Requires the live `data/gencc.sqlite`; if absent run `make data` first — note the 20/day quota.)

- [ ] **Step 4: Commit any fixes from Steps 2-3 with a clear message, then stop for review.**

---

## Self-review notes (author)

- **Spec coverage:** B1 → Tasks 3-4; P1 → Task 1; P2 → Task 2; V1 → Task 5; T1 → Task 6; cross-cutting (capabilities/docs/CHANGELOG) → Tasks 4-7; verification → Task 8. All five spec items + cross-cutting covered.
- **Type consistency:** service methods `get_genes_curations`/`get_diseases_curations` and next_commands `after_genes_curations`/`after_diseases_curations` are named identically wherever referenced; `ids_only` keyword matches across tool→service; `_BATCH_MAX = 20` and the "max 20" prose agree.
- **No brittle plan-plan assertions:** query-plan/perf verification is manual against the real 14k-row DB (Task 1 Step 5, Task 2 Step 5); CI tests assert correctness and index existence only (reliable on the 5-row fixture).
- **Atomicity:** Task 1 (the highest-value fix) is independently committable and does not depend on any later task.
```
