# MCP Evaluation Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close every gap in `docs/mcp-evaluation.md` (H1/M1/M2/M3/L1/L2/L3 + observability scorecard items) to reach a >9.5/10 LLM-consumer experience without changing the schema or tool inventory.

**Architecture:** Bottom-up. A new pure `filters.py` does enum validation/canonicalisation. The repository surfaces `matched` provenance + distinct MOI. The service wires validation + matched. The envelope/next_commands layer adds observability (`request_id`, `elapsed_ms`), mode-aware citation, and error `next_commands`. Capabilities/docs/downloader round it out.

**Tech Stack:** Python 3.12, FastMCP, SQLite/FTS5, pydantic, pytest + respx, Ruff, mypy strict. Commands via `make`.

---

## File Structure

- Create `gencc_link/services/filters.py` — pure enum validation + canonicalisation.
- Modify `gencc_link/data/base.py` — Protocol: `distinct_moi`, new `find_assertions` return.
- Modify `gencc_link/data/repository.py` — `distinct_moi`, matched-aware `find_assertions`.
- Modify `gencc_link/services/gencc_service.py` — validate filters, attach `matched`, pass `omit_*`.
- Modify `gencc_link/services/shaping.py` — `assertion_dict(..., omit_gene, omit_disease)`.
- Modify `gencc_link/mcp/next_commands.py` — query-propagating search fallbacks, `recovery_commands`.
- Modify `gencc_link/mcp/envelope.py` — `request_id`/`elapsed_ms`, mode-aware citation, error `next_commands`, `McpErrorContext.arguments`.
- Modify `gencc_link/mcp/tools/{genes,diseases,assertions,discovery}.py` — pass `response_mode`+`arguments`; propagate query; quota in diagnostics.
- Modify `gencc_link/mcp/capabilities.py` — `inheritance_modes`, `data_notes`, conventions, response_fields.
- Modify `gencc_link/mcp/resources.py` — reference-note quirks + filter semantics.
- Modify `gencc_link/ingest/downloader.py` — quota counter + `download_quota_status`.
- Modify docs: `README.md`, `docs/usage.md`, `docs/MCP_CONNECTION_GUIDE.md`, annotate `docs/mcp-evaluation.md`.
- Tests: new `tests/test_filters.py`; extend `test_repository`, `test_service`, `test_shaping`, `test_next_commands`, `test_envelope`, `test_capabilities`, `test_downloader`, `test_tools`.

---

## Task 1: Pure filter validation module (H1, L1 canonicalisation)

**Files:**
- Create: `gencc_link/services/filters.py`
- Test: `tests/test_filters.py`

- [ ] **Step 1: Write failing tests** in `tests/test_filters.py`:

```python
"""Tests for find_curations filter validation (gencc_link.services.filters)."""
from __future__ import annotations

import pytest

from gencc_link.exceptions import InvalidInputError
from gencc_link.services.filters import validate_find_filters

SUBM_TITLES = {"ClinGen", "Ambry Genetics", "Labcorp Genetics (formerly Invitae)"}
SUBM_CURIES = {"GENCC:000102", "GENCC:000101", "GENCC:000106"}
MOI_TITLES = {"Autosomal dominant", "Autosomal recessive", "Y-linked inheritance"}


def _run(**kw):
    base = dict(
        classification=None, submitter=None, moi=None,
        valid_submitter_titles=SUBM_TITLES, valid_submitter_curies=SUBM_CURIES,
        valid_moi_titles=MOI_TITLES,
    )
    base.update(kw)
    return validate_find_filters(**base)


class TestClassification:
    def test_canonicalises_case(self):
        c, _, _ = _run(classification=["definitive", "STRONG"])
        assert c == ["Definitive", "Strong"]

    def test_rejects_unknown_with_suggestion(self):
        with pytest.raises(InvalidInputError) as e:
            _run(classification=["Pathogenic"])
        assert e.value.field == "classification"
        assert "Pathogenic" in e.value.message
        assert "Definitive" in e.value.message  # accepted values listed

    def test_collects_multiple_invalid(self):
        with pytest.raises(InvalidInputError) as e:
            _run(classification=["Pathogenic", "Benign"])
        assert "Pathogenic" in e.value.message and "Benign" in e.value.message


class TestSubmitter:
    def test_canonicalises_title_case(self):
        _, s, _ = _run(submitter=["clingen"])
        assert s == ["ClinGen"]

    def test_accepts_curie(self):
        _, s, _ = _run(submitter=["GENCC:000102"])
        assert s == ["GENCC:000102"]

    def test_rejects_unknown_points_to_list_submitters(self):
        with pytest.raises(InvalidInputError) as e:
            _run(submitter=["NotARealLab"])
        assert e.value.field == "submitter"
        assert "list_submitters" in e.value.message


class TestMoi:
    def test_canonicalises_case(self):
        _, _, m = _run(moi="autosomal recessive")
        assert m == "Autosomal recessive"

    def test_rejects_short_form_with_did_you_mean(self):
        with pytest.raises(InvalidInputError) as e:
            _run(moi="Recessive")
        assert e.value.field == "moi"
        assert "Autosomal recessive" in e.value.message

    def test_accepts_quirky_real_title(self):
        _, _, m = _run(moi="y-linked inheritance")
        assert m == "Y-linked inheritance"


def test_all_none_passes_through():
    assert _run() == (None, None, None)
```

- [ ] **Step 2: Run** `make test ARGS="tests/test_filters.py"` (or `uv run pytest tests/test_filters.py -q`) → FAIL (module missing).

- [ ] **Step 3: Implement** `gencc_link/services/filters.py`:

