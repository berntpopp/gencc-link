# GenCC-Link MCP Consumer Uplift Implementation Plan

> Historical record — this document records the design or plan as of its date. Current behavior is
> defined by implemented code, standards, release evidence, and tests.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close every finding in `docs/mcp-consumer-assessment.md` (F1–F7 + the `ambiguous_query` coverage gap) to lift the consumer-facing MCP quality from 9/10 to >9.5/10.

**Architecture:** Presentational + discovery-surface changes at the MCP/service/shaping boundary, plus one new `outputSchema` module. No SQLite schema change and no DB rebuild — the `consensus_classification` rename is translated in the existing `assertion_from_row` mapping layer (DB column stays). TDD throughout; the sample database is built once per session from `tests/fixtures/sample.tsv`.

**Tech Stack:** Python 3.12, FastMCP 3.4.2 (`mcp` 1.27), Pydantic v2, SQLite/FTS5, pytest (`pytest.mark.mcp` async), Ruff (100 cols), mypy strict.

**Spec:** `docs/superpowers/specs/2026-06-12-mcp-consumer-uplift-design.md`

**Conventions for every task:** run focused tests with `uv run pytest <path> -q`. The MCP/tool tests are async and live in `tests/test_tools.py` (marked `mcp`). Keep modules <600 LOC (`make lint-loc`). Commit messages use Conventional Commits and end with the repo's `Co-Authored-By` trailer.

---

### Task 1: F3 — rename `consensus_classification` → `strongest_classification`

**Files:**
- Modify: `gencc_link/models/records.py` (GeneDiseaseAssertion field)
- Modify: `gencc_link/data/queries.py` (assertion_from_row mapping)
- Modify: `gencc_link/services/shaping.py` (assertion_headline, assertion_dict)
- Modify: `gencc_link/mcp/resources.py` (reference notes + server instructions prose)
- Modify: `gencc_link/mcp/capabilities.py` (response_fields glossary)
- Test: `tests/test_shaping.py`, `tests/test_service.py`, `tests/test_repository.py`

- [ ] **Step 1: Update the failing tests first (rename the consumer-facing field).**

In `tests/test_shaping.py`, change the model constructor kwarg and assertions:
- `_assertion(...)`: `consensus_classification="Definitive",` → `strongest_classification="Definitive",`
- `test_minimal_omits_min_classification`: `out["consensus_classification"]` → `out["strongest_classification"]`
- `TestOmitParentId.test_omit_gene_minimal`: `assert out["consensus_classification"]` → `assert out["strongest_classification"]`

In `tests/test_service.py` (around line 108): `out["assertion"]["consensus_classification"]` → `out["assertion"]["strongest_classification"]`.

In `tests/test_repository.py` (around line 140): `a.consensus_classification` → `a.strongest_classification`.

- [ ] **Step 2: Run the tests to verify they fail.**

Run: `uv run pytest tests/test_shaping.py tests/test_service.py tests/test_repository.py -q`
Expected: FAIL — `GeneDiseaseAssertion` has no field `strongest_classification` / KeyError on `strongest_classification`.

- [ ] **Step 3: Rename the model field.**

In `gencc_link/models/records.py`, replace the `consensus_classification` field of `GeneDiseaseAssertion` with:

```python
    strongest_classification: str | None = Field(
        default=None,
        description=(
            "Strongest (highest-rank) classification asserted by any submitter; "
            "NOT an agreement measure -- read has_conflict and min_classification "
            "for disagreement and the classification range."
        ),
    )
```

(Keep `consensus_rank` below it unchanged — it is internal and never serialized.)

- [ ] **Step 4: Update the row mapping (DB column stays `consensus_classification`).**

In `gencc_link/data/queries.py::assertion_from_row`, change the line
`consensus_classification=row["consensus_classification"],` to:

```python
        # DB column `consensus_classification` holds the strongest (max-rank)
        # title; surfaced to consumers as `strongest_classification`.
        strongest_classification=row["consensus_classification"],
```

- [ ] **Step 5: Update shaping (headline + dict).**

In `gencc_link/services/shaping.py::assertion_headline`, replace the body's
classification references:

```python
def assertion_headline(a: GeneDiseaseAssertion) -> str:
    """One-line summary for a gene-disease assertion."""
    label = a.disease_title or a.disease_curie
    strongest = a.strongest_classification or "no classification"
    conflict = " — CONFLICT" if a.has_conflict else ""
    spread = ""
    if a.min_classification and a.min_classification != a.strongest_classification:
        spread = f" (range {a.strongest_classification}..{a.min_classification})"
    return (
        f"{a.gene_symbol} - {label}: {strongest} from {a.n_submitters} "
        f"submitter(s){spread}{conflict}."
    )
```

In `assertion_dict`, change `out["consensus_classification"] = a.consensus_classification` to:

```python
    out["strongest_classification"] = a.strongest_classification
```

- [ ] **Step 6: Update the discovery text (reference note + server instructions).**

In `gencc_link/mcp/resources.py`:
- In `GENCC_REFERENCE_NOTES`, change
  `". consensus_classification is the strongest assertion across submitters; "`
  to `". strongest_classification is the highest-rank assertion across submitters "
  "(not an agreement measure); "`.
- In `GENCC_SERVER_INSTRUCTIONS`, change `"(all diseases for a gene, with "
  "consensus)"` to `"(all diseases for a gene, with the strongest classification "
  "and a conflict flag)"`, and change `"Each gene-disease pair carries a consensus "
  "classification and a has_conflict flag"` to `"Each gene-disease pair carries a "
  "strongest_classification and a has_conflict flag"`.

- [ ] **Step 7: Document the field + aggregation in capabilities.**

In `gencc_link/mcp/capabilities.py`, add to the `response_fields` dict (after
`"has_conflict"`):

```python
            "strongest_classification": "gene-disease pairs: the highest-rank "
            "classification asserted by any submitter (e.g. Definitive). NOT a "
            "consensus/agreement measure -- a pair can be Definitive yet conflicted; "
            "read has_conflict and min_classification for the spread.",
```

- [ ] **Step 8: Run the tests to verify they pass.**

Run: `uv run pytest tests/test_shaping.py tests/test_service.py tests/test_repository.py tests/test_consensus.py tests/test_ingest.py -q`
Expected: PASS. (`test_consensus.py`/`test_ingest.py` keep the internal/DB name and must stay green.)

- [ ] **Step 9: Grep gate — no consumer-facing leftover.**

