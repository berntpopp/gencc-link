# MCP Consumer-Uplift v0.4.0 Implementation Plan

> Historical record — this document records the design or plan as of its date. Current behavior is
> defined by implemented code, standards, release evidence, and tests.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Lift the GenCC-Link MCP from 9/10 to >9.5/10 by removing full-mode and per-call token redundancy, finishing refresh-safe paging across all paged tools, fixing three correctness/observability nits, and completing the capabilities documentation.

**Architecture:** Pure read-path/contract changes over the existing service → shaping → envelope → capabilities pipeline. No schema, ingest, or repository changes. The release-stamped opaque cursor already used by `find_curations` is generalized via a shared decoder in `services/cursor.py`; full-mode arrays are de-duplicated in `services/shaping.py`; per-call `_meta` policy is centralized in `mcp/envelope.py`.

**Tech Stack:** Python 3.12, FastMCP, Pydantic v2, SQLite/FTS5, pytest (+respx for downloads), Ruff, mypy strict. `make ci-local` is the gate (format, lint, lint-loc ≤600, typecheck, tests ≥85%).

---

## File structure / responsibilities

| File | Responsibility after this plan |
|------|------|
| `services/shaping.py` | `assertion_dict` no longer emits the full-mode union `pmids`; `submission_dict` returns only raw-extras (de-duplicated vs `submitters[]`). |
| `services/cursor.py` | Adds `decode_paged_cursor(token, *, current_release)` — the single decode+stale-reject helper for all paged tools. |
| `services/gencc_service.py` | `search_genes`/`search_diseases`/`get_gene_curations`/`get_disease_curations` accept `cursor` + mint `next_cursor`; `find_curations` reuses the shared decoder; resolve kind-scoped message + dual-arg guard; batch `received`/`duplicates`. |
| `mcp/envelope.py` | Error `_meta` → `citation_ref` only; `data_license` emitted only in `full`; `unsafe_for_clinical_use` always; `gencc_release` on success. |
| `mcp/tools/genes.py`, `mcp/tools/diseases.py` | `cursor` param + page-forward `next_commands` on the 4 paged tools; batch headline mentions folding. |
| `mcp/tools/assertions.py` | `resolve_identifier` dual-arg guard; full-mode `submissions[]` description. |
| `mcp/capabilities.py` | `tool_defaults`, annotated `error_codes` + `error_codes_list`, `conflict_semantics`, `ambiguous_query_example`, paging/full-mode notes, new `response_fields`. |
| `mcp/resources.py` | `gencc://usage` + `gencc://reference` text updates. |
| `mcp/schemas.py` | `received`/`duplicates`/`cursor` surfaced; `_META` already permissive. |
| `CHANGELOG.md`, `pyproject.toml` | 0.3.0 → 0.4.0 (+ `uv.lock` refresh). |
| `docs/mcp-consumer-assessment-v0.3.0.md` | Append "Resolution (v0.4.0)". |

Run `make lint-loc` after WS3 — `gencc_service.py` is at 516/600.

---

## WS1 — Full-mode de-duplication (Token)

### Task 1: Drop the full-mode union `pmids` from aggregated assertions

**Files:**
- Modify: `gencc_link/services/shaping.py` (`assertion_dict`, ~line 162-165)
- Test: `tests/test_shaping.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_shaping.py — add inside the existing assertion-shaping test area
def test_assertion_full_mode_has_no_union_pmids(sample_assertion) -> None:
    out = shaping.assertion_dict(sample_assertion, "full")
    assert "submitters" in out
    assert "pmids" not in out  # union removed; per-submitter pmids remain
    assert any("pmids" in s for s in out["submitters"])
```

If no `sample_assertion` fixture exists, build one from the repository in the test module the way other `test_shaping.py` tests do (resolve via the `service`/`repository` fixture: `repository.get_gene_disease("HGNC:10896", "MONDO:0008426")`). Match the existing file's construction style.

- [ ] **Step 2: Run — expect FAIL** (`pytest tests/test_shaping.py -k union_pmids -v`) — KeyError/`pmids` present.

- [ ] **Step 3: Implement** — in `assertion_dict`, delete:

```python
    # standard + full: per-submitter breakdown
    out["submitters"] = [_submitter_dict(s, mode) for s in a.submitters]
    if mode == "full":
        out["pmids"] = a.pmids
    return out
```

becomes:

```python
    # standard + full: per-submitter breakdown (each submitter carries its own
    # pmids in full; the pair-level union is dropped as pure redundancy).
    out["submitters"] = [_submitter_dict(s, mode) for s in a.submitters]
    return out
```

- [ ] **Step 4: Run — expect PASS.**

- [ ] **Step 5: Commit** — `git commit -am "perf(tokens): drop full-mode union pmids from aggregated assertions"`

### Task 2: Slim `submission_dict` to raw-extras only

**Files:**
- Modify: `gencc_link/services/shaping.py` (`submission_dict`, ~line 208-225)
- Test: `tests/test_shaping.py`, `tests/test_service.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_shaping.py
def test_submission_dict_is_raw_extras_only(sample_submission) -> None:
    out = shaping.submission_dict(sample_submission)
    # raw-extras kept
    for k in ("sgc_id", "submitter_title", "classification_title", "moi_title",
              "notes", "disease_original_curie", "disease_original_title",
              "version_number", "submitted_run_date", "pmids"):
        assert k in out
    # de-duplicated (now sourced from submitters[] / parent)
    for k in ("disease_curie", "disease_title", "public_report_url",
              "assertion_criteria_url", "submitted_as_date", "submitted_as_date_iso"):
        assert k not in out
```

Build `sample_submission` from `repository.get_submissions("HGNC:10896", "MONDO:0008426")[0]` in the test, matching the module's style.