```python
"""Validation + canonicalisation of find_curations enum filters.

Pure functions (no repository/MCP dependency): the caller passes the
data-derived valid sets in. Out-of-vocabulary values raise InvalidInputError
with the accepted values and a 'did you mean' suggestion, turning the previous
silent count:0 into an actionable error.
"""
from __future__ import annotations

import difflib

from gencc_link.constants import CLASSIFICATION_ORDER
from gencc_link.exceptions import InvalidInputError


def _suggest(value: str, options: list[str]) -> str:
    match = difflib.get_close_matches(value, options, n=1, cutoff=0.4)
    return f" Did you mean {match[0]!r}?" if match else ""


def _canonical_map(values: set[str]) -> dict[str, str]:
    return {v.casefold(): v for v in values}


def _validate_list(
    values: list[str], canon: dict[str, str], *, field: str, accepted_hint: str
) -> list[str]:
    out: list[str] = []
    invalid: list[str] = []
    for v in values:
        hit = canon.get(v.strip().casefold())
        if hit is None:
            invalid.append(v)
        else:
            out.append(hit)
    if invalid:
        listed = ", ".join(repr(x) for x in invalid)
        suggestion = _suggest(invalid[0], list(canon.values()))
        raise InvalidInputError(
            f"{listed} not a valid {field}.{suggestion} {accepted_hint}",
            field=field,
        )
    return out


def validate_find_filters(
    *,
    classification: list[str] | None,
    submitter: list[str] | None,
    moi: str | None,
    valid_submitter_titles: set[str],
    valid_submitter_curies: set[str],
    valid_moi_titles: set[str],
) -> tuple[list[str] | None, list[str] | None, str | None]:
    """Return canonicalised (classification, submitter, moi) or raise InvalidInputError."""
    canon_class: list[str] | None = None
    if classification:
        accepted = ", ".join(CLASSIFICATION_ORDER)
        canon_class = _validate_list(
            classification,
            {c.casefold(): c for c in CLASSIFICATION_ORDER},
            field="classification",
            accepted_hint=f"Accepted: {accepted}.",
        )

    canon_subm: list[str] | None = None
    if submitter:
        canon = _canonical_map(valid_submitter_titles | valid_submitter_curies)
        canon_subm = _validate_list(
            submitter,
            canon,
            field="submitter",
            accepted_hint="Call list_submitters for the accepted roster.",
        )

    canon_moi: str | None = None
    if moi and moi.strip():
        canon = _canonical_map(valid_moi_titles)
        accepted = ", ".join(sorted(valid_moi_titles))
        canon_moi = _validate_list(
            [moi], canon, field="moi", accepted_hint=f"Accepted: {accepted}."
        )[0]

    return canon_class, canon_subm, canon_moi
```

- [ ] **Step 4: Run** `uv run pytest tests/test_filters.py -q` → PASS.
- [ ] **Step 5: Commit** `feat(filters): pure enum validation + canonicalisation for find_curations`.

---

## Task 2: Repository `distinct_moi` + matched-aware `find_assertions`

**Files:**
- Modify: `gencc_link/data/base.py`, `gencc_link/data/repository.py`
- Test: `tests/test_repository.py`

- [ ] **Step 1: Write failing tests** (append to `tests/test_repository.py`, using existing repo fixture; check fixture name in file, commonly `repo`):

```python
class TestFindMatched:
    def test_distinct_moi_includes_fixture_values(self, repo):
        titles = {t for t, _ in repo.distinct_moi()}
        assert {"Autosomal dominant", "Autosomal recessive", "X-linked"} <= titles

    def test_find_assertions_returns_matched_map(self, repo):
        page, total, matched = repo.find_assertions(
            classification=["Refuted Evidence"], limit=50, offset=0
        )
        assert total == len(page)
        # every returned pair has a matched record naming the Refuted submission
        for a in page:
            key = (a.gene_curie, a.disease_curie)
            assert key in matched
            assert any(m["classification_title"] == "Refuted Evidence" for m in matched[key])

    def test_find_assertions_no_submission_filter_empty_matched(self, repo):
        page, total, matched = repo.find_assertions(has_conflict=True, limit=50, offset=0)
        assert matched == {}
        assert total == len(page)
```

- [ ] **Step 2: Run** `uv run pytest tests/test_repository.py::TestFindMatched -q` → FAIL.

- [ ] **Step 3a: Update Protocol** `gencc_link/data/base.py` — change `find_assertions` return type and add `distinct_moi`:

```python
    def find_assertions(
        self,
        *,
        gene: str | None = None,
        disease: str | None = None,
        classification: list[str] | None = None,
        submitter: list[str] | None = None,
        moi: str | None = None,
        has_conflict: bool | None = None,
        limit: int,
        offset: int,
    ) -> tuple[list[GeneDiseaseAssertion], int, dict[tuple[str, str], list[dict[str, str | None]]]]:
        """Filter assertions. Returns (page, total, matched_by_pair).

        ``matched_by_pair`` maps each (gene_curie, disease_curie) to the distinct
        submissions that satisfied a submission-level filter; empty when none.
        """
        ...

    def distinct_moi(self) -> list[tuple[str, str | None]]:
        """Distinct (moi_title, moi_curie) present in the submissions table."""
        ...
```

- [ ] **Step 3b: Implement in** `gencc_link/data/repository.py`. Replace `_pairs_from_submissions` to return a matched map, update `find_assertions`, add `distinct_moi`:

```python
    def find_assertions(
        self, *, gene=None, disease=None, classification=None,
        submitter=None, moi=None, has_conflict=None, limit, offset,
    ):
        gene_curie = None
        if gene is not None:
            resolved = self.resolve_gene(gene)
            if resolved is None:
                return [], 0, {}
            gene_curie = resolved.gene_curie

        submission_filtered = bool(classification) or bool(submitter) or bool(moi)
        matched: dict[tuple[str, str], list[dict[str, str | None]]] = {}
        if submission_filtered:
            matched = self._matched_from_submissions(
                gene_curie=gene_curie, disease_curie=disease,
                classification=classification, submitter=submitter, moi=moi,
            )
            if not matched:
                return [], 0, {}
            rows = self._gene_disease_rows_for_pairs(set(matched), has_conflict=has_conflict)
        else:
            rows = self._gene_disease_rows_direct(
                gene_curie=gene_curie, disease_curie=disease, has_conflict=has_conflict
            )
        total = len(rows)
        page = rows[offset : offset + limit]
        # drop matched entries filtered out by has_conflict
        kept = {(r["gene_curie"], r["disease_curie"]) for r in rows}
        matched = {k: v for k, v in matched.items() if k in kept}
        return [assertion_from_row(row) for row in page], total, matched

    def _matched_from_submissions(
        self, *, gene_curie, disease_curie, classification, submitter, moi,
    ) -> dict[tuple[str, str], list[dict[str, str | None]]]:
        clauses: list[str] = []
        params: list[object] = []
        if gene_curie is not None:
            clauses.append("gene_curie = ?"); params.append(gene_curie)
        if disease_curie is not None:
            clauses.append("disease_curie = ?"); params.append(disease_curie)
        if classification:
            ph = ",".join("?" for _ in classification)
            clauses.append(f"classification_title IN ({ph})"); params.extend(classification)
        if submitter:
            ph = ",".join("?" for _ in submitter)
            clauses.append(f"(submitter_title IN ({ph}) OR submitter_curie IN ({ph}))")
            params.extend(submitter); params.extend(submitter)
        if moi:
            clauses.append("moi_title = ? COLLATE NOCASE"); params.append(moi)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = (
            "SELECT gene_curie, disease_curie, submitter_title, classification_title, "
            f"moi_title FROM submissions{where}"
        )
        out: dict[tuple[str, str], list[dict[str, str | None]]] = {}
        seen: set[tuple] = set()
        for row in self._conn.execute(sql, params).fetchall():
            key = (row["gene_curie"], row["disease_curie"])
            tup = (key, row["submitter_title"], row["classification_title"], row["moi_title"])
            if tup in seen:
                continue
            seen.add(tup)
            out.setdefault(key, []).append({
                "submitter_title": row["submitter_title"],
                "classification_title": row["classification_title"],
                "moi_title": row["moi_title"],
            })
        return out

    def distinct_moi(self) -> list[tuple[str, str | None]]:
        rows = self._conn.execute(
            "SELECT moi_title, MAX(moi_curie) c FROM submissions "
            "WHERE moi_title IS NOT NULL AND moi_title != '' GROUP BY moi_title ORDER BY moi_title"
        ).fetchall()
        return [(row["moi_title"], row["c"]) for row in rows]
```

Delete the old `_pairs_from_submissions` (replaced by `_matched_from_submissions`).

- [ ] **Step 4: Run** `uv run pytest tests/test_repository.py -q` → PASS (fix any other callers of `find_assertions`/`_pairs_from_submissions`).
- [ ] **Step 5: Commit** `feat(repository): surface matched submissions + distinct_moi for find_curations`.

---

## Task 3: Service wires validation + matched (H1, M1)

**Files:**
- Modify: `gencc_link/services/gencc_service.py`
- Test: `tests/test_service.py`

- [ ] **Step 1: Write failing tests** (append to `tests/test_service.py`, using existing `service` fixture):

```python
class TestFindValidation:
    def test_invalid_classification_raises(self, service):
        import pytest
        from gencc_link.exceptions import InvalidInputError
        with pytest.raises(InvalidInputError) as e:
            service.find_curations(classification=["Pathogenic"])
        assert e.value.field == "classification"

    def test_invalid_submitter_raises(self, service):
        import pytest
        from gencc_link.exceptions import InvalidInputError
        with pytest.raises(InvalidInputError):
            service.find_curations(submitter=["NotARealLab"])

    def test_invalid_moi_raises(self, service):
        import pytest
        from gencc_link.exceptions import InvalidInputError
        with pytest.raises(InvalidInputError):
            service.find_curations(moi="Recessive")

    def test_case_insensitive_filter_returns_data(self, service):
        lower = service.find_curations(classification=["definitive"])
        canon = service.find_curations(classification=["Definitive"])
        assert lower["total"] == canon["total"] and lower["total"] > 0

    def test_matched_present_in_compact(self, service):
        out = service.find_curations(classification=["Refuted Evidence"], response_mode="compact")
        assert out["results"]
        assert all("matched" in r for r in out["results"])

    def test_matched_absent_in_minimal(self, service):
        out = service.find_curations(classification=["Refuted Evidence"], response_mode="minimal")
        assert all("matched" not in r for r in out["results"])

    def test_no_matched_without_submission_filter(self, service):
        out = service.find_curations(has_conflict=True)
        assert all("matched" not in r for r in out["results"])
```

- [ ] **Step 2: Run** `uv run pytest tests/test_service.py::TestFindValidation -q` → FAIL.

- [ ] **Step 3: Edit** `find_curations` in `gencc_link/services/gencc_service.py`. After the "at least one filter" check, validate, then thread matched through:

```python
        from gencc_link.services.filters import validate_find_filters

        valid_subm_titles: set[str] = set()
        valid_subm_curies: set[str] = set()
        valid_moi_titles: set[str] = set()
        if submitter:
            subs = self._repo.list_submitters()
            valid_subm_titles = {s.submitter_title for s in subs if s.submitter_title}
            valid_subm_curies = {s.submitter_curie for s in subs if s.submitter_curie}
        if moi and moi.strip():
            valid_moi_titles = {t for t, _ in self._repo.distinct_moi()}

        classification, submitter, moi_canon = validate_find_filters(
            classification=classification,
            submitter=submitter,
            moi=moi,
            valid_submitter_titles=valid_subm_titles,
            valid_submitter_curies=valid_subm_curies,
            valid_moi_titles=valid_moi_titles,
        )

        results, total, matched = self._repo.find_assertions(
            gene=gene.strip() if gene else None,
            disease=disease.strip() if disease else None,
            classification=classification,
            submitter=submitter,
            moi=moi_canon,
            has_conflict=has_conflict,
            limit=limit,
            offset=offset,
        )
        rows: list[dict[str, Any]] = []
        for a in results:
            row = shaping.assertion_dict(a, mode)
            if matched and mode != "minimal":
                row["matched"] = matched.get((a.gene_curie, a.disease_curie), [])
            rows.append(row)
        payload: dict[str, Any] = {
            "count": len(results),
            "total": total,
            "filters": {
                "gene": gene, "disease": disease, "classification": classification,
                "submitter": submitter, "moi": moi_canon, "has_conflict": has_conflict,
            },
            "results": rows,
        }
```

