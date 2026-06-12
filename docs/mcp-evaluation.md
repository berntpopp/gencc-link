# GenCC-Link MCP Evaluation

An LLM-consumer assessment of the GenCC-Link MCP server, conducted by exercising
the live tools against the standard test data (gene SKI / disease MONDO:0008426),
the BRCA2 and NAA10 worked examples, and deliberate failure cases.

- Data release tested: GenCC run date 2026-06-07 (29,846 submissions, 6,095
  genes, 8,149 diseases, 18 submitters).
- Server version: 0.1.0 (MCP protocol 2025-11-25).
- Scope: all 10 public tools, both `response_mode` extremes, pagination,
  boundary inputs, CURIE/case resolution, conflict filtering, and error paths.

This document has two parts:

1. **UX scorecard** - rates the server across the dimensions an MCP should excel
   at (discoverability, token efficiency, speed, observability, error handling).
2. **Senior-tester report** - a systematic test matrix across every tool, with
   findings ranked by severity and concrete recommendations.

---

## Part 1 - UX Scorecard

Ratings are 1-10 from the perspective of the LLM consuming the server.

| Area | Score | Basis |
|---|---|---|
| Discoverability | 9 | `get_server_capabilities` is a genuine self-description |
| Observability | 9 | `get_gencc_diagnostics` exposes provenance + freshness as first-class |
| Error handling | 8 | Structured, actionable - one missing affordance |
| Token efficiency | 7 | The lever works, but avoidable per-call redundancy |
| Speed | 9 | Local SQLite/FTS5; sub-second, parallel-friendly (estimated, not instrumented) |
| **Overall** | **8.5** | A polished, well-considered server with a few cheap wins left on the table |

### What is done unusually well (do not regress these)

- **Capabilities is a real contract, not a blurb.** It returns the tool
  inventory, the full classification vocabulary *with ranks*, what each
  `response_mode` includes, `recommended_workflows` written as literal example
  invocations, `parameter_conventions`, the error taxonomy, `token_cost_hints`,
  and a `capabilities_version` hash so a warm client can skip re-fetching.
- **`headline` on every payload.** A one-line plain-English answer at the top of
  each response - the right affordance for an LLM to ground a summary without
  parsing the structured body first.
- **Observability is first-class.** Diagnostics reports row/gene/disease/
  submitter counts, source ETag + last-modified, run date, `build_utc`,
  `build_duration_s`, schema version, and the refresh scheduler's live state
  (enabled, interval, last error). Provenance travels with the data.
- **Errors are structured and actionable.** Bad input returns `success:false`,
  a machine-readable `error_code`, `retryable`, `recovery_action`, and a human
  message that names the recovery tool.
- **`next_commands` chaining** turns the tool graph into a deterministic walk -
  success responses hand back ready-to-call `{tool, arguments}` next steps.

### Improvements (ordered by value-to-effort)

1. **Put `next_commands` on error envelopes too.** Success responses give a
   ready-to-execute next step; the `not_found` error only gives prose. It should
   hand back, e.g., `next_commands:[{tool:"search_genes", arguments:{query:...}}]`
   so recovery is deterministic instead of parsed from a sentence.
2. **Stop repeating `gene_curie`/`gene_symbol` in every disease row.** In the
   BRCA2 compact response all 8 rows repeat the same gene identifier already
   present in the parent `gene` object - pure duplication that scales with row
   count. Drop it from the rows (or omit in `minimal`/`compact`).
3. **Make the citation boilerplate cacheable.** The full ~260-char
   `recommended_citation` is re-emitted in `_meta` on every response, including
   `minimal`. Offer a short `_meta.citation_ref:"gencc://citation"` in
   `compact`/`minimal` and reserve the full string for `full` mode and
   capabilities - the same idea already used for `capabilities_version`.
4. **Add a request/trace id and optional server-side timing to `_meta`** so
   latency and multi-call debugging are observable rather than inferred.
5. **Surface the download-quota headroom in diagnostics** (downloads used today
   / 20) so the one real upstream rate limit is visible before it bites.

---

## Part 2 - Senior-Tester Report

32 tool calls across all 10 tools. The matrix below records the cases exercised;
findings follow, ranked by severity.

### Verdict

A genuinely well-engineered server - every tool works, error handling is
structured, and the consensus/conflict analysis is sound. Testing surfaced one
high-severity correctness trap (silent zero-results on out-of-vocabulary
filters), one medium clarity gap, and one small `next_commands` bug. Nothing is
broken at the data level.