Run: `grep -rn "consensus_classification" gencc_link/models/records.py gencc_link/services/shaping.py`
Expected: no output. (Hits remain only in `data/queries.py` as the DB column, `data/schema.sql`, `ingest/aggregates.py`, and `services/consensus.py` — all internal.)

- [ ] **Step 10: Commit.**

```bash
git add gencc_link/models/records.py gencc_link/data/queries.py gencc_link/services/shaping.py gencc_link/mcp/resources.py gencc_link/mcp/capabilities.py tests/test_shaping.py tests/test_service.py tests/test_repository.py
git commit -m "refactor(api)!: rename consensus_classification -> strongest_classification

The field is the max-rank assertion, not an agreement measure (assessment F3).
DB column unchanged; renamed at the model/mapping/shaping boundary."
```

---

### Task 2: F6 — minimal-mode field/headline parity (keep `n_submitters`)

**Files:**
- Modify: `gencc_link/services/shaping.py` (gene_summary_dict, disease_summary_dict)
- Test: `tests/test_shaping.py`

- [ ] **Step 1: Update the minimal-mode tests.**

In `tests/test_shaping.py::TestSummaryDicts`:
- `test_gene_minimal_omits_counts` → rename body to assert `n_submitters` present, `n_submissions` absent:

```python
    def test_gene_minimal_keeps_submitters_omits_submissions(self) -> None:
        out = shaping.gene_summary_dict(self._gene(), "minimal")
        assert "n_submissions" not in out
        assert out["n_submitters"] == 3
        assert out["gene_symbol"] == "SKI"
```

- `test_disease_minimal_omits_counts` → likewise:

```python
    def test_disease_minimal_keeps_submitters_omits_submissions(self) -> None:
        out = shaping.disease_summary_dict(self._disease(), "minimal")
        assert "n_submissions" not in out
        assert out["n_submitters"] == 3
        assert out["disease_title"] == "Shprintzen-Goldberg syndrome"
```

- [ ] **Step 2: Run to verify failure.**

Run: `uv run pytest tests/test_shaping.py -k minimal -q`
Expected: FAIL — `n_submitters` not in minimal output.

- [ ] **Step 3: Implement parity in shaping.**

In `gencc_link/services/shaping.py::gene_summary_dict`:

```python
def gene_summary_dict(gene: GeneSummary, mode: ResponseMode) -> dict[str, Any]:
    """Shape a gene summary per response_mode."""
    out = {
        "gene_curie": gene.gene_curie,
        "gene_symbol": gene.gene_symbol,
        "n_diseases": gene.n_diseases,
        "n_submitters": gene.n_submitters,
        "max_classification": gene.max_classification,
        "has_conflict": gene.has_conflict,
    }
    if mode != "minimal":
        out["n_submissions"] = gene.n_submissions
    return out
```

In `disease_summary_dict`:

```python
def disease_summary_dict(disease: DiseaseSummary, mode: ResponseMode) -> dict[str, Any]:
    """Shape a disease summary per response_mode."""
    out = {
        "disease_curie": disease.disease_curie,
        "disease_title": disease.disease_title,
        "n_genes": disease.n_genes,
        "n_submitters": disease.n_submitters,
        "max_classification": disease.max_classification,
    }
    if mode != "minimal":
        out["n_submissions"] = disease.n_submissions
    return out
```

- [ ] **Step 4: Run to verify pass.**

Run: `uv run pytest tests/test_shaping.py -q`
Expected: PASS.

- [ ] **Step 5: Commit.**

```bash
git add gencc_link/services/shaping.py tests/test_shaping.py
git commit -m "fix(shaping): keep n_submitters in minimal mode so headline matches (F6)"
```

---

### Task 3: F1 — set-aware multi-result headlines

**Files:**
- Modify: `gencc_link/services/shaping.py` (new headline builders)
- Modify: `gencc_link/services/gencc_service.py` (search_genes, search_diseases)
- Test: `tests/test_shaping.py`, `tests/test_tools.py`

- [ ] **Step 1: Write failing unit tests for the builders.**

Add to `tests/test_shaping.py` (a new `TestSearchHeadlines` class):

```python
class TestSearchHeadlines:
    def _gene(self, symbol: str) -> GeneSummary:
        return GeneSummary(
            gene_curie=f"HGNC:{symbol}", gene_symbol=symbol, n_submissions=1,
            n_diseases=1, n_submitters=1, max_classification="Definitive",
        )

    def _disease(self, curie: str, title: str | None) -> DiseaseSummary:
        return DiseaseSummary(
            disease_curie=curie, disease_title=title, n_submissions=1,
            n_genes=1, n_submitters=1, max_classification="Definitive",
        )

    def test_single_total_one_uses_rich_headline(self) -> None:
        head = shaping.genes_search_headline("SKI", [self._gene("SKI")], total=1)
        assert head == shaping.gene_headline(self._gene("SKI"))

    def test_two_hits_names_all(self) -> None:
        hits = [self._gene("COL1A1"), self._gene("COL2A1")]
        head = shaping.genes_search_headline("COL", hits, total=2)
        assert "2 genes match 'COL'" in head
        assert "COL1A1" in head and "COL2A1" in head

    def test_sliced_shows_of_total(self) -> None:
        hits = [self._disease("MONDO:1", "Marfan syndrome"),
                self._disease("MONDO:2", "Stickler syndrome"),
                self._disease("MONDO:3", "long QT syndrome 1")]
        head = shaping.diseases_search_headline("syndrome", hits, total=1920)
        assert "3 of 1920 diseases match 'syndrome'" in head
        assert "Marfan syndrome" in head

    def test_caps_names_at_five(self) -> None:
        hits = [self._gene(f"G{i}") for i in range(7)]
        head = shaping.genes_search_headline("G", hits, total=7)
        assert "+2 more" in head
        assert head.count(",") >= 4  # 5 names listed

    def test_disease_falls_back_to_curie(self) -> None:
        hits = [self._disease("MONDO:1", None), self._disease("MONDO:2", None)]
        head = shaping.diseases_search_headline("x", hits, total=2)
        assert "MONDO:1" in head and "MONDO:2" in head
```

- [ ] **Step 2: Run to verify failure.**

Run: `uv run pytest tests/test_shaping.py::TestSearchHeadlines -q`
Expected: FAIL — `shaping` has no `genes_search_headline`/`diseases_search_headline`.

- [ ] **Step 3: Implement the builders in shaping.py.**

Add to `gencc_link/services/shaping.py` (after `disease_headline`):