(Keep the existing `truncated` block and return.)

- [ ] **Step 4: Run** `uv run pytest tests/test_service.py -q` → PASS.
- [ ] **Step 5: Commit** `feat(service): validate find_curations enums and attach matched provenance`.

---

## Task 4: Shaping `omit_gene`/`omit_disease` (L2)

**Files:**
- Modify: `gencc_link/services/shaping.py`
- Test: `tests/test_shaping.py`

- [ ] **Step 1: Write failing tests** (append to `tests/test_shaping.py`; reuse an assertion factory already present, e.g. `make_assertion()` — check the file for the helper name):

```python
class TestOmitParentId:
    def test_omit_gene_compact(self, sample_assertion):
        out = shaping.assertion_dict(sample_assertion, "compact", omit_gene=True)
        assert "gene_curie" not in out and "gene_symbol" not in out
        assert out["disease_curie"]

    def test_omit_disease_compact(self, sample_assertion):
        out = shaping.assertion_dict(sample_assertion, "compact", omit_disease=True)
        assert "disease_curie" not in out and "disease_title" not in out
        assert out["gene_curie"]

    def test_omit_ignored_in_standard(self, sample_assertion):
        out = shaping.assertion_dict(sample_assertion, "standard", omit_gene=True)
        assert out["gene_curie"]
```

(If no `sample_assertion` fixture exists, build one inline from `GeneDiseaseAssertion` mirroring existing test_shaping construction.)

- [ ] **Step 2: Run** `uv run pytest tests/test_shaping.py::TestOmitParentId -q` → FAIL.

- [ ] **Step 3: Edit** `assertion_dict` signature + body:

```python
def assertion_dict(
    a: GeneDiseaseAssertion, mode: ResponseMode, *,
    omit_gene: bool = False, omit_disease: bool = False,
) -> dict[str, Any]:
    """Shape an aggregated gene-disease assertion per response_mode.

    omit_gene/omit_disease drop the parent identifier from rows where the parent
    object already carries it (minimal/compact only) to cut per-row redundancy.
    """
    trim = mode in ("minimal", "compact")
    out: dict[str, Any] = {}
    if not (omit_gene and trim):
        out["gene_curie"] = a.gene_curie
        out["gene_symbol"] = a.gene_symbol
    if not (omit_disease and trim):
        out["disease_curie"] = a.disease_curie
        out["disease_title"] = a.disease_title
    out["consensus_classification"] = a.consensus_classification
    out["n_submitters"] = a.n_submitters
    out["n_submissions"] = a.n_submissions
    out["has_conflict"] = a.has_conflict
    if mode == "minimal":
        return out
    out["min_classification"] = a.min_classification
    out["classification_titles"] = a.classification_titles
    out["moi_titles"] = a.moi_titles
    if mode == "compact":
        out["submitter_titles"] = a.submitter_titles
        return out
    out["submitters"] = [_submitter_dict(s, mode) for s in a.submitters]
    if mode == "full":
        out["pmids"] = a.pmids
    return out
```

- [ ] **Step 4: Run** `uv run pytest tests/test_shaping.py -q` → PASS.
- [ ] **Step 5: Commit** `feat(shaping): drop redundant parent id from rows in minimal/compact`.

---

## Task 5: Service curations use `omit_*` (L2)

**Files:**
- Modify: `gencc_link/services/gencc_service.py`
- Test: `tests/test_service.py`

- [ ] **Step 1: Write failing tests** (append):

```python
class TestRowTrim:
    def test_gene_curations_drops_gene_id_in_compact(self, service):
        out = service.get_gene_curations("SKI", response_mode="compact")
        assert out["gene"]["gene_curie"]
        assert all("gene_curie" not in d for d in out["diseases"])

    def test_disease_curations_drops_disease_id_in_compact(self, service):
        out = service.get_disease_curations("MONDO:0008426", response_mode="compact")
        assert out["disease"]["disease_curie"]
        assert all("disease_curie" not in g for g in out["genes"])
```

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Edit** the two list comprehensions:

```python
            "diseases": [shaping.assertion_dict(a, mode, omit_gene=True) for a in page],
```
```python
            "genes": [shaping.assertion_dict(a, mode, omit_disease=True) for a in page],
```

- [ ] **Step 4: Run** `uv run pytest tests/test_service.py -q` → PASS.
- [ ] **Step 5: Commit** `feat(service): trim redundant parent id from gene/disease curation rows`.

---

## Task 6: next_commands — query propagation + recovery map (M2, M3)

**Files:**
- Modify: `gencc_link/mcp/next_commands.py`
- Test: `tests/test_next_commands.py`

- [ ] **Step 1: Write failing tests** (append; update the two `test_empty` cases to pass a query):