### Tool-by-tool coverage

| Tool | Cases exercised | Verdict |
|---|---|---|
| `get_server_capabilities` | self-description, version hash | Pass - gap: omits MOI vocabulary |
| `get_gencc_diagnostics` | provenance, refresh state | Pass - strong |
| `search_genes` | exact, partial (`BRCA`->2), case (`brca2`), empty, no-match | Pass - minor next_commands bug |
| `search_diseases` | title, MONDO, OMIM CURIE, empty | Pass |
| `get_gene_curations` | modes, pagination (`limit`/`offset`), `limit=0`, `offset=999` | Pass |
| `get_disease_curations` | compact + standard (per-submitter) | Pass |
| `get_gene_disease_assertion` | full mode, minimal, valid-but-unlinked pair | Pass - full mode is excellent |
| `find_curations` | no-filter, conflict, vocab combos, bad values | Pass with caveats (H1/M1) |
| `list_submitters` | full roster | Pass - 18 with counts |
| `resolve_identifier` | gene, disease-by-title, not_found | Pass |

### Findings by severity

#### H1 - Out-of-vocabulary filter values return `count: 0` instead of `invalid_input` (highest-value fix)

Three confirmed cases all returned a clean empty result set, indistinguishable
from "no data exists":

- `find_curations(classification=["Pathogenic"])` -> `count:0`
- `find_curations(submitter=["NotARealLab"])` -> `count:0`
- `find_curations(moi="Recessive")` -> `count:0`