- [ ] **Step 2: Run — expect FAIL.**

- [ ] **Step 3: Implement** — replace `submission_dict` body:

```python
def submission_dict(s: SubmissionRecord) -> dict[str, Any]:
    """Shape a raw submission row as *raw-extras only* (full-detail view).

    In full mode the harmonized per-submitter fields (classification, MOI,
    dates, report/criteria URLs, pmids) live in ``submitters[]``; this row
    carries only the fields not represented there — raw IDs, version, notes,
    the unharmonized original disease, and the per-row classification/MOI/pmids
    that let a reader see divergent submissions from one submitter. The
    pair-constant disease identity comes from the parent assertion. Correlate a
    row back to a submitter via ``submitter_title``.
    """
    return {
        "sgc_id": s.sgc_id,
        "submitter_title": s.submitter_title,
        "classification_title": s.classification_title,
        "moi_title": s.moi_title,
        "disease_original_curie": s.disease_original_curie,
        "disease_original_title": s.disease_original_title,
        "version_number": s.version_number,
        "submitted_run_date": s.submitted_run_date,
        "pmids": s.pmids,
        "notes": s.notes,
    }
```

- [ ] **Step 4: Update any existing test** asserting the dropped keys on `submissions[]` (search `tests/` for `submission` + `disease_curie`/`public_report_url`; e.g. `tests/test_shaping.py`, `tests/test_service.py`, `tests/test_tools.py`). Adjust to the new shape.

Run: `grep -rn "submission" tests/ | grep -iE "disease_curie|public_report_url|assertion_criteria_url|submitted_as_date"`

- [ ] **Step 5: Run — expect PASS** (`pytest tests/test_shaping.py tests/test_service.py -v`).

- [ ] **Step 6: Commit** — `git commit -am "perf(tokens): slim full-mode submissions[] to raw-extras (de-dup vs submitters[])"`

### Task 3: Assert full-mode assertion payload actually shrank (guardrail)

**Files:** Test: `tests/test_tools.py`

- [ ] **Step 1: Write test** (end-to-end via `mcp_client`):

```python
async def test_assertion_full_mode_no_duplicate_pmids_or_dup_fields(self, mcp_client) -> None:
    r = await mcp_client.call_tool(
        "get_gene_disease_assertion",
        {"gene": "SKI", "disease": "MONDO:0008426", "response_mode": "full"},
    )
    d = r.structured_content
    assert "pmids" not in d["assertion"]              # no union
    assert d["submissions"]                            # raw rows still present
    row = d["submissions"][0]
    assert "notes" in row and "sgc_id" in row          # raw-extras preserved
    assert "disease_curie" not in row                  # de-duplicated
    assert "public_report_url" not in row
    # per-submitter pmids still available somewhere in full
    assert any(s.get("pmids") for s in d["assertion"]["submitters"])
```

- [ ] **Step 2: Run — expect PASS** (behavior already implemented in Tasks 1–2).

- [ ] **Step 3: Commit** — `git commit -am "test(tokens): guard full-mode assertion de-duplication end-to-end"`

---

## WS2 — Citation & static-field trimming (Token)

### Task 4: Error envelopes carry `citation_ref` only

**Files:**
- Modify: `gencc_link/mcp/envelope.py` (`_provenance_meta`, `_error_envelope`)
- Test: `tests/test_envelope.py`, `tests/test_tools.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_tools.py
async def test_error_envelope_uses_citation_ref_not_full(self, mcp_client) -> None:
    r = await mcp_client.call_tool("search_genes", {"query": ""})  # invalid_input
    meta = r.structured_content["_meta"]
    assert meta["citation_ref"] == "gencc://citation"
    assert "recommended_citation" not in meta
    assert "citation_short" not in meta          # an error carries no claim to cite
    assert meta["unsafe_for_clinical_use"] is True
```

- [ ] **Step 2: Run — expect FAIL** (error currently emits `recommended_citation`).

- [ ] **Step 3: Implement** — add an error-specific provenance branch. In `envelope.py`, refactor `_provenance_meta` to accept an `is_error` flag (default False) OR add a dedicated `_error_provenance_meta`. Minimal version — add a parameter:

```python
def _provenance_meta(response_mode: str | None = None, *, is_error: bool = False) -> dict[str, Any]:
    """Provenance block for ``_meta``; mode-aware citation to cut per-call tokens.

    Errors carry only ``citation_ref`` (no claim to cite). ``data_license`` is
    session-invariant (also in capabilities + citation_short) so it is emitted
    only in ``full``; ``unsafe_for_clinical_use`` rides every envelope.
    """
    meta: dict[str, Any] = {"unsafe_for_clinical_use": True}
    if is_error:
        meta["citation_ref"] = _CITATION_REF
    elif response_mode == "full":
        meta["data_license"] = DATA_LICENSE
        meta["recommended_citation"] = RECOMMENDED_CITATION
    elif response_mode in ("minimal", "compact", "standard"):
        meta["citation_ref"] = _CITATION_REF
        meta["citation_short"] = CITATION_SHORT
    else:  # unset success default (rare): keep a safe verbatim citation
        meta["recommended_citation"] = RECOMMENDED_CITATION
    if response_mode:
        meta["response_mode"] = response_mode
    if _DATA_RELEASE:
        meta["gencc_release"] = _DATA_RELEASE
    return meta
```

Then in `_error_envelope`, change `**_provenance_meta()` → `**_provenance_meta(is_error=True)`.

- [ ] **Step 4: Run — expect PASS.** Also run `tests/test_envelope.py` — fix any assertion expecting `recommended_citation` on errors.

- [ ] **Step 5: Commit** — `git commit -am "perf(tokens): error envelopes carry citation_ref only, not the verbatim citation"`