```python
class TestQueryPropagation:
    def test_search_genes_empty_propagates_query(self):
        out = nc.after_search_genes([], "ZZZX")
        assert out == [{"tool": "search_diseases", "arguments": {"query": "ZZZX"}}]

    def test_search_diseases_empty_propagates_query(self):
        out = nc.after_search_diseases([], "ZZZX")
        assert out == [{"tool": "search_genes", "arguments": {"query": "ZZZX"}}]


class TestRecoveryCommands:
    def test_not_found_gene_curations(self):
        out = nc.recovery_commands("get_gene_curations", "not_found", {"gene": "ZZZ"}, None)
        assert out == [{"tool": "search_genes", "arguments": {"query": "ZZZ"}}]

    def test_not_found_assertion_two_steps(self):
        out = nc.recovery_commands(
            "get_gene_disease_assertion", "not_found", {"gene": "SKI", "disease": "MONDO:1"}, None
        )
        assert {c["tool"] for c in out} == {"get_gene_curations", "get_disease_curations"}

    def test_invalid_submitter_points_to_list(self):
        out = nc.recovery_commands("find_curations", "invalid_input", {}, "submitter")
        assert out == [{"tool": "list_submitters", "arguments": {}}]

    def test_invalid_classification_points_to_capabilities(self):
        out = nc.recovery_commands("find_curations", "invalid_input", {}, "classification")
        assert out[0]["tool"] == "get_server_capabilities"

    def test_data_unavailable(self):
        out = nc.recovery_commands("get_gene_curations", "data_unavailable", {}, None)
        assert out[0]["tool"] == "get_gencc_diagnostics"

    def test_unknown_returns_empty(self):
        assert nc.recovery_commands("list_submitters", "internal_error", {}, None) == []
```

Update existing `TestAfterSearchGenes.test_empty` / `TestAfterSearchDiseases.test_empty` to call with a query arg.

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Edit** `gencc_link/mcp/next_commands.py`:

```python
def after_search_genes(gene_curies: list[str], query: str = "") -> list[dict[str, Any]]:
    """After resolving genes: pull the gene's curations, or cross over to disease search."""
    if not gene_curies:
        return [cmd("search_diseases", query=query)] if query else []
    return [cmd("get_gene_curations", gene=gene_curies[0])]


def after_search_diseases(disease_curies: list[str], query: str = "") -> list[dict[str, Any]]:
    """After resolving diseases: pull the disease's curations, or cross over to gene search."""
    if not disease_curies:
        return [cmd("search_genes", query=query)] if query else []
    return [cmd("get_disease_curations", disease=disease_curies[0])]


def recovery_commands(
    tool: str, error_code: str, arguments: dict[str, Any], field: str | None
) -> list[dict[str, Any]]:
    """Ready-to-call recovery steps for an error envelope (empty when none apply)."""
    if error_code == "not_found":
        if tool == "get_gene_curations" and arguments.get("gene"):
            return [cmd("search_genes", query=arguments["gene"])]
        if tool == "get_disease_curations" and arguments.get("disease"):
            return [cmd("search_diseases", query=arguments["disease"])]
        if tool == "get_gene_disease_assertion":
            out = []
            if arguments.get("gene"):
                out.append(cmd("get_gene_curations", gene=arguments["gene"]))
            if arguments.get("disease"):
                out.append(cmd("get_disease_curations", disease=arguments["disease"]))
            return out
        if tool == "resolve_identifier" and arguments.get("query"):
            return [
                cmd("search_genes", query=arguments["query"]),
                cmd("search_diseases", query=arguments["query"]),
            ]
    if error_code == "invalid_input":
        if field == "submitter":
            return [cmd("list_submitters")]
        if field in ("classification", "moi"):
            return [cmd("get_server_capabilities")]
    if error_code == "data_unavailable":
        return [cmd("get_gencc_diagnostics")]
    return []
```

- [ ] **Step 4: Run** `uv run pytest tests/test_next_commands.py -q` → PASS.
- [ ] **Step 5: Commit** `feat(next_commands): propagate query on zero-result + error recovery map`.

---

## Task 7: Envelope — observability, mode-aware citation, error next_commands (M3, L2, Obs)

**Files:**
- Modify: `gencc_link/mcp/envelope.py`
- Test: `tests/test_envelope.py`

- [ ] **Step 1: Write failing tests** (append):

```python
class TestObservability:
    async def test_meta_has_request_id_and_timing(self) -> None:
        async def body(): return {}
        out = await run_mcp_tool("t", body)
        assert isinstance(out["_meta"]["request_id"], str) and len(out["_meta"]["request_id"]) >= 8
        assert isinstance(out["_meta"]["elapsed_ms"], (int, float))
        assert out["_meta"]["elapsed_ms"] >= 0

    async def test_error_meta_has_request_id(self) -> None:
        out = await run_mcp_tool("t", _raiser(NotFoundError("x")))
        assert "request_id" in out["_meta"] and "elapsed_ms" in out["_meta"]


class TestCitationByMode:
    async def test_compact_uses_citation_ref(self) -> None:
        async def body(): return {}
        out = await run_mcp_tool("t", body, response_mode="compact")
        assert out["_meta"]["citation_ref"] == "gencc://citation"
        assert "recommended_citation" not in out["_meta"]

    async def test_full_uses_full_citation(self) -> None:
        async def body(): return {}
        out = await run_mcp_tool("t", body, response_mode="full")
        assert out["_meta"]["recommended_citation"]
        assert "citation_ref" not in out["_meta"]

    async def test_no_mode_keeps_full_citation(self) -> None:
        async def body(): return {}
        out = await run_mcp_tool("t", body)
        assert out["_meta"]["recommended_citation"]


class TestErrorNextCommands:
    async def test_not_found_recovery(self) -> None:
        out = await run_mcp_tool(
            "get_gene_curations",
            _raiser(NotFoundError("nope")),
            context=McpErrorContext("get_gene_curations", arguments={"gene": "ZZZ"}),
        )
        assert out["_meta"]["next_commands"] == [
            {"tool": "search_genes", "arguments": {"query": "ZZZ"}}
        ]

    async def test_invalid_submitter_recovery(self) -> None:
        out = await run_mcp_tool(
            "find_curations",
            _raiser(InvalidInputError("bad", field="submitter")),
            context=McpErrorContext("find_curations", arguments={}),
        )
        assert out["_meta"]["next_commands"][0]["tool"] == "list_submitters"
```

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Edit** `gencc_link/mcp/envelope.py`:

Add imports:
```python
import time
import uuid
from dataclasses import dataclass, field
from gencc_link.mcp.next_commands import recovery_commands
```

`McpErrorContext`:
```python
@dataclass
class McpErrorContext:
    tool_name: str
    arguments: dict[str, Any] = field(default_factory=dict)
```

`_provenance_meta` becomes mode-aware:
```python
def _provenance_meta(response_mode: str | None = None) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "unsafe_for_clinical_use": True,
        "data_license": DATA_LICENSE,
    }
    if response_mode in ("minimal", "compact"):
        meta["citation_ref"] = "gencc://citation"
    else:
        meta["recommended_citation"] = RECOMMENDED_CITATION
    if response_mode:
        meta["response_mode"] = response_mode
    if _DATA_RELEASE:
        meta["gencc_release"] = _DATA_RELEASE
    return meta
```

`_error_envelope` gains observability + recovery (pass exc/field + a request_id/elapsed):
```python
def _error_envelope(
    exc: BaseException, context: McpErrorContext, *, request_id: str, elapsed_ms: float
) -> dict[str, Any]:
    error_code, message, retryable = _classify(exc)
    field_name = getattr(exc, "field", None)
    meta: dict[str, Any] = {"tool": context.tool_name, **_provenance_meta()}
    meta["request_id"] = request_id
    meta["elapsed_ms"] = elapsed_ms
    nexts = recovery_commands(context.tool_name, error_code, context.arguments, field_name)
    if nexts:
        meta["next_commands"] = nexts
    envelope: dict[str, Any] = {
        "success": False,
        "error_code": error_code,
        "message": message,
        "retryable": retryable,
        "recovery_action": _recovery_action(error_code, retryable),
        "_meta": meta,
    }
    field_errors = _field_errors(exc)
    if field_errors is not None:
        envelope["field_errors"] = field_errors
    return envelope
```

`run_mcp_tool` adds timing + request id + response_mode:
```python
async def run_mcp_tool(
    tool_name: str,
    call: Callable[[], Awaitable[dict[str, Any]]],
    *,
    context: McpErrorContext | None = None,
    response_mode: str | None = None,
) -> dict[str, Any]:
    ctx = context or McpErrorContext(tool_name=tool_name)
    request_id = uuid.uuid4().hex[:12]
    start = time.perf_counter()
    try:
        result = await call()
        elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
        if isinstance(result, dict):
            result.setdefault("success", True)
            existing_meta: dict[str, Any] = result.get("_meta") or {}
            result["_meta"] = {
                **existing_meta,
                **_provenance_meta(response_mode),
                "request_id": request_id,
                "elapsed_ms": elapsed_ms,
            }
        return result
    except Exception as exc:
        elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
        envelope = _error_envelope(exc, ctx, request_id=request_id, elapsed_ms=elapsed_ms)
        logger.warning(
            "mcp_tool_error tool=%s code=%s exc=%s",
            tool_name, envelope["error_code"], exc.__class__.__name__,
        )
        return envelope
```

Note: `_provenance_meta()` no longer references `_BASE_META`; keep or remove `_BASE_META` accordingly (remove to avoid dead code; `RECOMMENDED_CITATION` import stays).

- [ ] **Step 4: Run** `uv run pytest tests/test_envelope.py -q` → PASS.
- [ ] **Step 5: Commit** `feat(envelope): request_id/elapsed_ms, mode-aware citation_ref, error next_commands`.

---

## Task 8: Tools pass response_mode + arguments; propagate query (wiring)

**Files:**
- Modify: `gencc_link/mcp/tools/{genes,diseases,assertions}.py`
- Test: `tests/test_tools.py`

- [ ] **Step 1: Write failing tests** (append to `tests/test_tools.py`, using the `mcp`/client fixture pattern already in the file — call tools and inspect the returned dict):

```python
class TestEvalHardening:
    async def test_search_genes_zero_result_propagates_query(self, call_tool):
        out = await call_tool("search_genes", {"query": "ZZZXNOPE"})
        nxt = out["_meta"]["next_commands"]
        assert nxt == [] or nxt[0]["arguments"].get("query") == "ZZZXNOPE"

    async def test_find_curations_invalid_classification(self, call_tool):
        out = await call_tool("find_curations", {"classification": ["Pathogenic"]})
        assert out["success"] is False and out["error_code"] == "invalid_input"
        assert out["_meta"]["next_commands"][0]["tool"] == "get_server_capabilities"

    async def test_gene_curations_not_found_recovery(self, call_tool):
        out = await call_tool("get_gene_curations", {"gene": "NOTAGENE"})
        assert out["success"] is False and out["error_code"] == "not_found"
        assert out["_meta"]["next_commands"][0] == {
            "tool": "search_genes", "arguments": {"query": "NOTAGENE"}
        }

    async def test_compact_has_citation_ref(self, call_tool):
        out = await call_tool("get_gene_curations", {"gene": "SKI", "response_mode": "compact"})
        assert out["_meta"]["citation_ref"] == "gencc://citation"
```

(Match `call_tool` to the existing helper; if tests call via `Client(mcp)` and parse `result.data`, follow that.)

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Edit each tool** to pass `response_mode` to `run_mcp_tool`, set `context` arguments, and propagate query.

