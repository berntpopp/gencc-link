# GenCC-Link — MCP Evaluation Hardening — Design Spec

> Historical record — this document records the design or plan as of its date. Current behavior is
> defined by implemented code, standards, release evidence, and tests.

**Date:** 2026-06-12
**Status:** Approved for implementation (autonomous build)
**Author:** Claude (MCP engineer)
**Input:** `docs/mcp-evaluation.md` (LLM-consumer assessment, overall 8.5/10)

## 1. Purpose

The evaluation rates GenCC-Link 8.5/10 and lists concrete, self-contained
improvements. This spec turns the full backlog (Part 1 scorecard items + Part 2
findings H1/M1/M2/M3/L1/L2/L3) into a single coherent change set that targets a
>9.5/10 LLM-consumer experience while preserving every behaviour the evaluation
flagged as "do not regress."

No tool is added, renamed, or removed. All changes are tool/facade/service/data
edits plus docs. The GenCC schema is unchanged.

## 2. Goals / Non-goals

**Goals** — close every gap in the evaluation:

| ID | Gap | Change |
|----|-----|--------|
| H1 | Out-of-vocab filter values return `count:0` (silent false negative) | Validate `classification`/`submitter`/`moi`; raise `invalid_input` with accepted values + "did you mean". Also fixes the case-sensitivity silent-zero (`"definitive"`, `"clingen"`). |
| M1 | `find_curations` rows don't show what matched | Add `matched` (submitter+classification+moi that triggered the hit); document submission-level filter semantics. |
| M2 | Zero-result search emits `search_*(query="")` → guaranteed error | Propagate the original query into the cross-over suggestion. |
| M3 | Error envelopes lack machine-actionable `next_commands` | Add recovery `next_commands` to error `_meta`. |
| L1 | MOI vocabulary not discoverable | Add `inheritance_modes` to capabilities (data-derived). |
| L2 | Per-row id + citation redundancy | Drop redundant parent id from rows (minimal/compact); replace full citation with `citation_ref` in minimal/compact. |
| L3 | Verbatim source quirks undocumented | Document passthrough quirks in reference notes + capabilities. |
| Obs | Latency/trace not observable | Add `request_id` + `elapsed_ms` to every `_meta`. |
| Obs | Download-quota headroom invisible | Surface `downloads used today / 20` in diagnostics. |

**Non-goals:** schema changes; new tools; changing consensus/conflict logic;
changing FTS/search ranking; programmatic-tool-calling / code-mode (out of scope).

## 3. Key design decisions (the non-obvious ones)

### 3.1 Validity sources: constant vs data-derived

The single most important decision. The real GenCC export (verified against the
built DB) has **quirky, drifting MOI titles**: `"Autosomal recessive"`,
`"Autosomal dominant"`, `"X-linked"`, `"Unknown"`, `"Semidominant"`,
`"Mitochondrial"`, `"X-linked recessive"`, **`"Y-linked inheritance"`** (note the
trailing word, inconsistent with the others). Submitters also grow over time (18
today, e.g. `"Labcorp Genetics (formerly Invitae)"`).

Therefore validity sets are sourced as follows:

- **`classification`** → the controlled-vocabulary constant `CLASSIFICATION_ORDER`
  (stable; the 8 values in data are all members). Case-insensitive match,
  canonicalised to the stored title.
- **`submitter`** → **data-derived** distinct `submitter_title` + `submitter_curie`.
  Case-insensitive, canonicalised to the stored title.
- **`moi`** → **data-derived** distinct `moi_title` (with `moi_curie` for display).
  Case-insensitive, canonicalised to the stored title.

A hardcoded MOI constant would re-introduce the H1 trap (rejecting the real
`"Y-linked inheritance"`), so MOI is data-derived everywhere — including
capabilities — and never appears in the static, hashed capabilities surface.

Canonicalisation is a real correctness fix beyond the eval: the existing
`classification`/`submitter` SQL uses case-sensitive `IN (...)`, so `"definitive"`
or `"clingen"` already silently returned `count:0`. After validation the service
passes canonical values to the repository, so case no longer matters.

### 3.2 Validation lives in a new pure module `gencc_link/services/filters.py`

`validate_find_filters(...)` is a pure function taking the raw filter inputs plus
the data-derived valid sets (passed in by the service, so the module has no repo
dependency). It returns canonicalised `(classification, submitter, moi)` or raises
`InvalidInputError` with `field` set. "Did you mean" uses `difflib.get_close_matches`.
This keeps `gencc_service.py` lean (file-size discipline) and the logic unit-testable.

Error message shape (per field):
- `classification` (9 values): list all accepted inline + closest match.
- `moi` (small set): list all accepted inline + closest match.
- `submitter` (18): closest match + "call list_submitters for the full roster"
  (avoid dumping 18 names every error).

Multiple invalid values in one list are collected and reported together.

### 3.3 `matched` provenance (M1)

`_pairs_from_submissions` changes from returning `set[pair]` to returning
`dict[pair, list[{submitter_title, classification_title, moi_title}]]` (the
distinct submissions that satisfied the filter — every returned row is by
definition a match). `find_assertions` returns `(page, total, matched_by_pair)`.
The service attaches `row["matched"]` to each result in **compact/standard/full**
(omitted in `minimal`, and absent when no submission-level filter is active).

### 3.4 Error `next_commands` via a recovery map (M3)