### Task 5: `data_license` only in full; success modes trimmed

**Files:** Test: `tests/test_tools.py` (implementation already in Task 4)

- [ ] **Step 1: Write tests**

```python
async def test_data_license_only_in_full(self, mcp_client) -> None:
    compact = await mcp_client.call_tool("get_gene_curations", {"gene": "SKI", "response_mode": "compact"})
    assert "data_license" not in compact.structured_content["_meta"]
    full = await mcp_client.call_tool("get_gene_curations", {"gene": "SKI", "response_mode": "full"})
    assert full.structured_content["_meta"]["data_license"] == "CC0-1.0"

async def test_unsafe_flag_on_every_envelope(self, mcp_client) -> None:
    for mode in ("minimal", "compact", "standard", "full"):
        r = await mcp_client.call_tool("get_gene_curations", {"gene": "SKI", "response_mode": mode})
        assert r.structured_content["_meta"]["unsafe_for_clinical_use"] is True
```

- [ ] **Step 2: Run — expect PASS** (Task 4 implemented the policy).

- [ ] **Step 3: Fix any existing `_meta` test** asserting `data_license` in non-full modes (`grep -rn "data_license" tests/`). Update them to the new policy.

- [ ] **Step 4: Commit** — `git commit -am "test(tokens): pin data_license-in-full and always-on safety flag"`

---

## WS3 — Uniform refresh-safe paging (Ergonomics)

### Task 6: Shared `decode_paged_cursor` helper

**Files:**
- Modify: `gencc_link/services/cursor.py`
- Test: `tests/test_cursor.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_cursor.py
import pytest
from gencc_link.services.cursor import encode_cursor, decode_paged_cursor

def test_decode_paged_cursor_round_trip() -> None:
    tok = encode_cursor(release="2026-06-07", offset=4, limit=2, filters={"query": "col"})
    st = decode_paged_cursor(tok, current_release="2026-06-07")
    assert st["o"] == 4 and st["lim"] == 2 and st["flt"]["query"] == "col"

def test_decode_paged_cursor_rejects_stale_release() -> None:
    tok = encode_cursor(release="2026-05-01", offset=0, limit=2, filters={})
    with pytest.raises(ValueError) as exc:
        decode_paged_cursor(tok, current_release="2026-06-07")
    assert "2026-05-01" in str(exc.value) and "2026-06-07" in str(exc.value)

def test_decode_paged_cursor_rejects_malformed() -> None:
    with pytest.raises(ValueError):
        decode_paged_cursor("!!!notbase64!!!", current_release="2026-06-07")
```

- [ ] **Step 2: Run — expect FAIL** (function missing).

- [ ] **Step 3: Implement** — append to `cursor.py`:

```python
def decode_paged_cursor(token: str, *, current_release: str | None) -> dict[str, Any]:
    """Decode a page cursor and reject one minted against a stale data release.

    Returns the decoded payload (``{"v","r","o","lim","flt"}``). Raises
    ``ValueError`` on malformation/version mismatch (via :func:`decode_cursor`)
    or when the cursor's release no longer matches ``current_release`` — the
    refresh-safe guarantee shared by every paged tool.
    """
    payload = decode_cursor(token)
    if payload["r"] != current_release:
        raise ValueError(
            f"Cursor was minted against GenCC release {payload['r']!r} but the "
            f"current release is {current_release!r}; restart the sweep."
        )
    return payload
```

- [ ] **Step 4: Run — expect PASS.**

- [ ] **Step 5: Commit** — `git commit -am "feat(paging): shared decode_paged_cursor with release-stale rejection"`

### Task 7: `find_curations` reuses the shared decoder (refactor, no behavior change)

**Files:**
- Modify: `gencc_link/services/gencc_service.py` (`find_curations`, ~line 376-398)
- Test: existing `tests/test_tools.py::...cursor...`, `tests/test_service.py::TestFindCurationsCursor`

- [ ] **Step 1: Refactor** — replace the inline decode/stale block:

```python
        if cursor is not None:
            try:
                cur = decode_paged_cursor(cursor, current_release=self.get_meta().gencc_run_date)
            except ValueError as exc:
                raise InvalidInputError(str(exc), field="cursor") from exc
            flt = cur["flt"]
            gene = flt.get("gene")
            disease = flt.get("disease")
            classification = flt.get("classification")
            submitter = flt.get("submitter")
            moi = flt.get("moi")
            has_conflict = flt.get("has_conflict")
            response_mode = flt.get("response_mode", response_mode)
            ids_only = flt.get("ids_only", ids_only)
            offset = cur["o"]
            limit = cur["lim"]
```

Update the import: `from gencc_link.services.cursor import decode_paged_cursor` (drop `decode_cursor` if now unused).

- [ ] **Step 2: Run existing cursor tests — expect PASS** (`pytest tests/ -k cursor -v`). Behavior is identical; the stale message is unchanged.

- [ ] **Step 3: Run `make lint-loc`** — confirm `gencc_service.py` shrank (inline block removed).

- [ ] **Step 4: Commit** — `git commit -am "refactor(paging): find_curations uses shared decode_paged_cursor"`

### Task 8: `cursor` param on `search_genes` + `get_gene_curations` (service)

**Files:**
- Modify: `gencc_link/services/gencc_service.py` (`search_genes`, `get_gene_curations`)
- Test: `tests/test_service.py`