`genes.py` search_genes:
```python
            payload["_meta"] = {"next_commands": after_search_genes(curies, query)}
            return payload
        return await run_mcp_tool(
            "search_genes", call,
            context=McpErrorContext("search_genes", arguments={"query": query}),
            response_mode=response_mode,
        )
```
genes.py get_gene_curations:
```python
        return await run_mcp_tool(
            "get_gene_curations", call,
            context=McpErrorContext("get_gene_curations", arguments={"gene": gene}),
            response_mode=response_mode,
        )
```
Apply the analogous edits in `diseases.py` (search_diseases passes `after_search_diseases(curies, query)` + `arguments={"query": query}`; get_disease_curations `arguments={"disease": disease}`) and `assertions.py`:
- get_gene_disease_assertion: `McpErrorContext("get_gene_disease_assertion", arguments={"gene": gene, "disease": disease})`, `response_mode=response_mode`.
- find_curations: `McpErrorContext("find_curations", arguments={})`, `response_mode=response_mode`.
- resolve_identifier: `McpErrorContext("resolve_identifier", arguments={"query": query})` (no response_mode → full citation).

Import `McpErrorContext` is already present in each tool module.

- [ ] **Step 4: Run** `uv run pytest tests/test_tools.py -q` → PASS.
- [ ] **Step 5: Commit** `feat(tools): thread response_mode + error arguments, propagate search query`.

---

## Task 9: Capabilities — inheritance_modes, data_notes, conventions (L1, L3)

**Files:**
- Modify: `gencc_link/mcp/capabilities.py`
- Test: `tests/test_capabilities.py`

- [ ] **Step 1: Write failing tests** (append):

```python
class TestEvalAdditions:
    def test_inheritance_modes_data_derived(self):
        from gencc_link.mcp.capabilities import build_capabilities
        caps = build_capabilities()
        titles = {m["title"] for m in caps["inheritance_modes"]}
        assert {"Autosomal dominant", "Autosomal recessive"} <= titles

    def test_data_notes_present(self):
        from gencc_link.mcp.capabilities import build_capabilities
        caps = build_capabilities()
        assert any("assertion_criteria_url" in n for n in caps["data_notes"])

    def test_capabilities_version_stable_vs_data(self):
        # data-derived additions live outside the hashed static surface
        from gencc_link.mcp.capabilities import capabilities_version, build_capabilities
        assert build_capabilities()["capabilities_version"] == capabilities_version()
```

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Edit** `build_capabilities()` to add live, data-derived fields (outside `_static_surface`):

```python
def build_capabilities() -> dict[str, Any]:
    surface = dict(_static_surface())
    surface["data"] = _data_status()
    surface["inheritance_modes"] = _inheritance_modes()
    surface["data_notes"] = [
        "Some submitter fields pass through verbatim: assertion_criteria_url may "
        "hold non-URL text (e.g. 'PMID: 28106320'); submitted_as_date mixes formats "
        "(e.g. '2018-03-30 13:31:56' vs ISO 8601).",
        "The structured pmids array is normalised and may correct malformed PMIDs "
        "in the raw notes text.",
        "find_curations classification/submitter/moi match at the submission level "
        "(any submitter), not the consensus; see each row's `matched` field.",
    ]
    return surface


def _inheritance_modes() -> list[dict[str, Any]]:
    try:
        from gencc_link.mcp.service_adapters import get_gencc_service

        repo = get_gencc_service()._repo  # read-only access for vocabulary
        return [{"title": t, "curie": c} for t, c in repo.distinct_moi()]
    except Exception:
        return []
```

Also extend `parameter_conventions` (static surface) with an `moi` key and `response_fields` with `matched`/`citation_ref`/`request_id`:
```python
        "parameter_conventions": {
            ...,
            "moi": "mode-of-inheritance title; data-derived (see inheritance_modes)",
        },
        ...
        "response_fields": {
            ...,
            "matched": "find_curations: the submission(s) that satisfied a submission-level filter",
            "citation_ref": "_meta.citation_ref: gencc://citation in minimal/compact (full string in standard/full)",
            "request_id": "_meta.request_id + _meta.elapsed_ms: per-call trace id and server timing",
        },
```

Note: adding to the static surface changes `capabilities_version` (expected — the contract changed). `inheritance_modes`/`data_notes` are live-only, so `test_capabilities_version_stable_vs_data` holds.

- [ ] **Step 4: Run** `uv run pytest tests/test_capabilities.py -q` → PASS.
- [ ] **Step 5: Commit** `feat(capabilities): inheritance_modes, data_notes, moi convention, response fields`.

---

## Task 10: Reference resource notes (L3, M1 docs)

**Files:**
- Modify: `gencc_link/mcp/resources.py`
- Test: covered by capabilities/usage; add a thin assertion if a resource test exists.

- [ ] **Step 1:** Append to `GENCC_REFERENCE_NOTES`:
```
"find_curations classification/submitter/moi match at submission level (any "
"submitter), not consensus; the matched field on each row names the triggering "
"submission. Some passthrough fields are verbatim: assertion_criteria_url may be "
"non-URL; submitted_as_date mixes formats; structured pmids are normalised."
```
- [ ] **Step 2:** Update the `find_curations` tool description in `assertions.py` to add: "Filters match at the submission level (any submitter), not the consensus; each row's `matched` field names the triggering submission. Out-of-vocabulary values return invalid_input with the accepted set."
- [ ] **Step 3: Run** `uv run pytest tests/test_capabilities.py tests/test_tools.py -q` → PASS.
- [ ] **Step 4: Commit** `docs(resources): document submission-level filter semantics + passthrough quirks`.

---

## Task 11: Downloader quota counter + status (Obs)

**Files:**
- Modify: `gencc_link/ingest/downloader.py`
- Test: `tests/test_downloader.py`

- [ ] **Step 1: Write failing tests** (append; reuse the existing respx + tmp config fixtures in the file):

```python
class TestQuotaCounter:
    def test_status_zero_when_no_cache(self, data_config):
        from gencc_link.ingest.downloader import download_quota_status
        st = download_quota_status(data_config)
        assert st["used_today"] == 0 and st["daily_quota"] == 20 and st["remaining"] == 20

    def test_increment_on_real_download(self, data_config, respx_mock):
        # arrange a 200 export response like the existing download test does, then:
        from gencc_link.ingest.downloader import download_export, download_quota_status
        download_export(data_config)
        assert download_quota_status(data_config)["used_today"] == 1

    def test_304_does_not_increment(self, data_config, respx_mock):
        from gencc_link.ingest.downloader import download_export, download_quota_status
        # arrange a 304 response; then:
        download_export(data_config)
        assert download_quota_status(data_config)["used_today"] == 0
```