```python
_MAX_HEADLINE_NAMES = 5


def _search_headline(query: str, names: list[str], returned: int, total: int, noun: str) -> str:
    """Set-aware headline: '<scope> match '<query>': name1, name2, …, +N more.'"""
    plural = f"{noun}s" if total != 1 else noun
    scope = f"{returned} of {total} {plural}" if total > returned else f"{total} {plural}"
    shown = ", ".join(names[:_MAX_HEADLINE_NAMES])
    extra = len(names) - _MAX_HEADLINE_NAMES
    more = f", +{extra} more" if extra > 0 else ""
    return f"{scope} match '{query}': {shown}{more}."


def genes_search_headline(query: str, hits: list[GeneSummary], total: int) -> str:
    """Headline for a gene search: rich single line for one exact hit, else set summary."""
    if len(hits) == 1 and total == 1:
        return gene_headline(hits[0])
    return _search_headline(query, [g.gene_symbol for g in hits], len(hits), total, "gene")


def diseases_search_headline(query: str, hits: list[DiseaseSummary], total: int) -> str:
    """Headline for a disease search: rich single line for one exact hit, else set summary."""
    if len(hits) == 1 and total == 1:
        return disease_headline(hits[0])
    names = [d.disease_title or d.disease_curie for d in hits]
    return _search_headline(query, names, len(hits), total, "disease")
```

- [ ] **Step 4: Run unit tests to verify pass.**

Run: `uv run pytest tests/test_shaping.py::TestSearchHeadlines -q`
Expected: PASS.

- [ ] **Step 5: Wire into the service.**

In `gencc_link/services/gencc_service.py::search_genes`, replace
`payload["headline"] = shaping.gene_headline(hits[0])` with:

```python
        if hits:
            payload["headline"] = shaping.genes_search_headline(query.strip(), hits, total)
```

In `search_diseases`, replace `payload["headline"] = shaping.disease_headline(hits[0])` with:

```python
        if hits:
            payload["headline"] = shaping.diseases_search_headline(query.strip(), hits, total)
```

- [ ] **Step 6: Add a tool-level test (real fixture multi-hit).**

Add to `tests/test_tools.py` (inside `class TestEvalHardening` or a new class):

```python
    async def test_search_genes_multi_headline_names_all(self, mcp_client) -> None:
        result = await mcp_client.call_tool("search_genes", {"query": "COL"})
        data = result.structured_content
        symbols = {g["gene_symbol"] for g in data["genes"]}
        assert {"COL1A1", "COL2A1"} <= symbols
        for sym in symbols:  # fixture page is <=5 hits, so every symbol is named
            assert sym in data["headline"]
```

- [ ] **Step 7: Run tool tests to verify pass.**

Run: `uv run pytest tests/test_tools.py -k "search_genes or search_diseases" -q`
Expected: PASS.

- [ ] **Step 8: Commit.**

```bash
git add gencc_link/services/shaping.py gencc_link/services/gencc_service.py tests/test_shaping.py tests/test_tools.py
git commit -m "fix(search): set-aware multi-result headlines (F1)"
```

---

### Task 4: F2 — `next_commands` fan-out across resolved entities

**Files:**
- Modify: `gencc_link/mcp/next_commands.py` (after_search_genes/diseases, after_genes/diseases_curations, cap constant)
- Test: `tests/test_next_commands.py`, `tests/test_tools.py`

- [ ] **Step 1: Read the existing next_commands tests to know what to update.**

Run: `uv run python -c "print(open('tests/test_next_commands.py').read())"`
Note which assertions cover `after_search_genes` and `after_genes_curations`; they will be updated in Step 2.

- [ ] **Step 2: Write/replace failing tests for fan-out + cap.**

Add (or replace existing single-item assertions) in `tests/test_next_commands.py`:

```python
from gencc_link.mcp import next_commands as nc


def test_after_search_genes_fans_out_capped() -> None:
    curies = [f"HGNC:{i}" for i in range(8)]
    cmds = nc.after_search_genes(curies, "x")
    assert [c["tool"] for c in cmds] == ["get_gene_curations"] * nc._MAX_NEXT_COMMANDS
    assert cmds[0]["arguments"]["gene"] == "HGNC:0"


def test_after_search_genes_zero_hits_crosses_over() -> None:
    assert nc.after_search_genes([], "marfan") == [{"tool": "search_diseases", "arguments": {"query": "marfan"}}]


def test_after_genes_curations_drilldown_plus_unresolved() -> None:
    payload = {
        "results": [
            {"gene": {"gene_curie": "HGNC:1"}, "diseases": [{"disease_curie": "MONDO:1"}]},
            {"gene": {"gene_curie": "HGNC:2"}, "diseases": [{"disease_curie": "MONDO:2"}]},
        ],
        "unresolved": [{"input": "NOTAGENE", "reason": "not_found"}],
    }
    cmds = nc.after_genes_curations(payload)
    tools = [c["tool"] for c in cmds]
    assert tools.count("get_gene_disease_assertion") == 2
    assert {"tool": "search_genes", "arguments": {"query": "NOTAGENE"}} in cmds
    assert len(cmds) <= nc._MAX_NEXT_COMMANDS
```

- [ ] **Step 3: Run to verify failure.**

Run: `uv run pytest tests/test_next_commands.py -q`
Expected: FAIL — `_MAX_NEXT_COMMANDS` missing / single-item behavior.

- [ ] **Step 4: Implement fan-out in next_commands.py.**

At the top of `gencc_link/mcp/next_commands.py` (after the `cmd` helper) add:

```python
_MAX_NEXT_COMMANDS = 5
```

Replace `after_search_genes` and `after_search_diseases`:

```python
def after_search_genes(gene_curies: list[str], query: str = "") -> list[dict[str, Any]]:
    """After resolving genes: pull each gene's curations (capped), or cross to disease search."""
    if not gene_curies:
        return [cmd("search_diseases", query=query)] if query else []
    return [cmd("get_gene_curations", gene=c) for c in gene_curies[:_MAX_NEXT_COMMANDS]]


def after_search_diseases(disease_curies: list[str], query: str = "") -> list[dict[str, Any]]:
    """After resolving diseases: pull each disease's curations (capped), or cross to gene search."""
    if not disease_curies:
        return [cmd("search_genes", query=query)] if query else []
    return [cmd("get_disease_curations", disease=c) for c in disease_curies[:_MAX_NEXT_COMMANDS]]
```

Replace `after_genes_curations` and `after_diseases_curations`:

```python
def after_genes_curations(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Drill into each resolved gene's top disease (capped); append unresolved recovery."""
    unresolved = payload.get("unresolved") or []
    cap = _MAX_NEXT_COMMANDS - 1 if unresolved else _MAX_NEXT_COMMANDS
    nexts: list[dict[str, Any]] = []
    for block in payload.get("results") or []:
        gene = block.get("gene") or {}
        diseases = block.get("diseases") or []
        if gene.get("gene_curie") and diseases:
            nexts.append(
                cmd(
                    "get_gene_disease_assertion",
                    gene=gene["gene_curie"],
                    disease=diseases[0]["disease_curie"],
                )
            )
        if len(nexts) >= cap:
            break
    if unresolved:
        nexts.append(cmd("search_genes", query=unresolved[0]["input"]))
    return nexts


def after_diseases_curations(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Drill into each resolved disease's top gene (capped); append unresolved recovery."""
    unresolved = payload.get("unresolved") or []
    cap = _MAX_NEXT_COMMANDS - 1 if unresolved else _MAX_NEXT_COMMANDS
    nexts: list[dict[str, Any]] = []
    for block in payload.get("results") or []:
        disease = block.get("disease") or {}
        genes = block.get("genes") or []
        if disease.get("disease_curie") and genes:
            nexts.append(
                cmd(
                    "get_gene_disease_assertion",
                    gene=genes[0]["gene_curie"],
                    disease=disease["disease_curie"],
                )
            )
        if len(nexts) >= cap:
            break
    if unresolved:
        nexts.append(cmd("search_diseases", query=unresolved[0]["input"]))
    return nexts
```

- [ ] **Step 5: Update the affected tool-level test.**

In `tests/test_tools.py::TestBatchTools::test_genes_curations_partial_next_command`, replace the
`next_commands[0] == search_genes(...)` assertion with a presence check:

```python
    async def test_genes_curations_partial_next_command(self, mcp_client) -> None:
        result = await mcp_client.call_tool("get_genes_curations", {"genes": ["SKI", "NOTAGENE"]})
        data = result.structured_content
        assert data["success"] is True
        assert data["unresolved"][0]["input"] == "NOTAGENE"
        cmds = data["_meta"]["next_commands"]
        # resolved gene drills down; unresolved input still offered (as an addition)
        assert any(c["tool"] == "get_gene_disease_assertion" for c in cmds)
        assert {"tool": "search_genes", "arguments": {"query": "NOTAGENE"}} in cmds
```

- [ ] **Step 6: Run tests to verify pass.**

Run: `uv run pytest tests/test_next_commands.py tests/test_tools.py -q`
Expected: PASS.

- [ ] **Step 7: Commit.**

```bash
git add gencc_link/mcp/next_commands.py tests/test_next_commands.py tests/test_tools.py
git commit -m "fix(next_commands): fan out across resolved entities on search/batch (F2)"
```

---

### Task 5: F5 — normalized ISO date field

**Files:**
- Modify: `gencc_link/services/shaping.py` (normalize helper, _submitter_dict, submission_dict)
- Modify: `gencc_link/mcp/capabilities.py` (data_notes + response_fields)
- Modify: `gencc_link/mcp/resources.py` (reference note)
- Test: `tests/test_shaping.py`, `tests/test_tools.py`

- [ ] **Step 1: Write failing unit tests for the normalizer + emission.**

Add to `tests/test_shaping.py`:

```python
class TestDateNormalization:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("2017-08-29 00:00:00", "2017-08-29"),
            ("2024-08-29T00:00:00.000000Z", "2024-08-29"),
            ("2018-03-30 13:31:56", "2018-03-30"),
            ("2019-04-01", "2019-04-01"),
            (None, None),
            ("not a date", None),
        ],
    )
    def test_normalize_submitted_date(self, raw, expected) -> None:
        assert shaping.normalize_submitted_date(raw) == expected

    def test_submitter_dict_standard_adds_iso(self) -> None:
        out = shaping._submitter_dict(
            {"submitter_title": "Ambry Genetics", "classification_title": "Definitive",
             "moi_title": "AD", "submitted_as_date": "2017-08-29 00:00:00",
             "public_report_url": None},
            "standard",
        )
        assert out["submitted_as_date"] == "2017-08-29 00:00:00"
        assert out["submitted_as_date_iso"] == "2017-08-29"
```

- [ ] **Step 2: Run to verify failure.**

Run: `uv run pytest tests/test_shaping.py::TestDateNormalization -q`
Expected: FAIL — `normalize_submitted_date` not defined / no `submitted_as_date_iso`.

- [ ] **Step 3: Implement the normalizer and emit the field.**

In `gencc_link/services/shaping.py`, add imports at the top (`import re`) and a helper:

```python
_ISO_DATE = re.compile(r"^\s*(\d{4})-(\d{2})-(\d{2})")


def normalize_submitted_date(raw: str | None) -> str | None:
    """Normalize a verbatim submitter date to an ISO-8601 date (YYYY-MM-DD).

    GenCC passes dates through verbatim, mixing '2017-08-29 00:00:00' and ISO-8601
    '2024-08-29T00:00:00.000000Z'. The reliably-present, comparable granularity is
    the calendar date; returns None when no leading date can be parsed.
    """
    if not raw:
        return None
    match = _ISO_DATE.match(raw)
    if not match:
        return None
    year, month, day = (int(p) for p in match.groups())
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return None
    return f"{year:04d}-{month:02d}-{day:02d}"
```

In `_submitter_dict`, inside the `if mode in ("standard", "full")` block, after the
`submitted_as_date` line add:

```python
        base["submitted_as_date_iso"] = normalize_submitted_date(data.get("submitted_as_date"))
```

In `submission_dict`, after the `"submitted_as_date": s.submitted_as_date,` line add:

```python
        "submitted_as_date_iso": normalize_submitted_date(s.submitted_as_date),
```

- [ ] **Step 4: Run unit tests to verify pass.**

Run: `uv run pytest tests/test_shaping.py::TestDateNormalization -q`
Expected: PASS.

- [ ] **Step 5: Update discovery text.**

In `gencc_link/mcp/capabilities.py`:
- In `response_fields`, add:

```python
            "submitted_as_date_iso": "per-submitter/submission: submitted_as_date "
            "normalized to an ISO-8601 date (YYYY-MM-DD); the verbatim "
            "submitted_as_date is retained alongside it (standard/full).",
```

- In `build_capabilities`'s `data_notes`, change the first note's trailing text to
  mention the normalized field, i.e. append to that note string:
  `" A normalized submitted_as_date_iso (YYYY-MM-DD) is emitted alongside the "
  "verbatim value in standard/full."`