This is a serious trap specifically for an LLM consumer: a wrong vocabulary
(ClinVar's "Pathogenic", the short form "Recessive") silently produces the false
conclusion "there are no such curations." The server already knows all three
controlled vocabularies (classifications in capabilities; submitters via
`list_submitters`; MOI is a tiny closed set).

**Recommend:** validate these filters and return `invalid_input` echoing the
accepted values, e.g. "'Recessive' is not a valid mode of inheritance; expected
one of [Autosomal dominant, Autosomal recessive, X-linked, ...]."

#### M1 - `find_curations` classification filter is submission-level, but rows only show consensus, with no indication of what matched

Confirmed semantics: `classification=["Refuted Evidence"]` returns pairs where
*any* submitter refuted - so a row can read `consensus: "Strong"` while having
matched on a single Refuted submission. The behavior is *correct*, and the
`submitter`+`classification` conjunction is also correct:

> Decisive test - BRIP1 / hereditary breast carcinoma (MONDO:0016419), where
> ClinGen asserted Refuted Evidence and Ambry asserted Limited:
> - `classification=["Refuted Evidence"], submitter=["ClinGen"]` -> BRIP1 present
> - `classification=["Refuted Evidence"], submitter=["Ambry Genetics"]` -> BRIP1 absent
>
> This proves the conjunction means "that submitter gave that classification,"
> not a cross-submitter false positive.

The problem is purely observability: nothing in the result row tells you which
submitter/classification satisfied the filter, so the rows look wrong.

**Recommend:** add a `matched` field (the submitter+classification that
triggered the hit) and document in the tool description that `classification`
matches at submission level, not consensus.

#### M2 - Zero-result search emits a `next_commands` suggestion guaranteed to fail

`search_genes("ZZZX")` (0 hits) returned
`next_commands: [{tool: "search_diseases", arguments: {query: ""}}]` - an empty
query, which separately returns `invalid_input`. An agent chaining
`next_commands` deterministically walks straight into an error.

**Recommend:** propagate the original query (`"ZZZX"`), not an empty string - or
omit the suggestion on zero results.

#### M3 - Error envelopes lack machine-actionable `next_commands`

Every error triggered (empty query, no-filter, unlinked pair, unresolved token)
gives a helpful prose recovery hint but no `{tool, arguments}` next step, unlike
every success path. The `not_found` on `get_gene_curations` should hand back
`next_commands: [{tool: "search_genes", arguments: {query: <input>}}]`.

#### L1 - MOI vocabulary is not discoverable

`get_server_capabilities` enumerates the 9 classifications with ranks but omits
the mode-of-inheritance value set, so a consumer cannot know to pass
"Autosomal recessive" rather than "Recessive." Add an `inheritance_modes` list
(pairs naturally with the H1 fix).

#### L2 - Token redundancy (across all list tools)

Every row in `get_gene_curations` / `get_disease_curations` / `find_curations`
repeats the parent identifier (`gene_curie`+`gene_symbol`, or
`disease_curie`+`disease_title`) already present in the parent object, and the
full ~260-char citation is re-emitted in `_meta` on every call including
`minimal`.

#### L3 - Source data passed through verbatim (not bugs; worth a doc note)

- `assertion_criteria_url` sometimes holds a non-URL (e.g. `"PMID: 28106320"`).
- `submitted_as_date` mixes formats (`"2018-03-30 13:31:56"` vs
  `"2024-07-23T00:00:00.000000Z"`).
- Positive note: the structured `pmids` array carries a correctly-formed PMID
  (`24736733`) where the raw ClinGen note text has it truncated (`4736733`) -
  the server improves on the source there.

### What works well (protect in any refactor)

- Case-insensitive and partial search with exact-match-first ranking.
- OMIM->MONDO and title->MONDO resolution.
- Consistent pagination contract (`count`/`total`/`truncated`/`next_offset`/
  `hint`) across all list tools.
- Semantically correct `has_conflict` detection (33 conflict pairs, each with
  genuine supporting + refuting coexistence).
- Structured `field_errors` with boundary validation (`limit >= 1`).
- Genuinely rich `full` assertion mode (deduped PMIDs, curation notes,
  `disease_original_curie`, criteria URLs).

### Prioritized recommendations

1. **Validate enum filters** (`classification`, `submitter`, `moi`) -> return
   `invalid_input` with accepted values. *(H1 - correctness, biggest LLM-safety win.)*
2. **Add `next_commands` to error envelopes** and **fix the zero-result search
   suggestion** to propagate the query. *(M2, M3 - cheap, makes chaining reliable.)*
3. **Surface the matched submission in `find_curations` rows** and document
   submission-level filter semantics. *(M1.)*
4. **Add MOI vocabulary to capabilities; trim per-row identifier and citation
   redundancy.** *(L1, L2.)*

Items 1, 2, and 4 are self-contained tool/facade edits with no schema change and
map onto the repo-local `mcp-tool-change` skill.

---

## Resolution (2026-06-12)

Every finding above was addressed in the `feat/mcp-eval-hardening` change set.
Design spec: `docs/superpowers/specs/2026-06-12-mcp-evaluation-hardening-design.md`;
plan: `docs/superpowers/plans/2026-06-12-mcp-evaluation-hardening.md`.

| Finding | Status | What changed |
|---|---|---|
| H1 — silent zero on out-of-vocab filters | Fixed | `find_curations` validates `classification`/`submitter`/`moi` (case-insensitive, canonicalised) and returns `invalid_input` with the accepted set + "did you mean". `submitter`/`moi` valid-sets are **data-derived** (GenCC ships quirky titles like `"Y-linked inheritance"`); `classification` uses the controlled vocabulary. Also fixes the previously-silent case-sensitivity miss (`"definitive"`, `"clingen"`). |
| M1 — no indication of what matched | Fixed | Each submission-filtered row carries a `matched` field (submitter + classification + moi that triggered the hit); semantics documented in the tool description, `gencc://reference`, and capabilities `data_notes`. |
| M2 — zero-result `next_commands` fails | Fixed | The cross-over suggestion propagates the original query instead of `query=""`; an empty query yields no suggestion. |
| M3 — error envelopes lack `next_commands` | Fixed | Error `_meta` now carries recovery `next_commands` via a tool/error/field recovery map (e.g. `not_found` → `search_*` with the same input; invalid `submitter` → `list_submitters`). |
| L1 — MOI vocabulary not discoverable | Fixed | Capabilities exposes data-derived `inheritance_modes` (`{title, curie}`) and an `moi` `parameter_convention`. |
| L2 — per-row id + citation redundancy | Fixed | `minimal`/`compact` drop the redundant parent id from list rows and replace the full citation with `_meta.citation_ref = "gencc://citation"`. |
| L3 — verbatim source quirks undocumented | Fixed | Documented in capabilities `data_notes` and `gencc://reference`. |
| Scorecard — latency/trace not observable | Fixed | Every `_meta` carries `request_id` + `elapsed_ms`. |
| Scorecard — download-quota headroom | Fixed | The downloader tracks daily real-download usage; `get_gencc_diagnostics` reports a `quota` block (`used_today` / `daily_quota` / `remaining`). |