`McpErrorContext` gains `arguments: dict`. Each tool passes its call args. The
envelope calls `next_commands.recovery_commands(tool, error_code, arguments, field)`
and, when non-empty, sets `_meta.next_commands` on the error envelope. Mapping:

- `not_found` on `get_gene_curations` → `search_genes(query=<gene>)`
- `not_found` on `get_disease_curations` → `search_diseases(query=<disease>)`
- `not_found` on `get_gene_disease_assertion` → `get_gene_curations(<gene>)` + `get_disease_curations(<disease>)`
- `not_found` on `resolve_identifier` → `search_genes(<query>)` + `search_diseases(<query>)`
- `invalid_input` field `submitter` → `list_submitters`
- `invalid_input` field `classification`/`moi` → `get_server_capabilities`
- `data_unavailable` → `get_gencc_diagnostics`

Layering stays correct (service never imports MCP); the map lives in the MCP layer.

### 3.5 Token trims (L2), mode-aware

- **Redundant parent id:** `assertion_dict(a, mode, *, omit_gene=False, omit_disease=False)`.
  `get_gene_curations` rows pass `omit_gene=True`; `get_disease_curations` rows pass
  `omit_disease=True` — **only in minimal/compact** (kept in standard/full where rows
  are consumed individually). `find_curations` keeps both (rows are cross-gene/disease).
- **Citation:** `run_mcp_tool(..., response_mode=...)`. In minimal/compact the
  envelope emits `_meta.citation_ref = "gencc://citation"` instead of the ~260-char
  `recommended_citation`; standard/full and discovery/resolve tools keep the full
  string. The `gencc://citation` resource already exists.

### 3.6 Observability (`_meta`)

`run_mcp_tool` wraps execution with `time.perf_counter` and a short
`uuid4().hex[:12]` request id, adding `_meta.request_id` and `_meta.elapsed_ms`
(rounded) to **both** success and error envelopes. Also echoes `_meta.response_mode`
when known.

### 3.7 Download-quota headroom (diagnostics)

`download_cache.json` gains a `downloads` record `{date: "YYYY-MM-DD" (UTC), count}`.
`download_export` increments it on each real (200, body) GET; `304`/`HEAD` do not.
`download_quota_status(config)` returns `{date, used_today, daily_quota, remaining}`
with same-day reset. `get_gencc_diagnostics` adds a `quota` block (best-effort;
never breaks diagnostics). Cross-process via the shared file under `data_dir`.

## 4. Capabilities & docs updates

- Capabilities `build_capabilities()` (live section, **not** the hashed static
  surface) gains `inheritance_modes: [{title, curie}]` (data-derived) and a
  `data_notes` block documenting verbatim passthrough quirks (`assertion_criteria_url`
  may be non-URL; `submitted_as_date` mixed formats; structured `pmids` normalised).
- `parameter_conventions.moi` documents data-derived values + "see inheritance_modes".
- `find_curations` tool description documents submission-level matching + `matched`.
- `response_fields` documents `matched`, `citation_ref`, `request_id`, `elapsed_ms`.
- `GENCC_REFERENCE_NOTES` (gencc://reference) documents the quirks + filter semantics.
- README / docs/usage.md / docs/MCP_CONNECTION_GUIDE.md: note new fields where they
  describe the response envelope and find_curations.

## 5. Testing

TDD per change. New/updated tests:
- `test_filters.py` (new): canonicalisation, case-insensitivity, rejection +
  did-you-mean, multi-invalid collection, valid passthrough.
- `test_service.py`: invalid enum → `InvalidInputError` with field; canonical
  case-insensitive filters return data; `matched` present/shape; minimal omits it.
- `test_repository.py`: `find_assertions` returns `matched_by_pair`; `distinct_moi`.
- `test_envelope.py`: `request_id`/`elapsed_ms` present + typed; `citation_ref` in
  compact/minimal, full citation otherwise; error `next_commands` via recovery map.
- `test_next_commands.py`: `recovery_commands` table; `after_search_*` propagates query.
- `test_shaping.py`: `omit_gene`/`omit_disease` behaviour by mode.
- `test_capabilities.py`: `inheritance_modes`, `data_notes`; `capabilities_version`
  unchanged by data-derived additions.
- `test_downloader.py`: quota counter increment, same-day reset, `quota_status`.
- `test_tools.py`: end-to-end find_curations invalid value path; matched in payload.
- Invariant test: every distinct `moi_title`/`submitter_title` in the fixture is
  accepted by the validator (guards constant/data drift).

Gate: `make ci-local` (format, lint, lint-loc ≤600, typecheck strict, tests, 85% cov).

## 6. Risks & mitigations

- **Test churn from `request_id`/`elapsed_ms`:** assert presence/type, never value.
- **File-size cap:** new `filters.py` absorbs validation; repository gains only
  small methods; envelope/service stay under 600.
- **Quota counter cross-process correctness:** best-effort read in diagnostics,
  isolated in the downloader, fully covered by `respx` tests; failure degrades to
  omitting the `quota` block, never an error.
- **Backward-compat of `find_assertions` signature:** internal Protocol method;
  updated in lockstep across base/repo/service/tests.

## 7. Definition of done

`make ci-local` green; every eval item demonstrably addressed by a test; docs and
capabilities reflect the new contract; `docs/mcp-evaluation.md` annotated with a
resolution note pointing here.