In `gencc_link/mcp/resources.py` `GENCC_REFERENCE_NOTES`, change
`"submitted_as_date mixes formats; the pmids array is normalised."` to
`"submitted_as_date mixes formats (a normalized submitted_as_date_iso is added in "
"standard/full); the pmids array is normalised."`

- [ ] **Step 6: Add a tool-level assertion.**

Add to `tests/test_tools.py`:

```python
    async def test_assertion_full_has_iso_date(self, mcp_client) -> None:
        result = await mcp_client.call_tool(
            "get_gene_disease_assertion",
            {"gene": "GLA", "disease": "MONDO:0010526", "response_mode": "full"},
        )
        data = result.structured_content
        subs = data["assertion"]["submitters"]
        assert any("submitted_as_date_iso" in s for s in subs)
```

- [ ] **Step 7: Run tests to verify pass.**

Run: `uv run pytest tests/test_shaping.py tests/test_tools.py -k "date or iso or assertion_full" -q`
Expected: PASS.

- [ ] **Step 8: Commit.**

```bash
git add gencc_link/services/shaping.py gencc_link/mcp/capabilities.py gencc_link/mcp/resources.py tests/test_shaping.py tests/test_tools.py
git commit -m "feat(shaping): normalized submitted_as_date_iso alongside verbatim date (F5)"
```

---

### Task 6: F7 — inline citation stub in compact/minimal

**Files:**
- Modify: `gencc_link/constants.py` (CITATION_SHORT)
- Modify: `gencc_link/mcp/envelope.py` (_provenance_meta)
- Modify: `gencc_link/mcp/capabilities.py` (response_fields)
- Test: `tests/test_tools.py`, `tests/test_envelope.py`

- [ ] **Step 1: Write failing tests.**

Add to `tests/test_tools.py::TestEvalHardening`:

```python
    async def test_compact_has_citation_short(self, mcp_client) -> None:
        result = await mcp_client.call_tool(
            "get_gene_curations", {"gene": "SKI", "response_mode": "compact"}
        )
        meta = result.structured_content["_meta"]
        assert meta["citation_short"] == "GenCC (thegencc.org), CC0-1.0"
        assert meta["citation_ref"] == "gencc://citation"

    async def test_full_uses_full_citation_not_short(self, mcp_client) -> None:
        result = await mcp_client.call_tool(
            "get_gene_curations", {"gene": "SKI", "response_mode": "full"}
        )
        meta = result.structured_content["_meta"]
        assert "recommended_citation" in meta
        assert "citation_short" not in meta
```

- [ ] **Step 2: Run to verify failure.**

Run: `uv run pytest tests/test_tools.py -k citation -q`
Expected: FAIL — no `citation_short` key.

- [ ] **Step 3: Add the constant.**

In `gencc_link/constants.py`, after `DATA_LICENSE = "CC0-1.0"` add:

```python
# Short attribution stub for compact/minimal envelopes; the full verbatim citation
# stays behind gencc://citation (and in standard/full). Not a substitute for
# RECOMMENDED_CITATION.
CITATION_SHORT = "GenCC (thegencc.org), CC0-1.0"
```

- [ ] **Step 4: Emit it in the envelope.**

In `gencc_link/mcp/envelope.py`, import `CITATION_SHORT`:
change `from gencc_link.constants import DATA_LICENSE, RECOMMENDED_CITATION` to
`from gencc_link.constants import CITATION_SHORT, DATA_LICENSE, RECOMMENDED_CITATION`.

In `_provenance_meta`, inside the `if response_mode in ("minimal", "compact"):`
branch, after `meta["citation_ref"] = _CITATION_REF` add:

```python
        meta["citation_short"] = CITATION_SHORT
```

- [ ] **Step 5: Document it in capabilities.**

In `gencc_link/mcp/capabilities.py` `response_fields`, after the `citation_ref` entry add:

```python
            "citation_short": "_meta.citation_short: a one-line attribution stub "
            "(minimal/compact) so a sourced answer can be cited without a round-trip; "
            "the full verbatim citation stays at gencc://citation and in standard/full.",
```

- [ ] **Step 6: Run tests to verify pass.**

Run: `uv run pytest tests/test_tools.py tests/test_envelope.py -k "citation or provenance or meta" -q`
Expected: PASS.

- [ ] **Step 7: Commit.**

```bash
git add gencc_link/constants.py gencc_link/mcp/envelope.py gencc_link/mcp/capabilities.py tests/test_tools.py
git commit -m "feat(envelope): inline citation_short stub in compact/minimal (F7)"
```

---

### Task 7: Coverage gap — make `ambiguous_query` reachable

**Files:**
- Modify: `gencc_link/services/gencc_service.py` (resolve_identifier auto-ambiguity)
- Modify: `gencc_link/mcp/next_commands.py` (recovery_commands)
- Modify: `gencc_link/mcp/tools/assertions.py` (resolve_identifier description)
- Test: `tests/test_service.py`, `tests/test_tools.py`, `tests/test_next_commands.py`

- [ ] **Step 1: Write a failing service test with a fake repo (no fixture churn).**

Add to `tests/test_service.py` (top-level):

```python
import pytest

from gencc_link.exceptions import AmbiguousQueryError
from gencc_link.models import DiseaseSummary, GeneSummary
from gencc_link.services.gencc_service import GenCCService


class _BothMatchRepo:
    """Minimal repo stub: one token resolves to BOTH a gene and a disease."""

    def resolve_gene(self, identifier):
        if identifier.upper() == "AMBIG":
            return GeneSummary(gene_curie="HGNC:9", gene_symbol="AMBIG",
                               n_submissions=1, n_diseases=1, n_submitters=1)
        return None

    def resolve_disease(self, identifier):
        if identifier.upper() == "AMBIG":
            return DiseaseSummary(disease_curie="MONDO:9", disease_title="AMBIG",
                                  n_submissions=1, n_genes=1, n_submitters=1)
        return None


def test_resolve_identifier_auto_ambiguous_raises() -> None:
    svc = GenCCService(_BothMatchRepo(), cache_size=0, cache_ttl=0)  # type: ignore[arg-type]
    with pytest.raises(AmbiguousQueryError) as exc:
        svc.resolve_identifier("AMBIG", kind="auto")
    assert "HGNC:9" in str(exc.value)
    assert "MONDO:9" in str(exc.value)


def test_resolve_identifier_kind_gene_not_ambiguous() -> None:
    svc = GenCCService(_BothMatchRepo(), cache_size=0, cache_ttl=0)  # type: ignore[arg-type]
    out = svc.resolve_identifier("AMBIG", kind="gene")
    assert out["gene"]["gene_symbol"] == "AMBIG"
    assert out["disease"] is None
```