For each method: add `cursor: str | None = None`; when present, decode via `decode_paged_cursor`, restore filters + offset + limit; pass `cursor_context` to `truncation_block`.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_service.py
class TestSearchPagingCursor:
    def test_search_genes_mints_and_follows_cursor(self, service) -> None:
        first = service.search_genes("col", limit=1)  # COL1A1, COL2A1 -> 2 hits
        assert "truncated" in first and "next_cursor" in first["truncated"]
        tok = first["truncated"]["next_cursor"]
        second = service.search_genes("ignored", cursor=tok)
        ids1 = {g["gene_curie"] for g in first["genes"]}
        ids2 = {g["gene_curie"] for g in second["genes"]}
        assert ids1 and ids2 and ids1.isdisjoint(ids2)

    def test_search_genes_stale_cursor_rejected(self, service) -> None:
        from gencc_link.services.cursor import encode_cursor
        tok = encode_cursor(release="1999-01-01", offset=1, limit=1, filters={"query": "col"})
        with pytest.raises(InvalidInputError):
            service.search_genes("col", cursor=tok)

    def test_gene_curations_mints_and_follows_cursor(self, service) -> None:
        first = service.get_gene_curations("COL1A1", limit=1)
        if "truncated" not in first:
            return  # COL1A1 may have 1 disease in fixture; skip when no 2nd page
        tok = first["truncated"]["next_cursor"]
        second = service.get_gene_curations("COL1A1", cursor=tok)
        assert second["count"] >= 0