(Mirror the existing download tests' respx setup for 200/304; reuse their config fixture name.)

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** in `downloader.py`:

```python
from datetime import datetime, timezone

def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _bump_download_count(config: GenCCDataConfigModel) -> None:
    cache_path = _cache_path(config)
    data: dict[str, object] = {}
    if cache_path.exists():
        try:
            loaded = json.loads(cache_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
        except (json.JSONDecodeError, OSError):
            data = {}
    rec = data.get("downloads")
    today = _today_utc()
    if not isinstance(rec, dict) or rec.get("date") != today:
        rec = {"date": today, "count": 0}
    rec["count"] = int(rec.get("count", 0)) + 1
    data["downloads"] = rec
    cache_path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def download_quota_status(config: GenCCDataConfigModel) -> dict[str, object]:
    """Return today's download usage against the per-IP daily quota."""
    cache_path = _cache_path(config)
    used = 0
    today = _today_utc()
    if cache_path.exists():
        try:
            data = json.loads(cache_path.read_text(encoding="utf-8"))
            rec = data.get("downloads") if isinstance(data, dict) else None
            if isinstance(rec, dict) and rec.get("date") == today:
                used = int(rec.get("count", 0))
        except (json.JSONDecodeError, OSError, TypeError, ValueError):
            used = 0
    return {
        "date": today,
        "used_today": used,
        "daily_quota": DOWNLOAD_DAILY_QUOTA,
        "remaining": max(0, DOWNLOAD_DAILY_QUOTA - used),
    }
```

Import `DOWNLOAD_DAILY_QUOTA` from constants. In `download_export`, after a successful real (200, body written, not `not_modified`) response, call `_bump_download_count(config)`. Do **not** bump on `304`/HEAD.

- [ ] **Step 4: Run** `uv run pytest tests/test_downloader.py -q` → PASS.
- [ ] **Step 5: Commit** `feat(downloader): track daily download usage against the GenCC quota`.

---

## Task 12: Diagnostics surfaces quota (Obs)

**Files:**
- Modify: `gencc_link/mcp/tools/discovery.py`
- Test: `tests/test_tools.py`

- [ ] **Step 1: Write failing test** (append to `tests/test_tools.py`):
```python
    async def test_diagnostics_has_quota_block(self, call_tool):
        out = await call_tool("get_gencc_diagnostics", {})
        assert "quota" in out
        assert out["quota"]["daily_quota"] == 20
        assert "remaining" in out["quota"]
```
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Edit** `get_gencc_diagnostics` body to add a best-effort quota block:
```python
            quota: dict[str, Any] | None = None
            try:
                from gencc_link.ingest.downloader import download_quota_status
                quota = download_quota_status(cfg)
            except Exception:
                quota = None
            result = {
                "headline": (...unchanged...),
                "data": meta.model_dump(),
                "refresh": refresh,
            }
            if quota is not None:
                result["quota"] = quota
            return result
```
- [ ] **Step 4: Run** `uv run pytest tests/test_tools.py -q` → PASS.
- [ ] **Step 5: Commit** `feat(diagnostics): surface daily download-quota headroom`.

---

## Task 13: Docs + evaluation annotation

**Files:**
- Modify: `README.md`, `docs/usage.md`, `docs/MCP_CONNECTION_GUIDE.md`, `docs/mcp-evaluation.md`

- [ ] **Step 1:** In `docs/usage.md` and `docs/MCP_CONNECTION_GUIDE.md`, where the response envelope and find_curations are described, add: new `_meta` fields (`request_id`, `elapsed_ms`, `citation_ref` in minimal/compact), `matched` on find_curations rows, enum validation for `classification`/`submitter`/`moi`, and the diagnostics `quota` block.
- [ ] **Step 2:** In `README.md`, update any response-shape/feature blurb to mention validated enum filters, error `next_commands`, and observability fields.
- [ ] **Step 3:** Append a short "## Resolution (2026-06-12)" note to `docs/mcp-evaluation.md` mapping each finding (H1/M1/M2/M3/L1/L2/L3 + scorecard) to "addressed", pointing to `docs/superpowers/specs/2026-06-12-mcp-evaluation-hardening-design.md`.
- [ ] **Step 4: Commit** `docs: document evaluation hardening (validated filters, matched, observability)`.

---

## Task 14: Full gate

- [ ] **Step 1:** Run `make ci-local`.
- [ ] **Step 2:** Fix any format/lint/lint-loc/typecheck/coverage failures (use `make lint-fix`, `make format`; keep modules ≤600 lines).
- [ ] **Step 3:** Re-run `make ci-local` → all green.
- [ ] **Step 4: Commit** any fixups; final `chore: ci-local green for MCP evaluation hardening`.

---

## Self-Review (coverage vs spec)

- H1 → Tasks 1,3 (validate, canonicalise, case-insensitive).
- M1 → Tasks 2,3,10 (matched map, attach, document).
- M2 → Task 6 (query propagation).
- M3 → Tasks 6,7,8 (recovery map, error next_commands, tool arguments).
- L1 → Task 9 (inheritance_modes).
- L2 → Tasks 4,5,7 (omit parent id; citation_ref).
- L3 → Tasks 9,10 (data_notes, reference notes).
- Obs (request_id/elapsed_ms) → Task 7. Obs (quota) → Tasks 11,12.
- Docs → Task 13. Gate → Task 14.

No placeholders; types consistent (`find_assertions` 3-tuple defined Task 2, consumed Task 3; `recovery_commands` defined Task 6, consumed Task 7; `download_quota_status` defined Task 11, consumed Task 12).