- [ ] **Step 2: Run to verify failure.**

Run: `uv run pytest tests/test_service.py -k ambiguous -q`
Expected: FAIL — currently returns both, no raise.

- [ ] **Step 3: Implement auto-ambiguity in the service.**

In `gencc_link/services/gencc_service.py`, add the import near the others:
`from gencc_link.exceptions import AmbiguousQueryError, InvalidInputError, NotFoundError`.

In `resolve_identifier`, before the final `if result["gene"] is None and result["disease"] is None:`
not-found block, add:

```python
        if kind == "auto" and result["gene"] is not None and result["disease"] is not None:
            raise AmbiguousQueryError(
                f"{query!r} matches both a gene ({result['gene']['gene_curie']}) and a "
                f"disease ({result['disease']['disease_curie']}); re-run with kind='gene' "
                "or kind='disease'.",
                candidates=[result["gene"]["gene_curie"], result["disease"]["disease_curie"]],
            )
```

- [ ] **Step 4: Run service tests to verify pass.**

Run: `uv run pytest tests/test_service.py -k ambiguous -q`
Expected: PASS.

- [ ] **Step 5: Add ambiguous_query recovery in next_commands.**

In `gencc_link/mcp/next_commands.py::recovery_commands`, add a branch (after the
`not_found` block, before `invalid_input`):

```python
    if error_code == "ambiguous_query" and tool == "resolve_identifier" and arguments.get("query"):
        return [
            cmd("get_gene_curations", gene=arguments["query"]),
            cmd("get_disease_curations", disease=arguments["query"]),
        ]
```

Add a unit test to `tests/test_next_commands.py`:

```python
def test_recovery_commands_ambiguous_query() -> None:
    cmds = nc.recovery_commands("resolve_identifier", "ambiguous_query", {"query": "AMBIG"}, None)
    assert [c["tool"] for c in cmds] == ["get_gene_curations", "get_disease_curations"]
```

- [ ] **Step 6: Update the resolve_identifier tool description.**

In `gencc_link/mcp/tools/assertions.py`, replace the `resolve_identifier` description string with:

```python
        description=(
            "Resolve free text to a canonical GenCC gene (HGNC) and/or disease "
            "(MONDO) identifier by exact symbol/id/title match. Use kind='gene' or "
            "kind='disease' to disambiguate; default 'auto' tries both and returns "
            "ambiguous_query if the text matches both a gene and a disease."
        ),
```

- [ ] **Step 7: Add a tool-level test for the error envelope.**

This needs a both-match token in the connected fixture client, which `sample.tsv`
does not contain. Instead assert the recovery wiring via the envelope path using a
service-level error is covered in Steps 1–5; add a focused tool test that the code
path is wired by monkeypatching is overkill. Add this lighter assertion to
`tests/test_next_commands.py` already covers recovery. Confirm no fixture token is
both gene and disease so existing `resolve_identifier` tool tests still pass:

Run: `uv run pytest tests/test_tools.py -k resolve -q`
Expected: PASS (e.g. `resolve_identifier("SKI")` still returns the gene; "SKI" is
not a disease title).

- [ ] **Step 8: Run the full affected set.**

Run: `uv run pytest tests/test_service.py tests/test_next_commands.py tests/test_tools.py -q`
Expected: PASS.

- [ ] **Step 9: Commit.**

```bash
git add gencc_link/services/gencc_service.py gencc_link/mcp/next_commands.py gencc_link/mcp/tools/assertions.py tests/test_service.py tests/test_next_commands.py
git commit -m "feat(resolve): reachable ambiguous_query on auto both-match (coverage gap)"
```

---

### Task 8: F4 — declare a meaningful `outputSchema` for every tool

**Files:**
- Create: `gencc_link/mcp/schemas.py`
- Modify: `gencc_link/mcp/tools/discovery.py`, `genes.py`, `diseases.py`, `assertions.py`, `submitters.py` (add `output_schema=`)
- Test: `tests/test_tools.py`

- [ ] **Step 1: Write the failing test for advertised schemas.**

Add to `tests/test_tools.py`:

```python
async def test_all_tools_advertise_typed_output_schema(mcp_client) -> None:
    tools = await mcp_client.list_tools()
    assert tools
    for t in tools:
        schema = t.outputSchema
        assert schema is not None, t.name
        props = schema.get("properties", {})
        assert "success" in props, t.name
        assert "_meta" in props, t.name
        # at least one tool-specific top-level field beyond the envelope
        assert len(props) > 3, t.name
```

- [ ] **Step 2: Run to verify failure.**

Run: `uv run pytest tests/test_tools.py::test_all_tools_advertise_typed_output_schema -q`
Expected: FAIL — current schemas have empty `properties`.

- [ ] **Step 3: Create the schema module.**

Create `gencc_link/mcp/schemas.py`:

```python
"""JSON Schema (2020-12) output schemas advertised by GenCC-Link tools.

FastMCP already emits ``structuredContent`` for dict-returning tools, but with a
contentless ``{type: object, additionalProperties: true}`` schema. These schemas
give clients a real, conformant field glossary. ``additionalProperties: true`` and
``required: ["success"]`` keep every response_mode tier and error envelope valid.
"""

from __future__ import annotations

from typing import Any

_STR = {"type": "string"}
_INT = {"type": "integer"}
_BOOL = {"type": "boolean"}
_OBJ: dict[str, Any] = {"type": "object", "additionalProperties": True}
_OBJ_ARRAY: dict[str, Any] = {"type": "array", "items": _OBJ}

_NEXT_COMMANDS = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {"tool": _STR, "arguments": _OBJ},
        "required": ["tool", "arguments"],
        "additionalProperties": False,
    },
}

_META = {
    "type": "object",
    "description": "Per-call envelope metadata.",
    "properties": {
        "request_id": _STR,
        "elapsed_ms": {"type": "number"},
        "response_mode": _STR,
        "data_license": _STR,
        "unsafe_for_clinical_use": _BOOL,
        "gencc_release": _STR,
        "recommended_citation": _STR,
        "citation_ref": _STR,
        "citation_short": _STR,
        "next_commands": _NEXT_COMMANDS,
        "tool": _STR,
    },
    "additionalProperties": True,
}

_TRUNCATION = {
    "type": "object",
    "properties": {
        "total": _INT,
        "returned": _INT,
        "next_offset": _INT,
        "hint": _STR,
    },
    "additionalProperties": True,
}

# Fields shared by success and error envelopes (all optional but success).
_BASE_PROPS: dict[str, Any] = {
    "success": _BOOL,
    "headline": _STR,
    "_meta": _META,
    "error_code": _STR,
    "message": _STR,
    "retryable": _BOOL,
    "recovery_action": _STR,
    "field_errors": _OBJ_ARRAY,
}


def tool_output_schema(**top_level: dict[str, Any]) -> dict[str, Any]:
    """Build a permissive-but-typed object schema: envelope + tool-specific fields."""
    return {
        "type": "object",
        "properties": {**_BASE_PROPS, **top_level},
        "required": ["success"],
        "additionalProperties": True,
    }


SEARCH_GENES_SCHEMA = tool_output_schema(
    query=_STR, count=_INT, total=_INT, genes=_OBJ_ARRAY, truncated=_TRUNCATION
)
SEARCH_DISEASES_SCHEMA = tool_output_schema(
    query=_STR, count=_INT, total=_INT, diseases=_OBJ_ARRAY, truncated=_TRUNCATION
)
GENE_CURATIONS_SCHEMA = tool_output_schema(
    gene=_OBJ, count=_INT, total=_INT, diseases=_OBJ_ARRAY, truncated=_TRUNCATION
)
DISEASE_CURATIONS_SCHEMA = tool_output_schema(
    disease=_OBJ, count=_INT, total=_INT, genes=_OBJ_ARRAY, truncated=_TRUNCATION
)
GENES_CURATIONS_SCHEMA = tool_output_schema(
    requested=_INT, count=_INT, results=_OBJ_ARRAY, unresolved=_OBJ_ARRAY
)
DISEASES_CURATIONS_SCHEMA = GENES_CURATIONS_SCHEMA
ASSERTION_SCHEMA = tool_output_schema(assertion=_OBJ, submissions=_OBJ_ARRAY)
FIND_CURATIONS_SCHEMA = tool_output_schema(
    count=_INT, total=_INT, filters=_OBJ, results=_OBJ_ARRAY, truncated=_TRUNCATION
)
RESOLVE_SCHEMA = tool_output_schema(query=_STR, gene=_OBJ, disease=_OBJ)
LIST_SUBMITTERS_SCHEMA = tool_output_schema(count=_INT, submitters=_OBJ_ARRAY)
CAPABILITIES_SCHEMA = tool_output_schema(
    server=_STR, server_version=_STR, tools=_OBJ_ARRAY, classifications=_OBJ_ARRAY,
    response_modes=_OBJ, capabilities_version=_STR, data=_OBJ,
)
DIAGNOSTICS_SCHEMA = tool_output_schema(
    server_version=_STR, capabilities_version=_STR, data=_OBJ, refresh=_OBJ, quota=_OBJ
)
```

- [ ] **Step 4: Wire schemas into the discovery tools.**

In `gencc_link/mcp/tools/discovery.py`, add the import
`from gencc_link.mcp.schemas import CAPABILITIES_SCHEMA, DIAGNOSTICS_SCHEMA` and add
`output_schema=CAPABILITIES_SCHEMA,` to the `get_server_capabilities` `@mcp.tool(...)`
and `output_schema=DIAGNOSTICS_SCHEMA,` to `get_gencc_diagnostics`.

- [ ] **Step 5: Wire schemas into gene tools.**

In `gencc_link/mcp/tools/genes.py`, add
`from gencc_link.mcp.schemas import GENE_CURATIONS_SCHEMA, GENES_CURATIONS_SCHEMA, SEARCH_GENES_SCHEMA`
and add `output_schema=SEARCH_GENES_SCHEMA,` to `search_genes`,
`output_schema=GENE_CURATIONS_SCHEMA,` to `get_gene_curations`,
`output_schema=GENES_CURATIONS_SCHEMA,` to `get_genes_curations`.

- [ ] **Step 6: Wire schemas into disease tools.**

In `gencc_link/mcp/tools/diseases.py`, add
`from gencc_link.mcp.schemas import DISEASE_CURATIONS_SCHEMA, DISEASES_CURATIONS_SCHEMA, SEARCH_DISEASES_SCHEMA`
and add `output_schema=SEARCH_DISEASES_SCHEMA,` to `search_diseases`,
`output_schema=DISEASE_CURATIONS_SCHEMA,` to `get_disease_curations`,
`output_schema=DISEASES_CURATIONS_SCHEMA,` to `get_diseases_curations`.

- [ ] **Step 7: Wire schemas into assertion tools.**

In `gencc_link/mcp/tools/assertions.py`, add
`from gencc_link.mcp.schemas import ASSERTION_SCHEMA, FIND_CURATIONS_SCHEMA, RESOLVE_SCHEMA`
and add `output_schema=ASSERTION_SCHEMA,` to `get_gene_disease_assertion`,
`output_schema=FIND_CURATIONS_SCHEMA,` to `find_curations`,
`output_schema=RESOLVE_SCHEMA,` to `resolve_identifier`.

- [ ] **Step 8: Wire schema into the submitter tool.**

In `gencc_link/mcp/tools/submitters.py`, add
`from gencc_link.mcp.schemas import LIST_SUBMITTERS_SCHEMA` and add
`output_schema=LIST_SUBMITTERS_SCHEMA,` to `list_submitters`.

- [ ] **Step 9: Run the schema test + a representative structured-content test.**

Run: `uv run pytest tests/test_tools.py::test_all_tools_advertise_typed_output_schema tests/test_tools.py -k "success or capabilities or diagnostics" -q`
Expected: PASS — schemas now typed, structured content still conforms.

- [ ] **Step 10: Commit.**

```bash
git add gencc_link/mcp/schemas.py gencc_link/mcp/tools/discovery.py gencc_link/mcp/tools/genes.py gencc_link/mcp/tools/diseases.py gencc_link/mcp/tools/assertions.py gencc_link/mcp/tools/submitters.py tests/test_tools.py
git commit -m "feat(mcp): declare typed outputSchema for every tool (F4)"
```

---

### Task 9: Docs reconciliation, version bump, CHANGELOG

**Files:**
- Modify: `docs/architecture.md`, `docs/usage.md`, `docs/MCP_CONNECTION_GUIDE.md`, `README.md`
- Modify: `pyproject.toml` (version)
- Modify: `CHANGELOG.md` (create if absent)
- Test: `tests/test_capabilities.py` (version assertion if present)

- [ ] **Step 1: Reconcile the rename + new fields in prose docs.**