```

(Note: COL1A1 has 3 diseases in the fixture, so it pages.)

- [ ] **Step 2: Run — expect FAIL** (`cursor` kwarg unknown / no `next_cursor`).

- [ ] **Step 3: Implement** `search_genes`:

```python
    def search_genes(
        self,
        query: str,
        *,
        response_mode: str = "compact",
        limit: int = 20,
        offset: int = 0,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        if cursor is not None:
            query, response_mode, limit, offset = self._restore_search_cursor(
                cursor, query, response_mode
            )
        mode = self._validate_mode(response_mode)
        if not query or not query.strip():
            raise InvalidInputError("query must not be empty.", field="query")
        limit = self._clamp_limit(limit)
        offset = self._validate_offset(offset)
        key = f"sg:{query.strip().lower()}:{mode}:{limit}:{offset}"
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        hits, total = self._repo.search_genes(query.strip(), limit=limit, offset=offset)
        payload: dict[str, Any] = {
            "query": query.strip(),
            "count": len(hits),
            "total": total,
            "genes": [shaping.gene_summary_dict(g, mode) for g in hits],
        }
        if hits:
            payload["headline"] = shaping.genes_search_headline(query.strip(), hits, total)
        trunc = shaping.truncation_block(
            total, limit, offset,
            cursor_context={
                "release": self.get_meta().gencc_run_date,
                "filters": {"query": query.strip(), "response_mode": mode},
            },
        )
        if trunc:
            payload["truncated"] = trunc
        self._cache.put(key, payload)
        return payload
```

Add the shared restore helper (one place, reused by all four):

```python
    def _restore_search_cursor(
        self, cursor: str, default_query: str, default_mode: str
    ) -> tuple[str, str, int, int]:
        """Decode a search/curation cursor; return (query, mode, limit, offset)."""
        try:
            cur = decode_paged_cursor(cursor, current_release=self.get_meta().gencc_run_date)
        except ValueError as exc:
            raise InvalidInputError(str(exc), field="cursor") from exc
        flt = cur["flt"]
        return (
            flt.get("query", default_query),
            flt.get("response_mode", default_mode),
            cur["lim"],
            cur["o"],
        )
```

Implement `get_gene_curations` the same way, but the cursor filter carries `gene` (the resolved curie) not `query`:

```python
    def get_gene_curations(
        self, gene: str, *, response_mode: str = "compact",
        limit: int = 50, offset: int = 0, cursor: str | None = None,
    ) -> dict[str, Any]:
        if cursor is not None:
            gene, response_mode, limit, offset = self._restore_id_cursor(
                cursor, "gene", gene, response_mode
            )
        mode = self._validate_mode(response_mode)
        # ... unchanged resolve + page ...
        trunc = shaping.truncation_block(
            total, limit, offset,
            cursor_context={
                "release": self.get_meta().gencc_run_date,
                "filters": {"gene": summary.gene_curie, "response_mode": mode},
            },
        )
```

with a sibling restore helper:

```python
    def _restore_id_cursor(
        self, cursor: str, key: str, default_id: str, default_mode: str
    ) -> tuple[str, str, int, int]:
        try:
            cur = decode_paged_cursor(cursor, current_release=self.get_meta().gencc_run_date)
        except ValueError as exc:
            raise InvalidInputError(str(exc), field="cursor") from exc
        flt = cur["flt"]
        return (flt.get(key, default_id), flt.get("response_mode", default_mode), cur["lim"], cur["o"])
```

(If LOC pressure: fold `_restore_search_cursor` and `_restore_id_cursor` into one `_restore_cursor(cursor, key, default_value, default_mode)` returning `(value, mode, lim, off)`; `search_*` pass `key="query"`.)

- [ ] **Step 4: Run — expect PASS.**

- [ ] **Step 5: Run `make lint-loc`.** If `gencc_service.py` ≥ 590, fold the two restore helpers into one as noted.

- [ ] **Step 6: Commit** — `git commit -am "feat(paging): release-bound cursor on search_genes + get_gene_curations"`

### Task 9: `cursor` param on `search_diseases` + `get_disease_curations` (service)

**Files:**
- Modify: `gencc_link/services/gencc_service.py` (`search_diseases`, `get_disease_curations`)
- Test: `tests/test_service.py`

- [ ] **Step 1: Write failing tests** mirroring Task 8 (use query `"syndrome"` for multi-hit disease search; `MONDO:0008426`/disease titles for curations). Example:

```python
def test_search_diseases_mints_and_follows_cursor(self, service) -> None:
    first = service.search_diseases("syndrome", limit=1)
    assert "truncated" in first and "next_cursor" in first["truncated"]
    tok = first["truncated"]["next_cursor"]
    second = service.search_diseases("ignored", cursor=tok)
    ids1 = {d["disease_curie"] for d in first["diseases"]}
    ids2 = {d["disease_curie"] for d in second["diseases"]}
    assert ids1.isdisjoint(ids2)
```

- [ ] **Step 2: Run — expect FAIL.**

- [ ] **Step 3: Implement** `search_diseases` (cursor filter `{"query","response_mode"}`) and `get_disease_curations` (cursor filter `{"disease": summary.disease_curie, "response_mode"}`), using `_restore_search_cursor` / `_restore_id_cursor(key="disease")`.

- [ ] **Step 4: Run — expect PASS; run `make lint-loc`.**

- [ ] **Step 5: Commit** — `git commit -am "feat(paging): release-bound cursor on search_diseases + get_disease_curations"`

### Task 10: Tools accept `cursor` + emit page-forward `next_commands`

**Files:**
- Modify: `gencc_link/mcp/tools/genes.py` (`search_genes`, `get_gene_curations`), `gencc_link/mcp/tools/diseases.py` (`search_diseases`, `get_disease_curations`)
- Test: `tests/test_tools.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_tools.py
async def test_search_genes_pages_forward_with_cursor(self, mcp_client) -> None:
    first = await mcp_client.call_tool("search_genes", {"query": "col", "limit": 1})
    d1 = first.structured_content
    assert "next_cursor" in d1["truncated"]
    cont = d1["_meta"]["next_commands"][0]
    assert cont["tool"] == "search_genes" and "cursor" in cont["arguments"]
    second = await mcp_client.call_tool("search_genes", cont["arguments"])
    d2 = second.structured_content
    assert {g["gene_curie"] for g in d1["genes"]}.isdisjoint(
        {g["gene_curie"] for g in d2["genes"]}
    )

async def test_get_gene_curations_pages_forward_with_cursor(self, mcp_client) -> None:
    first = await mcp_client.call_tool("get_gene_curations", {"gene": "COL1A1", "limit": 1})
    d1 = first.structured_content
    assert "next_cursor" in d1["truncated"]
    assert d1["_meta"]["next_commands"][0]["tool"] == "get_gene_curations"
```

Add the disease analogues (`search_diseases` query `"syndrome"`, `get_disease_curations` a multi-gene disease).

- [ ] **Step 2: Run — expect FAIL** (cursor not threaded; page-forward not prepended).

- [ ] **Step 3: Implement** — thread `cursor` through each tool signature and prepend the page-forward command. `search_genes` in `genes.py`:

```python
    async def search_genes(
        query: str = "",
        response_mode: _MODE = "compact",
        limit: int = 20,
        offset: int = 0,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            payload = get_gencc_service().search_genes(
                query, response_mode=response_mode, limit=limit, offset=offset, cursor=cursor
            )
            curies = [g["gene_curie"] for g in payload.get("genes", [])]
            nexts: list[dict[str, Any]] = []
            trunc = payload.get("truncated") or {}
            if trunc.get("next_cursor"):
                nexts.append(cmd("search_genes", cursor=trunc["next_cursor"]))
            nexts.extend(after_search_genes(curies, payload.get("query", query)))
            payload["_meta"] = {"next_commands": nexts[:5]}
            return payload
        return await run_mcp_tool(
            "search_genes", call,
            context=McpErrorContext("search_genes", arguments={"query": query}),
            response_mode=response_mode,
        )
```

Import `cmd` in `genes.py`/`diseases.py` (`from gencc_link.mcp.next_commands import ... , cmd`). Apply the same pattern to `get_gene_curations` (page-forward `cmd("get_gene_curations", gene=gene_arg, cursor=...)`), `search_diseases`, `get_disease_curations`.

Note: `query` default becomes `""` so a cursor-only call validates; the service still rejects an empty query when no cursor is supplied. Verify the existing empty-query error test still passes (the service guard runs before cursor restore only when `cursor is None`).

- [ ] **Step 4: Run — expect PASS.** Run the full `tests/test_tools.py` (`pytest tests/test_tools.py -v`) to catch `next_commands` ordering regressions.

- [ ] **Step 5: Commit** — `git commit -am "feat(paging): thread cursor + page-forward next_commands through search/curation tools"`

---

## WS4 — Correctness & observability (Error-handling)

### Task 11: Kind-scoped `resolve_identifier` not-found message

**Files:**
- Modify: `gencc_link/services/gencc_service.py` (`resolve_identifier`, ~line 511-516)
- Test: `tests/test_service.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_service.py
def test_resolve_not_found_message_is_kind_scoped(service) -> None:
    with pytest.raises(NotFoundError) as g:
        service.resolve_identifier("NOTATHING", kind="gene")
    assert "gene" in str(g.value) and "disease" not in str(g.value)
    with pytest.raises(NotFoundError) as d:
        service.resolve_identifier("NOTATHING", kind="disease")
    assert "disease" in str(d.value) and "gene or disease" not in str(d.value)
    with pytest.raises(NotFoundError) as a:
        service.resolve_identifier("NOTATHING", kind="auto")
    assert "gene or disease" in str(a.value)
```

- [ ] **Step 2: Run — expect FAIL.**

- [ ] **Step 3: Implement** — replace the trailing not-found block:

```python
        if result["gene"] is None and result["disease"] is None:
            scope = {"gene": "GenCC gene", "disease": "GenCC disease"}.get(
                kind, "GenCC gene or disease"
            )
            hint = {
                "gene": "Try search_genes.",
                "disease": "Try search_diseases.",
            }.get(kind, "Try search_genes or search_diseases.")
            raise NotFoundError(f"Could not resolve {query!r} to a {scope}. {hint}")
        return result
```

- [ ] **Step 4: Run — expect PASS.**

- [ ] **Step 5: Commit** — `git commit -am "fix(resolve): kind-scoped not-found message"`

### Task 12: `resolve_identifier` dual-arg precedence guard

**Files:**
- Modify: `gencc_link/mcp/tools/assertions.py` (`resolve_identifier`, ~line 159-185)
- Test: `tests/test_tools.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_tools.py
async def test_resolve_dual_arg_conflict_rejected(self, mcp_client) -> None:
    r = await mcp_client.call_tool("resolve_identifier", {"query": "SKI", "identifier": "BRCA2"})
    d = r.structured_content
    assert d["success"] is False and d["error_code"] == "invalid_input"

async def test_resolve_dual_arg_equal_ok(self, mcp_client) -> None:
    r = await mcp_client.call_tool("resolve_identifier", {"query": "SKI", "identifier": "SKI"})
    assert r.structured_content["success"] is True
```

- [ ] **Step 2: Run — expect FAIL** (currently `identifier` silently dropped → SKI succeeds).

- [ ] **Step 3: Implement** — in the tool `call()`:

```python
        async def call() -> dict[str, Any]:
            if (
                query is not None and identifier is not None
                and query.strip() != identifier.strip()
            ):
                raise InvalidInputError(
                    "Pass only one of `query`/`identifier` (they are aliases); "
                    f"got query={query!r} and identifier={identifier!r}.",
                    field="query",
                )
            q = query if query is not None else identifier
            if q is None:
                raise InvalidInputError("query must not be empty.", field="query")
            payload = get_gencc_service().resolve_identifier(q, kind=kind)
            ...
```

Update the tool description: note `identifier` is an alias for `query` and only one may be set. (`InvalidInputError` is already imported in `assertions.py`.)

- [ ] **Step 4: Run — expect PASS.**

- [ ] **Step 5: Commit** — `git commit -am "fix(resolve): reject conflicting query/identifier aliases"`

### Task 13: Batch dedup observability (`received` + `duplicates`)

**Files:**
- Modify: `gencc_link/services/gencc_service.py` (`_dedupe_batch`, `get_genes_curations`, `get_diseases_curations`)
- Test: `tests/test_service.py`

- [ ] **Step 1: Write failing tests** (extend the existing dedup test):

```python
# tests/test_service.py  (replace test_genes_curations_dedupes_preserving_order)
def test_genes_curations_dedupes_preserving_order(self, service) -> None:
    out = service.get_genes_curations(["SKI", "ski", "SKI"])
    assert out["requested"] == 1          # distinct queried (back-compat)
    assert out["received"] == 3           # raw input length
    assert out["duplicates"] == ["ski", "SKI"]
    assert out["count"] == 1

def test_genes_curations_no_duplicates_block_when_unique(self, service) -> None:
    out = service.get_genes_curations(["SKI", "GLA"])
    assert out["received"] == 2
    assert "duplicates" not in out
```

- [ ] **Step 2: Run — expect FAIL.**

- [ ] **Step 3: Implement** — `_dedupe_batch` returns `(ordered, duplicates)`:

```python
    @staticmethod
    def _dedupe_batch(items: list[str], *, field: str) -> tuple[list[str], list[str]]:
        """Validate, de-duplicate (case-insensitively), and report folded duplicates."""
        if not items:
            raise InvalidInputError(f"{field} must not be empty.", field=field)
        if len(items) > _BATCH_MAX:
            raise InvalidInputError(
                f"Too many values ({len(items)}); max {_BATCH_MAX} per call.", field=field
            )
        seen: set[str] = set()
        ordered: list[str] = []
        duplicates: list[str] = []
        for raw in items:
            if not isinstance(raw, str) or not raw.strip():
                raise InvalidInputError(
                    f"each {field} value must be a non-empty string.", field=field
                )
            value = raw.strip()
            if value.lower() in seen:
                duplicates.append(value)
                continue
            seen.add(value.lower())
            ordered.append(value)
        return ordered, duplicates
```

In `get_genes_curations` / `get_diseases_curations`, update the call site and payload:

```python
        ordered, duplicates = self._dedupe_batch(genes, field="genes")
        ...
        fold = f" ({len(duplicates)} duplicate(s) folded)" if duplicates else ""
        payload: dict[str, Any] = {
            "headline": (
                f"Curations for {len(results)} of {len(ordered)} requested gene(s) "
                f"({len(unresolved)} unresolved){fold}."
            ),
            "received": len(genes),
            "requested": len(ordered),
            "count": len(results),
            "results": results,
        }
        if duplicates:
            payload["duplicates"] = duplicates
        if unresolved:
            payload["unresolved"] = unresolved
        return payload
```

Apply the identical change to `get_diseases_curations` (field `diseases`, raw `diseases`).

- [ ] **Step 4: Run — expect PASS** (`pytest tests/test_service.py -k Batch -v`).

- [ ] **Step 5: Commit** — `git commit -am "feat(batch): echo received + folded duplicates for observability"`

---

## WS5 — Documentation completeness (Discoverability)

### Task 14: `tool_defaults`, annotated `error_codes`, `conflict_semantics`, `ambiguous_query_example`

**Files:**
- Modify: `gencc_link/mcp/capabilities.py` (`_static_surface`)
- Test: `tests/test_capabilities.py`, `tests/test_tools.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_tools.py
async def test_capabilities_documents_defaults_and_conflict(self, mcp_client) -> None:
    sc = (await mcp_client.call_tool("get_server_capabilities", {})).structured_content
    td = sc["tool_defaults"]
    assert td["get_gene_disease_assertion"] == "standard"
    assert td["search_genes"] == "compact" and td["find_curations"] == "compact"
    cs = sc["conflict_semantics"]
    assert set(cs["supporting"]) == {"Definitive", "Strong", "Moderate"}
    assert "No Known Disease Relationship" in cs["against"]
    assert "Animal Model Only" in cs["excluded"]
    # operational-only error codes annotated + flat list retained
    codes = {e["code"]: e for e in sc["error_codes"]}
    assert codes["data_unavailable"]["operational_only"] is True
    assert codes["invalid_input"]["operational_only"] is False
    assert "ambiguous_query_example" in sc
    assert sc["error_codes_list"]  # back-compat flat list
```

- [ ] **Step 2: Run — expect FAIL.**

- [ ] **Step 3: Implement** — in `_static_surface`, import the conflict sets and replace the flat `error_codes`:

```python
from gencc_link.constants import (
    AGAINST_CLASSIFICATIONS,
    CLASSIFICATION_ORDER,
    CLASSIFICATION_RANKS,
    DATA_LICENSE,
    RECOMMENDED_CITATION,
    SUPPORTING_CLASSIFICATIONS,
)
```

```python
        "tool_defaults": {
            "get_server_capabilities": "n/a",
            "get_gencc_diagnostics": "n/a",
            "search_genes": "compact",
            "search_diseases": "compact",
            "get_gene_curations": "compact",
            "get_disease_curations": "compact",
            "get_genes_curations": "compact",
            "get_diseases_curations": "compact",
            "get_gene_disease_assertion": "standard",
            "find_curations": "compact",
            "list_submitters": "n/a",
            "resolve_identifier": "n/a",
        },
        "error_codes": [
            {"code": "invalid_input", "operational_only": False,
             "when": "malformed/out-of-vocab argument; carries field_errors + accepted set"},
            {"code": "not_found", "operational_only": False,
             "when": "a well-formed identifier resolves to nothing"},
            {"code": "ambiguous_query", "operational_only": False,
             "when": "resolve_identifier(kind='auto') when text matches a gene AND a disease"},
            {"code": "data_unavailable", "operational_only": True,
             "when": "database not built (ingest/ops)"},
            {"code": "upstream_unavailable", "operational_only": True,
             "when": "thegencc.org download failed (ingest/ops)"},
            {"code": "rate_limited", "operational_only": True,
             "when": "GenCC daily download quota exceeded (ingest/ops)"},
            {"code": "internal_error", "operational_only": True,
             "when": "unexpected server fault"},
        ],
        "error_codes_list": [
            "invalid_input", "not_found", "ambiguous_query", "data_unavailable",
            "upstream_unavailable", "rate_limited", "internal_error",
        ],
        "conflict_semantics": {
            "supporting": sorted(SUPPORTING_CLASSIFICATIONS, key=lambda t: -CLASSIFICATION_RANKS[t]),
            "against": sorted(AGAINST_CLASSIFICATIONS, key=lambda t: -CLASSIFICATION_RANKS[t]),
            "excluded": [t for t in CLASSIFICATION_ORDER
                         if t not in SUPPORTING_CLASSIFICATIONS and t not in AGAINST_CLASSIFICATIONS],
            "rule": "has_conflict is true when at least one supporting and one against "
                    "classification coexist for a pair; excluded tiers never trigger it.",
        },
        "ambiguous_query_example": {
            "trigger": "resolve_identifier(query=X, kind='auto') where X is, case-insensitively, "
                       "both an approved gene symbol and a harmonized disease title",
            "note": "Harmonized MONDO titles are descriptive phrases, so exact symbol/title "
                    "collisions are rare in current data; pass kind='gene' or kind='disease' to "
                    "disambiguate deterministically. ambiguous_query is never raised when kind is set.",
        },
```

(Remove the old flat `"error_codes": [...]` literal.) Keep the existing `error_codes`-referencing comment accurate.

- [ ] **Step 4: Run — expect PASS.** `capabilities_version` changes (expected; it is content-hashed). Update any test pinning the *old* hash (`grep -rn "capabilities_version\|f8007316" tests/`); assert it is a 16-hex string, not a fixed value.

- [ ] **Step 5: Commit** — `git commit -am "docs(capabilities): tool_defaults, annotated error codes, conflict_semantics, ambiguous example"`

### Task 15: `response_fields` additions + reference/usage text

**Files:**
- Modify: `gencc_link/mcp/capabilities.py` (`response_fields`, `response_modes`, `token_cost_hints`), `gencc_link/mcp/resources.py`
- Test: `tests/test_capabilities.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_capabilities.py
def test_capabilities_documents_new_fields() -> None:
    from gencc_link.mcp.capabilities import build_capabilities
    cap = build_capabilities()
    rf = cap["response_fields"]
    assert "received" in rf and "duplicates" in rf and "tool_defaults" in rf
    assert "conflict_semantics" in rf
    # cursor now general, not find_curations-only
    assert "all paged tools" in rf["cursor"].lower() or "search" in rf["cursor"].lower()
    assert "full" in cap["response_modes"]
```

- [ ] **Step 2: Run — expect FAIL.**

- [ ] **Step 3: Implement** — add to `response_fields`:

```python
            "received": "get_genes_curations/get_diseases_curations: raw input list length "
            "before case-insensitive de-duplication (requested = distinct queried).",
            "duplicates": "get_genes_curations/get_diseases_curations: the folded duplicate "
            "inputs (present only when some were removed).",
            "tool_defaults": "per-tool default response_mode (see top-level tool_defaults).",
            "conflict_semantics": "the supporting/against/excluded classification tiers that "
            "define has_conflict (see top-level conflict_semantics).",
```

Update the existing `cursor` and `next_cursor` `response_fields` entries to say *all paged tools* (search_genes/search_diseases/get_gene_curations/get_disease_curations/find_curations), and update `response_modes["full"]` to describe the de-duplicated shape:

```python
            "full": "adds submitter curies, criteria URLs, and PMIDs per submitter; "
            "get_gene_disease_assertion also returns raw-extras submissions[] "
            "(sgc_id, notes, original disease ids, version) — not the harmonized fields "
            "already in submitters[]. No pair-level union pmids.",
```

In `resources.py`, update `GENCC_REFERENCE_NOTES` paging sentence to cover all paged tools and the full-mode split, and `GENCC_USAGE_NOTES` to mention cursor paging on search/curation tools. Keep ASCII.

- [ ] **Step 4: Run — expect PASS** (`pytest tests/test_capabilities.py -v`).

- [ ] **Step 5: Commit** — `git commit -am "docs(capabilities): document received/duplicates, general cursor, full-mode shape"`

### Task 16: Output schemas surface new fields

**Files:**
- Modify: `gencc_link/mcp/schemas.py`
- Test: `tests/test_tools.py` (structured-content validation already exercised)

- [ ] **Step 1: Implement** — extend the batch schema and truncation:

```python
GENES_CURATIONS_SCHEMA = tool_output_schema(
    received=_INT, requested=_INT, count=_INT, results=_OBJ_ARRAY,
    duplicates=_ARRAY, unresolved=_OBJ_ARRAY,
)
DISEASES_CURATIONS_SCHEMA = GENES_CURATIONS_SCHEMA
```

Add `next_cursor` to `_TRUNCATION.properties` (`"next_cursor": _STR`). The `_META` block is already permissive (`additionalProperties: True`) so no change needed there.

- [ ] **Step 2: Run** `pytest tests/test_tools.py -v` — structured-content conforms (schemas are permissive; this just enriches the glossary).

- [ ] **Step 3: Commit** — `git commit -am "docs(schemas): surface received/duplicates/next_cursor in output schemas"`

---

## WS6 — Release & closure

### Task 17: Tool descriptions + server instructions touch-ups

**Files:** `gencc_link/mcp/tools/assertions.py`, `genes.py`, `diseases.py`, `gencc_link/mcp/resources.py` (`GENCC_SERVER_INSTRUCTIONS`)

- [ ] **Step 1:** Update `get_gene_disease_assertion` description: full mode returns harmonized `submitters[]` plus raw-extras `submissions[]` (no duplicated fields, no union pmids). Update `search_*`/`get_*_curations` descriptions to mention release-bound `cursor` paging (parity with find_curations). One sentence each; keep ASCII; stay within line length.

- [ ] **Step 2:** `make format lint` — fix wrapping.

- [ ] **Step 3: Commit** — `git commit -am "docs(tools): describe full-mode split and cursor paging in tool descriptions"`

### Task 18: Version bump + CHANGELOG + assessment resolution

**Files:** `pyproject.toml`, `CHANGELOG.md`, `uv.lock`, `docs/mcp-consumer-assessment-v0.3.0.md`

- [ ] **Step 1:** Bump `pyproject.toml` `version = "0.4.0"`; run `make lock` (or `uv lock`) to refresh `uv.lock`.

- [ ] **Step 2:** Prepend a `## 0.4.0` CHANGELOG section: full-mode de-duplication (union pmids dropped, submissions[] slimmed to raw-extras), citation_ref-only error envelopes + data_license-in-full-only, uniform release-bound cursor paging across search/curation tools, kind-scoped resolve message, dual-arg guard, batch received/duplicates, capabilities tool_defaults/conflict_semantics/annotated error codes.

- [ ] **Step 3:** Append a "## Resolution (v0.4.0)" section to `docs/mcp-consumer-assessment-v0.3.0.md` — a table mapping each Part-1 improvement and Part-2 defect (#1–#8) to its commit/workstream and status (Resolved / Documented / Deferred-with-rationale for the one-shot tool and title auto-resolve).

- [ ] **Step 4: Commit** — `git commit -am "release(0.4.0): version, changelog, assessment resolution"`

### Task 19: Final gate

- [ ] **Step 1:** Run `make ci-local`. Expected: format clean, lint clean, **lint-loc all modules ≤600**, mypy strict clean, tests pass, coverage ≥85%.

- [ ] **Step 2:** If `gencc_service.py` > 600: fold the two cursor-restore helpers into one and/or extract `_paging.py` (a tiny module with the restore helper). Re-run.

- [ ] **Step 3:** Confirm `capabilities_version` is internally regenerated (no stale hash committed in docs/tests).

- [ ] **Step 4: Commit** any final fixups — `git commit -am "chore: ci-local green for v0.4.0"`

---

## Self-review notes

- **Spec coverage:** WS1↔Tasks 1-3, WS2↔4-5, WS3↔6-10, WS4↔11-13, WS5↔14-16, release↔17-19. Every Part-1 (#1 token, #2 citation, #3 static, #5 per-tool default) and Part-2 (#1 kind msg, #2 batch dedup, #3 dual-arg, #4 cross-tool paging, #5 full redundancy, #6 error citation, #7 ambiguous/operational codes, #8 default modes) finding maps to a task. #4 one-shot tool and #8 auto-resolve: deferred in spec, recorded in Task 18 resolution table.
- **Type consistency:** `_dedupe_batch` returns `(ordered, duplicates)` everywhere it's called (Task 13 updates both batch methods); `decode_paged_cursor(token, *, current_release)` signature used identically in Tasks 6-9; `_restore_search_cursor`/`_restore_id_cursor` (or the folded `_restore_cursor`) consistent across Tasks 8-9.
- **No fixed-hash assertions:** Task 14 step 4 explicitly removes any test pinning `f8007316...`.
- **LOC discipline:** Tasks 7/8/9/19 watch `gencc_service.py` against the 600 cap with a concrete fallback (fold helpers / extract `_paging.py`).
