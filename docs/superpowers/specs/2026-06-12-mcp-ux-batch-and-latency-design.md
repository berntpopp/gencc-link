# GenCC-Link — Batch Tools, Latency & Version Probe — Design Spec

**Date:** 2026-06-12
**Status:** Approved for implementation (autonomous build)
**Author:** Claude (MCP engineer)
**Input:** `MCP-UX-ASSESSMENT.md` (LLM-consumer assessment, overall 9/10)

## 1. Purpose

The assessment rates GenCC-Link 9/10 — already best-in-class on discoverability,
observability, and error recovery — and names four concrete, self-contained
improvements. This spec turns those four into one coherent change set that
targets a >9.5/10 LLM-consumer experience, plus one **root-cause correction**:
the assessment misdiagnosed the `find_curations` latency, and the fix it proposed
would not have worked.

## 2. Goals / Non-goals

**Goals** — close every gap the assessment raised:

| ID | Assessment item | Change |
|----|-----------------|--------|
| B1 | "Add a batch tool — biggest LLM-UX win." Multi-entity questions force N round trips. | Add `get_genes_curations(genes=[...])` and `get_diseases_curations(diseases=[...])` with partial-failure semantics, mirroring sibling `genereviews-link.get_passages_batch`. |
| P1 | "Profile `find_curations` — the one speed outlier" (59 ms). | **Rewrite** `_gene_disease_rows_for_pairs` from a full `gene_disease` scan to a targeted primary-key lookup. 34 ms → 0.07 ms. No schema change. |
| P2 | (completes P1) submitter-only / moi-only filters also full-scan (4–6 ms; not separately flagged). | Add `idx_sub_submitter_title` and `idx_sub_moi_nocase`; brings every `find_curations` path sub-millisecond. |
| V1 | "Expose a lightweight version probe." Checking `capabilities_version` requires the ~4 kB capabilities doc. | Echo `capabilities_version` + `server_version` into the small `get_gencc_diagnostics` payload (assessment's option A). |
| T1 | "No field-projection / `ids_only` mode for `find_curations` paging." | Add `ids_only: bool` to `find_curations`: returns just `{gene_curie, disease_curie}` pairs + counts. |

**Non-goals (YAGNI):**

- No `ids_only` on `get_gene_curations` / `get_disease_curations` (assessment named
  only `find_curations`).
- No removal of `headline` (the assessment marked this low-priority; `headline` is
  a deliberate UX feature, not bloat).
- No `capabilities_version` in every envelope `_meta` (would tax every response and
  work against the token-efficiency score; diagnostics echo is the opt-in probe).
- No new error code for oversized batches (reuse `invalid_input`, which already
  carries recovery `next_commands`).
- No change to consensus/conflict logic, FTS/search ranking, or download cadence.
- No combined gene+disease batch tool (rare case; two pluralized tools match the
  existing `get_gene_curations` / `get_disease_curations` symmetry).

## 3. Root-cause correction (the load-bearing analysis)

The assessment hypothesized the 59 ms came from "a full scan or Python-side filter
over the 29,846 submission rows" and recommended "a composite index on the
submission-level filter columns." Measured against the live 2026-06-07 database
(29,846 submissions; 14,131 `gene_disease` pairs):

| Stage | What runs | Plan | Time |
|-------|-----------|------|------|
| A: `_matched_from_submissions` (`classification=['Definitive'], submitter=['ClinGen'], moi='Autosomal dominant'`) | `SELECT … FROM submissions WHERE …` | `SEARCH submissions USING INDEX idx_sub_classification` | ~2.1 ms |
| **B: `_gene_disease_rows_for_pairs`** | `SELECT * FROM gene_disease ORDER BY consensus_rank DESC, gene_symbol, disease_title` | `SCAN gene_disease … USE TEMP B-TREE FOR … ORDER BY` | **~34 ms** |
| B′: proposed fix | `… WHERE (gene_curie, disease_curie) IN (VALUES …) ORDER BY …` | `SEARCH gene_disease USING INDEX sqlite_autoindex_gene_disease_1` | **~0.07 ms** |

**The submission filter is already fast (Stage A, index-assisted).** The 34 ms is
Stage B: a full table scan of every aggregated row — including the large JSON
columns (`submitters_json`, etc.) — plus a temp-B-tree sort, with Python then
discarding all but the matched pairs. The assessment's composite index would
optimize the 2 ms stage and leave the 34 ms scan untouched. **The fix is a query
rewrite, not an index.** SQLite's `SQLITE_LIMIT_VARIABLE_NUMBER` here is 250,000,
so a single `IN (VALUES …)` covers even the worst case (~14k pairs → 28k params).

P2 (the schema indexes) is a *separate, smaller* completion: submitter-only and
moi-only filters still `SCAN submissions` (4–6 ms) because `idx_sub_submitter` is
on `submitter_curie` (not `submitter_title`) and `idx_sub_moi` (BINARY) cannot
serve the `COLLATE NOCASE` comparison. Two targeted indexes close that gap.

## 4. Detailed design

### 4.1 Batch curation tools (B1)

Two new tools, registered in the existing `genes.py` / `diseases.py` modules.

**`get_genes_curations`**

```
get_genes_curations(
    genes: list[str],                 # 1..20 symbols or HGNC ids
    response_mode: minimal|compact|standard|full = "compact",
    limit_per_gene: int = 50,         # clamped to _MAX_LIMIT (200)
) -> dict
```

Behaviour:

- Dedupe inputs preserving first-seen order.
- Resolve each gene; for each resolved gene, build the same per-gene block as
  `get_gene_curations` (gene summary + diseases page up to `limit_per_gene` + a
  per-gene `truncated` block when the gene has more).
- Unresolved inputs collect into `unresolved: [{input, reason: "not_found"}]`.
- The **call succeeds even with partial or total misses** — per-item failures are
  data, not errors, so the model keeps the resolved results and a `next_commands`
  recovery for the misses. Mirrors `genereviews-link` (HTTP 200 + `missing_ids`).
- **Input validation** (returns `invalid_input` envelope): empty list; list longer
  than 20 (`field="genes"`, message names the cap of 20).

Response:

```json
{
  "headline": "Curations for 2 of 2 requested genes (0 unresolved).",
  "requested": 2,
  "count": 2,
  "results": [ { "gene": {...}, "headline": "...", "count": 8, "total": 8, "diseases": [ ... ] } ],
  "unresolved": [ { "input": "BRCA9999", "reason": "not_found" } ],   // omitted when empty
  "_meta": { ...envelope..., "next_commands": [ ... ] }
}
```

`next_commands`:
- If any unresolved → `search_genes(query=first_unresolved_input)`.
- Else if results → `get_gene_disease_assertion(gene=first_gene_curie, disease=top_disease_curie)`.

**`get_diseases_curations`** — symmetric: `diseases: list[str]`, `limit_per_disease`,
per-disease blocks shaped like `get_disease_curations`, `unresolved` reason
`not_found`, `next_commands` to `search_diseases` / `get_gene_disease_assertion`.

Service layer adds `get_genes_curations` / `get_diseases_curations` on
`GenCCService`, reusing the existing single-entity logic per item (no new
repository method).

### 4.2 `find_curations` latency fix (P1)

Rewrite `GenCCRepository._gene_disease_rows_for_pairs(pairs, *, has_conflict)`:

```python
def _gene_disease_rows_for_pairs(self, pairs, *, has_conflict):
    if not pairs:
        return []
    values = ",".join("(?,?)" for _ in pairs)
    params: list[object] = [x for pair in pairs for x in pair]
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

- `has_conflict` moves into the SQL `WHERE` (was a Python post-filter), so
  `find_assertions` no longer needs the `kept`/`matched`-pruning step — the matched
  map is filtered to the returned pairs directly. Ordering stays identical
  (`ORDER BY` preserved), so existing ordering tests hold.
- Behaviour is unchanged; only the access path differs. Verified by reusing the
  existing repository tests plus a new test asserting the targeted plan.

### 4.3 Schema index completion (P2)

Add to `schema.sql` (after the existing `submissions` indexes):

```sql
CREATE INDEX idx_sub_submitter_title ON submissions(submitter_title);
CREATE INDEX idx_sub_moi_nocase ON submissions(moi_title COLLATE NOCASE);
```

- **No `schema_version` bump.** Indexes do not change query *results*, only the
  access path, so existing databases remain correct; forcing a rebuild would spend
  download quota for nothing.
- Test databases rebuild from `schema.sql` every session (conftest →
  `build_database`), so the indexes are exercised automatically.
- The live `data/gencc.sqlite` is migrated in place with
  `CREATE INDEX IF NOT EXISTS …` (no network, quota-safe); any future rebuild from
  `schema.sql` includes them.
- **Measurement gate:** after adding the indexes, re-check `EXPLAIN QUERY PLAN`.
  If the `submitter_title IN (…) OR submitter_curie IN (…)` predicate still scans
  (SQLite may not OR-union the two), the submitter branch is left as-is — the P1
  fix already removes the dominant cost and 4–6 ms is acceptable; the moi index is
  kept regardless since `moi_title COLLATE NOCASE` provably uses `idx_sub_moi_nocase`.

This is committed separately from P1 so the core latency win lands independently.

### 4.4 Version probe (V1)

Add to the `get_gencc_diagnostics` payload (top level, before `data`):

```python
"server_version": _server_version(),
"capabilities_version": capabilities_version(),
```

The payload already carries data freshness (`gencc_run_date`,
`source_last_modified` inside `data`), so diagnostics becomes the cheap
freshness-and-drift probe: a warm client polls it, compares
`capabilities_version`, and re-fetches the 4 kB capabilities doc only on change.
Documented in capabilities `response_fields` and the connection guide.

### 4.5 `ids_only` paging (T1)

Add `ids_only: bool = False` to `find_curations` (tool + service):

- When `True`, each result row is exactly `{"gene_curie": …, "disease_curie": …}`
  — no shaping, no `matched`, no per-row classification lists.
- `count` / `total` / `filters` / `truncated` are unchanged, so paging metadata
  still works.
- Filter validation still runs (invalid filters still error).
- `_meta.next_commands` still drills into the first pair.

Lets an LLM page through a large match set cheaply, then fetch detail only for the
pairs it wants — the server-side-projection pattern from the token-efficiency
guidance.

## 5. Cross-cutting updates

- `capabilities.py` `TOOLS`: add `get_genes_curations`, `get_diseases_curations`
  (10 → 12). `capabilities_version` hash changes by design.
- `capabilities.py`: add `token_cost_hints` for both batch tools; add a batch
  entry to `recommended_workflows`; document `ids_only` under `response_fields` /
  `parameter_conventions`; note `capabilities_version` echo in diagnostics.
- `next_commands.py`: add `after_genes_curations` / `after_diseases_curations`
  helpers.
- Tests: `tests/test_tools.py` `EXPECTED_TOOLS` (+2) and `len(tools) == 12`;
  `tests/test_capabilities.py` `len == 12`. New tool tests for batch, version
  probe, `ids_only`; new repository test for the targeted-pair plan; new service
  tests for batch partial-failure and `ids_only`.
- Docs: tool tables in `README.md` and `docs/MCP_CONNECTION_GUIDE.md`; the MCP
  instructions string in `facade.py` (mention batch tools); `docs/usage.md` if it
  enumerates tools.
- `CHANGELOG.md` `[Unreleased] / Added`.

## 6. Testing plan

- **P1:** new repository test asserts the matched-pair fetch returns the same rows
  & order as before and that `EXPLAIN QUERY PLAN` uses the PK autoindex (not a full
  scan). Existing `find_assertions` / `find_curations` tests must stay green.
- **B1:** service tests — two-gene success, dedupe, unresolved partial, all-missing
  (success=True, count=0), over-cap → `invalid_input`, `limit_per_gene` clamp.
  Tool tests — `get_genes_curations(["BRCA2","NAA10"])`-style multi-entity success,
  `_meta.next_commands` present, citation_ref in compact.
- **V1:** tool test — diagnostics carries `capabilities_version` (16-hex) and
  `server_version`.
- **T1:** service + tool test — `ids_only` rows have exactly two keys; `total`
  matches the non-`ids_only` call.
- `make ci-local` green (format, ruff, mypy strict, lint-loc ≤600, tests, coverage
  ≥85%).

## 7. Risks & mitigations

| Risk | Mitigation |
|------|-----------|
| `repository.py` is 580/600 lines; P1 must not push it over. | The rewrite is net-neutral/shorter (removes the Python filter loop). `make lint-loc` gates it; split helper if needed. |
| Adding two tools worsens the deferred-tool cold start the assessment noted. | Net win: batch tools *remove* round trips. Tool count 12 is well within sibling norms (gnomAD ~20). |
| Live-DB index migration vs. quota. | `CREATE INDEX` runs on existing data — no download. |
| `capabilities_version` change breaks a pinned-hash test. | No test pins the value (only `len==16` + hex); both tool-count asserts are updated. |
| Batch payloads could be large. | `response_mode` + `limit_per_gene` (clamped) + 20-item cap bound the size; default compact. |

## 8. Out of scope

Schema row-shape changes; consensus/conflict/ranking changes; code-execution/
programmatic-tool-calling mode; `ids_only` on single-entity tools; per-call
`capabilities_version` in `_meta`.