Run: `grep -rn "consensus_classification" docs/architecture.md docs/usage.md docs/MCP_CONNECTION_GUIDE.md README.md`
For each hit, change `consensus_classification` to `strongest_classification` and,
where the doc defines it (e.g. `docs/architecture.md:168` "the classification with
the highest rank among …"), keep the definition but add "(surfaced as
`strongest_classification`; the DB column remains `consensus_classification`)".
Add a one-line mention of `submitted_as_date_iso` and `citation_short` wherever
response fields are enumerated (e.g. `docs/usage.md`). Do NOT touch
`docs/mcp-consumer-assessment.md` (the source assessment) or the superpowers
spec/plan files.

- [ ] **Step 2: Bump the version.**

Run: `grep -n '^version' pyproject.toml`
Change `version = "0.1.0"` to `version = "0.2.0"`.

- [ ] **Step 3: Update/confirm the version test.**

Run: `grep -rn "0.1.0\|server_version" tests/test_capabilities.py`
If a test pins `0.1.0`, update it to `0.2.0`. (If the test reads the installed
version dynamically, no change needed.)

- [ ] **Step 4: Add a CHANGELOG entry.**

If `CHANGELOG.md` exists, prepend a `## [0.2.0] - 2026-06-12` section; otherwise create
`CHANGELOG.md` with that section. Content:

```markdown
# Changelog

## [0.2.0] - 2026-06-12

### Changed
- **BREAKING:** renamed the gene-disease output field `consensus_classification`
  to `strongest_classification` (it is the max-rank assertion, not an agreement
  measure). The SQLite column is unchanged.
- Multi-result `search_genes`/`search_diseases` headlines now summarize the set
  instead of naming only the first hit.
- `_meta.next_commands` now fans out across every resolved entity on multi-result
  and batch responses (capped), keeping the unresolved-recovery hint.
- `minimal` mode keeps `n_submitters` so the headline's submitter count matches.

### Added
- Typed `outputSchema` for all 12 tools (clients can validate structured content).
- `submitted_as_date_iso` (ISO-8601 date) alongside the verbatim `submitted_as_date`.
- `_meta.citation_short` attribution stub in minimal/compact.
- Reachable `ambiguous_query`: `resolve_identifier(kind='auto')` now errors when a
  query matches both a gene and a disease, with disambiguation recovery commands.
```

- [ ] **Step 5: Reinstall so the version metadata is current, then sanity-check.**

Run: `uv pip install -e . -q && uv run python -c "from gencc_link.mcp.capabilities import server_version; print(server_version())"`
Expected: `0.2.0`.

- [ ] **Step 6: Run capabilities + tools tests.**

Run: `uv run pytest tests/test_capabilities.py tests/test_tools.py -q`
Expected: PASS.

- [ ] **Step 7: Commit.**

```bash
git add docs/architecture.md docs/usage.md docs/MCP_CONNECTION_GUIDE.md README.md pyproject.toml CHANGELOG.md tests/test_capabilities.py
git commit -m "docs(release): reconcile docs with renamed field + new contract; bump 0.2.0"
```

---

### Task 10: Full gate + assessment cross-check + final probe

**Files:** none (verification only)

- [ ] **Step 1: Run the full local CI gate.**

Run: `make ci-local`
Expected: PASS — ruff format check, ruff lint, lint-loc (<600), mypy strict, full
unit suite, coverage ≥85%.

- [ ] **Step 2: If anything fails, fix and re-run.**

Triage per `.claude/skills/ci-failure-triage`. Re-run `make ci-local` until green.
Do not bypass checks.

- [ ] **Step 3: Probe the live server end-to-end for the assessment's exact cases.**

Run:

```bash
uv run python - <<'PY'
import asyncio, json
from fastmcp import Client
from gencc_link.mcp.facade import create_gencc_mcp

async def main():
    async with Client(create_gencc_mcp()) as c:
        # F1: multi-hit headline names the set
        r = await c.call_tool("search_genes", {"query": "COL"})
        print("F1 headline:", r.structured_content["headline"])
        # F2: fan-out
        r = await c.call_tool("search_genes", {"query": "COL"})
        print("F2 next_commands:", [x["arguments"] for x in r.structured_content["_meta"]["next_commands"]])
        # F3: renamed field
        r = await c.call_tool("get_gene_curations", {"gene": "GLA"})
        print("F3 key present:", "strongest_classification" in r.structured_content["diseases"][0])
        # F4: typed schema
        tools = await c.list_tools()
        print("F4 schemas typed:", all(t.outputSchema.get("properties") for t in tools))
        # F5/F7
        r = await c.call_tool("get_gene_disease_assertion", {"gene":"GLA","disease":"MONDO:0010526","response_mode":"full"})
        print("F5 iso:", any("submitted_as_date_iso" in s for s in r.structured_content["assertion"]["submitters"]))
        r = await c.call_tool("get_gene_curations", {"gene":"SKI"})
        print("F7 citation_short:", r.structured_content["_meta"].get("citation_short"))

asyncio.run(main())
PY
```

Expected: F1 names COL1A1+COL2A1; F2 lists both genes; F3 True; F4 True; F5 True;
F7 prints the stub.

- [ ] **Step 4: Cross-check each finding against the assessment.**

Open `docs/mcp-consumer-assessment.md` and confirm F1–F7 + the coverage gap each map
to a shipped commit. Note any residual in the final summary.

- [ ] **Step 5: Final commit (only if Step 2/4 produced fixes).**

```bash
git add -A && git commit -m "chore: ci-local green; finalize consumer-uplift"
```

---

## Self-review

**Spec coverage:** F1→Task 3; F2→Task 4; F3→Task 1; F4→Task 8; F5→Task 5; F6→Task 2;
F7→Task 6; coverage gap→Task 7; docs/version/changelog→Task 9; gate+cross-check→Task 10. All spec sections covered.

**Placeholders:** none — every code/doc step shows exact content or an exact grep/edit instruction.

**Type/name consistency:** `strongest_classification` (model field + DB-column source `consensus_classification`) used consistently across Tasks 1/3/8/9; `normalize_submitted_date`, `_MAX_NEXT_COMMANDS`, `_MAX_HEADLINE_NAMES`, `CITATION_SHORT`, and the `*_SCHEMA` names are each defined once and referenced consistently; `tool_output_schema(**top_level)` signature matches all call sites.

**Ordering:** F3 (rename) first so later tasks build on the new field; F4 (schemas) after the payload-shape changes so schemas describe the final shape; docs/version last before the gate.
