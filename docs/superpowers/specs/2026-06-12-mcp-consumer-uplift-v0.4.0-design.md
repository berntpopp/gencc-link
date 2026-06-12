# GenCC-Link MCP — Consumer-Uplift v0.4.0 (Design Spec)

| | |
|---|---|
| **Status** | Approved (autonomous goal directive) |
| **Date** | 2026-06-12 |
| **Author** | Claude (MCP engineer role) |
| **Source assessment** | `docs/mcp-consumer-assessment-v0.3.0.md` (scored 9/10 by an LLM consumer) |
| **Target** | >9.5/10 across the UX dimensions |
| **Release** | 0.3.0 → 0.4.0 |
| **Supersedes for token/paging** | `2026-06-12-mcp-consumer-uplift-9.5-design.md` (v0.3.0) |

## Problem

The v0.3.0 consumer assessment is a fresh black-box pass (~45 live calls across
all 12 tools, including adversarial cursor forgery). It scores **9/10** overall
with **no functional bugs**. The weakest dimension is **Token efficiency (8/10)**,
dragging the average; everything else is 9–10. The gap to >9.5 is entirely
*polish on the agent-facing contract*: remove real per-call and full-mode token
redundancy, make a few messages/observability signals exact, and finish the
refresh-safe-paging story the v0.3.0 work started for `find_curations` only.

Grounded in the MCP `2025-11-25` spec (tools, pagination, structured output) and
current MCP token-efficiency guidance (response filtering / aggregation; return
only the fields the agent needs).

## Root-cause findings (verified in code)

Mapping each assessment finding to its mechanism in the codebase:

1. **Full-mode payload redundancy (Part-1 #1, Part-2 #5 — biggest token win).**
   - `get_gene_disease_assertion` full: `shaping.assertion_dict` emits
     `submitters[]` (per-submitter: classification, MOI, dates, report URL,
     criteria URL, PMIDs) **and** the service adds raw `submissions[]`
     (`shaping.submission_dict`) carrying the *same* harmonized fields again,
     **and** a top-level union `pmids` (a third PMID listing). `submitters[]`
     is built from the pre-aggregated `gene_disease` table; `notes`, `sgc_id`,
     `disease_original_*`, `version_number`, `submitted_run_date` exist **only**
     on raw `submissions`. The two arrays are not 1:1 (a submitter may file
     multiple submissions for one pair: `n_submissions ≥ n_submitters`), which
     is *why* both exist — but ~90% of fields duplicate.
   - `get_gene_curations` / `get_disease_curations` full: each pair carries
     per-submitter `submitters[].pmids` **and** a pair-level union `pmids`
     (`assertion_dict` `if mode == "full": out["pmids"]`).

2. **Citation boilerplate on error envelopes (Part-1 #2, Part-2 #6).**
   `_error_envelope` calls `_provenance_meta()` with no `response_mode`, hitting
   the `else` branch that emits the verbatim ~250-char `RECOMMENDED_CITATION`.
   A 0.06 ms `invalid_input` is then majority citation boilerplate. (Note: the
   *standard* success envelope already uses `citation_ref`; only `full` and
   *errors* carry the verbatim string — so the assessment's "standard/full"
   framing is half-resolved already. `full` is opt-in maximum detail; errors are
   the real waste.)

3. **`_meta` static-field repetition (Part-1 #3).** Every envelope repeats
   `unsafe_for_clinical_use`, `data_license`, and `gencc_release`.
   `unsafe_for_clinical_use` is a per-call safety signal (keep — domain is
   clinical-adjacent). `data_license` (`CC0-1.0`) is session-invariant *and* is
   already encoded in `citation_short` ("…CC0-1.0") and in the capabilities
   contract, so it is pure redundancy in token-sensitive modes. `gencc_release`
   is per-call freshness/provenance (keep — small, useful).

4. **`resolve_identifier` message ignores `kind` scope (Part-2 D1, Medium).**
   `GenCCService.resolve_identifier` raises one `NotFoundError`:
   "Could not resolve 'X' to a GenCC gene or disease." — even when `kind="disease"`
   searched diseases only.

5. **Silent batch dedup (Part-2 D2, Medium).** `_dedupe_batch` case-folds and
   drops duplicates, then `requested` is reported as the *deduped* length with
   no echo of what was folded. `get_genes_curations(["BRCA2","NOTAGENE","brca2"])`
   → `requested: 2` with no signal.

6. **`resolve_identifier` dual-arg silently dropped (Part-2 D3, Medium).**
   The tool sets `q = query if query is not None else identifier`; passing both
   `query` and a *different* `identifier` silently ignores `identifier`.

7. **Refresh-safe paging is `find_curations`-only (Part-2 D4, Medium).**
   `search_genes`, `search_diseases`, `get_gene_curations`,
   `get_disease_curations` page by raw `offset` with no release stamp.
   `truncation_block` already mints a release-bound `next_cursor` when given a
   `cursor_context`, but these callers pass none. A weekly refresh mid-walk can
   silently skip/dupe rows; the cursor's reject-on-stale guarantee is missing.

8. **Documentation gaps (Part-2 #7, #8).** Per-tool default `response_mode` is
   not stated in capabilities; the exact `has_conflict` tier semantics live only
   in prose; `ambiguous_query` has no reachable example and operational-only
   error codes (`rate_limited`/`upstream_unavailable`/`data_unavailable`) aren't
   marked as such.

## Out of scope (YAGNI / deliberate)

- **One-shot "answer" tool** (Part-1 #4): a new grounded entry point. A new tool
  is the largest-surface, lowest-marginal-score item; `next_commands` already
  makes search→get_* painless. Deferred; noted as a future enhancement.
- **Single-hit title auto-resolve for `get_*_curations`** (Part-2 #8): the
  current exact-match + redirect-to-search behavior is deterministic and the
  assessment calls it "correct." Auto-magic adds data-dependent nondeterminism.
  We *document* the exact-match contract instead of changing behavior.

## Design

Five workstreams. Each is independently testable; together they lift Token
8→≥9.5, Discoverability 9→10, Error-handling 9→10, Ergonomics 9→9.5+.

### WS1 — Full-mode de-duplication (Token)

**Principle:** every datum appears exactly once; `submitters[]` is the harmonized
per-submitter view, `submissions[]` is the *raw-extras* per-row view. No data is
removed from the response set — only duplication.

- **`get_gene_disease_assertion` full mode:**
  - Drop the top-level union `pmids` (it triplicates `submitters[].pmids` /
    `submissions[].pmids`; trivially derivable). Remove the `if mode == "full":
    out["pmids"] = a.pmids` branch in `assertion_dict`.
  - Slim `shaping.submission_dict` to the fields **not** already in
    `submitters[]` and **not** pair-constant. **Keep:** `sgc_id`,
    `submitter_title` (correlation key), `classification_title`, `moi_title`
    (a submitter may file divergent rows — keep per-row), `notes`,
    `disease_original_curie`, `disease_original_title`, `version_number`,
    `submitted_run_date`, `pmids` (per-row evidence link). **Drop (now sourced
    from `submitters[]` or the parent):** `disease_curie`, `disease_title`
    (pair-constant), `public_report_url`, `assertion_criteria_url`,
    `submitted_as_date`, `submitted_as_date_iso`.
  - Net: full-mode assertion payload shrinks materially; `notes` and all raw IDs
    are preserved; correlation by `submitter_title`.
- **`get_gene_curations` / `get_disease_curations` full mode:** drop the
  per-pair union `pmids` (same `assertion_dict` branch); `submitters[].pmids`
  remains.

**Contract change:** full-mode payload shape changes (fewer duplicated fields).
Documented in capabilities `response_modes`, `gencc://usage`, `gencc://reference`,
the tool descriptions, and CHANGELOG. Minor version bump (0.4.0).

### WS2 — Citation & static-field trimming (Token)

- **Errors → `citation_ref` only.** `_error_envelope` builds its `_meta` from a
  new minimal provenance path that emits `citation_ref` (and keeps
  `unsafe_for_clinical_use`, `gencc_release`) but **not** the verbatim citation
  and **not** `citation_short` (an error carries no claim to cite).
- **`data_license` trim.** Remove `data_license` from per-call `_meta` in
  `minimal`/`compact`/`standard` (already in `citation_short` for min/compact and
  always in capabilities). Keep it in `full` (the "everything" mode) and document
  it as session-invariant (`capabilities.data_license`). `unsafe_for_clinical_use`
  stays on **every** envelope (safety). `gencc_release` stays on every success
  envelope.
- Implementation: refactor `_provenance_meta` into a small, explicit policy
  (success-by-mode vs error) so the rules are readable and unit-testable.

### WS3 — Uniform refresh-safe paging (Ergonomics / D4)

Extend the existing release-stamped opaque cursor to **all** offset-paged tools.

- **New shared decoder** `cursor.decode_paged_cursor(token, *, current_release)
  -> dict` in `services/cursor.py`: decodes, validates version/shape, and
  rejects a stale release with the exact `find_curations` message ("Cursor was
  minted against GenCC release '…' but the current release is '…'; restart the
  sweep."). Raises `ValueError` (caller wraps as `InvalidInputError(field=
  "cursor")`). `find_curations` is refactored to use it (removes ~20 inline
  lines, offsetting service growth against the 600-LOC cap).
- **`search_genes`, `search_diseases`, `get_gene_curations`,
  `get_disease_curations`:** add an optional `cursor: str | None` param. When
  present, decode → restore `query`/`gene`/`disease` + `response_mode` + offset +
  limit from `flt`; ignore the raw args (cursor wins, like `find_curations`).
  Pass `cursor_context={"release": run_date, "filters": {...}}` to
  `truncation_block` so the truncation block mints `next_cursor`.
- **Tools:** when `truncated.next_cursor` is present, prepend a page-forward
  `cmd(<self>, cursor=...)` to `_meta.next_commands` (mirrors `find_curations`).
- **`get_genes_curations` / `get_diseases_curations`** (per-gene batch, no global
  offset) are unchanged; documented as non-paged batch tools.
- Net: the assessment's reject-on-stale guarantee now holds server-wide.

### WS4 — Correctness & observability (Error-handling)

- **WS4a — kind-scoped resolve message.** `resolve_identifier` `NotFoundError`
  text reflects `kind`: gene→"…to a GenCC gene.", disease→"…to a GenCC disease.",
  auto→"…to a GenCC gene or disease." Recovery `next_commands` stay as-is.
- **WS4b — batch dedup observability.** `get_genes_curations` /
  `get_diseases_curations` payloads add `received` (raw input length) and, when
  any duplicates were folded, a `duplicates` list of the dropped raw values.
  `requested` keeps its meaning (distinct queried) for back-compat; the headline
  notes folding when it occurred. `_dedupe_batch` returns `(ordered, duplicates)`.
- **WS4c — dual-arg precedence.** `resolve_identifier`: if both `query` and
  `identifier` are provided **and differ** (after strip), raise
  `InvalidInputError(field="query")` ("Pass only one of `query`/`identifier`…").
  Equal values pass. Description states `identifier` is an alias and only one may
  be set.

### WS5 — Documentation completeness (Discoverability)

All in `capabilities.py` static surface (so `capabilities_version` bumps once)
plus the `gencc://` text resources:

- **`tool_defaults`** map: each tool's default `response_mode` (e.g.
  `get_gene_disease_assertion: "standard"`, search/curation/find/`get_*s`:
  `"compact"`). Added to the hashed static surface.
- **`error_codes` reachability.** Replace the flat list with annotated entries
  marking `data_unavailable`/`upstream_unavailable`/`rate_limited` as
  *operational-only* (ingest/quota; not reachable from a well-formed query) and
  `ambiguous_query` with a reachable example. Keep a flat `error_codes_list` for
  back-compat consumers.
- **`ambiguous_query` example.** Identify a real symbol/title collision in the
  data (a token that is exactly an approved gene symbol **and** a harmonized
  disease title) by querying the DB at implementation time; document it as the
  worked example. If none exists, document that `ambiguous_query` is reachable
  only under such a collision and give the precise trigger condition.
- **`has_conflict` exact semantics** surfaced as structured data:
  `conflict_semantics: {supporting: [...], against: [...], excluded: [...]}`
  derived from `constants.SUPPORTING_CLASSIFICATIONS` /
  `AGAINST_CLASSIFICATIONS` (Animal Model Only / Supportive / Limited excluded).
- **Paging note:** `gencc://reference` + capabilities state that *all* paged
  tools now accept a release-bound `cursor` and that offsets/cursors are valid
  only for the shown `gencc_release`; batch `get_*s_curations` are non-paged.
- **Full-mode shape note:** document the WS1 split (`submitters[]` harmonized vs
  `submissions[]` raw-extras; correlate by `submitter_title`).
- Update `capabilities.token_cost_hints`, `response_fields` (`received`,
  `duplicates`, `tool_defaults`, `conflict_semantics`), and the output schemas
  in `schemas.py` (`received`, `duplicates`, `cursor` params surfaced).

## Components touched

| File | Change |
|------|--------|
| `services/shaping.py` | WS1: slim `submission_dict`; drop union `pmids` in `assertion_dict`; `truncation_block` callers unchanged |
| `services/gencc_service.py` | WS1 (drop submissions union), WS3 (cursor on 4 methods, shared decoder), WS4a/b/c |
| `services/cursor.py` | WS3: `decode_paged_cursor` shared helper |
| `mcp/envelope.py` | WS2: error provenance (citation_ref only), `data_license` mode policy |
| `mcp/tools/genes.py` | WS3: `cursor` param + page-forward on `search_genes`/`get_gene_curations`; WS4b headline |
| `mcp/tools/diseases.py` | WS3: `cursor` param + page-forward on `search_diseases`/`get_disease_curations` |
| `mcp/tools/assertions.py` | WS1: `submissions[]` description; WS4c dual-arg guard |
| `mcp/capabilities.py` | WS5: `tool_defaults`, annotated error codes, `conflict_semantics`, paging/full-mode notes, response_fields |
| `mcp/resources.py` | WS5: `gencc://usage` + `gencc://reference` text |
| `mcp/schemas.py` | WS5: `received`/`duplicates` props; `_META` `data_license` optionality already permissive |
| `constants.py` | none (vocab unchanged) |
| `CHANGELOG.md`, `pyproject.toml`, `uv.lock` | 0.3.0 → 0.4.0 |
| `tests/` | new + updated unit/integration coverage per workstream |
| `docs/mcp-consumer-assessment-v0.3.0.md` | append a "Resolution (v0.4.0)" section mapping each finding to its fix |

## Testing strategy

TDD per superpowers: a failing test per behavior change first.

- **WS1:** assertion full mode has no top-level `pmids`; `submissions[]` rows
  omit `disease_curie`/`public_report_url`/etc. but retain `notes`/`sgc_id`;
  `get_gene_curations` full pair has no union `pmids`; `submitters[].pmids`
  still present. Token-shrink assertion: full payload byte-size < pre-change.
- **WS2:** an `invalid_input` envelope `_meta` has `citation_ref`, no
  `recommended_citation`, no `citation_short`; success `compact`/`standard`
  `_meta` has no `data_license`; `full` retains it; `unsafe_for_clinical_use`
  present on all.
- **WS3:** each of the 4 tools: truncated page mints `next_cursor`; cursor
  round-trip returns the next page; stale-release cursor rejected with the
  release-mismatch message; malformed cursor → `invalid_input` field=`cursor`;
  `_meta.next_commands[0]` is the page-forward `cmd`.
- **WS4:** kind-scoped messages (3 variants); `received`/`duplicates` echoed on a
  folding batch; dual-arg differ → `invalid_input`, equal → ok.
- **WS5:** `capabilities_version` changes once; `tool_defaults`,
  `conflict_semantics`, annotated `error_codes` present and internally consistent
  with `constants`; `ambiguous_query` example validates against the live data (or
  the documented "no collision" condition holds).
- `make ci-local` green (format, lint, lint-loc ≤600, mypy strict, tests ≥85%).

## Risks & mitigations

- **Full-mode shape change breaks a consumer** — mitigated: pre-1.0 research-use
  server; the consumer *requested* this; documented + minor bump; no data lost
  (only de-duplicated).
- **600-LOC cap on `gencc_service.py` (currently 516)** — mitigated: cursor
  decode moves to `cursor.py`; `find_curations` inline block removed; measure
  with `make lint-loc` during execution and split `find/paging` helpers if it
  approaches 580.
- **Cursor on FTS-ranked search** — a raw-offset cursor can still skip/dupe
  *within* a release if ranking is unstable, but the release stamp delivers the
  valuable reject-on-stale guarantee (parity with `find_curations`); documented
  as offset-within-release, not keyset.

## Success criteria

Every v0.3.0 assessment finding is resolved or explicitly deferred with
rationale; `make ci-local` green; a re-run consumer assessment would score
**Token ≥9.5, Discoverability 10, Error-handling 10, Ergonomics ≥9.5, Overall
>9.5**. The assessment doc carries a Resolution section closing the loop.
