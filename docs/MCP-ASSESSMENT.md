# GenCC-Link MCP — Consumer & Tester Assessment

| | |
|---|---|
| **Server** | `gencc-link` v0.2.0 (MCP protocol `2025-11-25`) |
| **Data release** | GenCC `2026-06-07` (29,846 submissions · 6,095 genes · 8,149 diseases · 18 submitters) |
| **Assessment date** | 2026-06-12 |
| **Evaluator** | Claude (LLM consumer of the live MCP surface) |
| **Method** | Black-box exercise of the live server: ~40 tool invocations across all 12 tools + all 5 resources |

This document collects two passes:

- **Part 1** — an LLM-consumer UX evaluation with 1–10 ratings per dimension and obvious improvements.
- **Part 2** — a senior-tester thorough test pass: per-tool verdicts, defects ranked by severity with reproduction inputs, and prioritized recommendations.

---

## Part 1 — LLM-Consumer UX Evaluation

Ratings are grounded in direct use of the server, not inspection of source.

| Dimension | Score | Basis |
|---|---|---|
| Speed / latency | 10 | Every data call 0.3–37 ms server-side (local SQLite + FTS5). Capabilities one-time at 50 ms. Nothing to wait on. |
| Discoverability | 9 | `get_server_capabilities` is a model example: tool list, ranked classifications, response-mode semantics, recommended workflows, parameter conventions, error codes, token-cost hints, a field glossary, and 5 backing resources. A `capabilities_version` content hash lets a warm client skip re-fetching. |
| Observability | 9 | `request_id` + `elapsed_ms` on every envelope; `get_gencc_diagnostics` exposes data freshness (run date, ETag, Last-Modified), row/gene/disease counts, build duration, refresh-scheduler state, and live download-quota usage. |
| Agent ergonomics / chaining | 9 | `_meta.next_commands` with ready-to-call `{tool, arguments}` on (almost) every response, plus a plain-English `headline` atop each payload. The next call rarely needs guessing. |
| Result honesty / pagination | 9 | Real `total` even when truncated, with `next_offset` + hint. No silent capping. |
| Error handling & recovery | 8 | The domain-error envelopes are excellent — `error_code`, actionable `message`, `retryable`, `recovery_action`, and a `next_commands` pointer. Docked for the inconsistency in Part 2 (D2). |
| Token efficiency | 8 | Four well-differentiated response modes; `citation_ref`/`citation_short` instead of the full citation in minimal/compact; `ids_only` for cheap paging. Docked for repeated boilerplate and the assertion mode defect (D1). |
| **Overall** | **9** | A reference-grade `*-link` MCP. The gaps are refinements, not defects. |

### Obvious improvements (from Part 1)

1. **Surface the page-forward call in `next_commands` when truncated.** On a truncated result, `truncated.next_offset` says how to page, but `_meta.next_commands` points at the first row's assertion — an agent following `next_commands` mechanically never pages further.
2. **Route argument-validation errors through the structured envelope.** A wrong param name dumped raw Pydantic instead of the clean `{error_code, message, next_commands}` envelope.
3. **Trim per-call `_meta` boilerplate in standard/full.** Every envelope repeats `unsafe_for_clinical_use`, `data_license`, `gencc_release`, and (in standard/full) the ~250-char citation. Extending the "cite-by-ref, dereference once" pattern to all modes would shave a recurring tax on multi-call loops.

---

## Part 2 — Senior MCP Tester: Thorough Test Pass

### Coverage & overall verdict

Every tool works, returns well-formed envelopes, and is fast (0.06–50 ms server-side). The chaining contract (`next_commands`), conflict detection, input normalization, and injection safety are better than most MCPs. The pass surfaced **one reproducible behavioral defect**, **two contract inconsistencies**, and several nits. None are data-correctness bugs — the analytical output is trustworthy.

**Overall: 9/10.** Production-grade; the items below are the gap to 10.

### Per-tool results

| Tool | Verdict | Notes |
|---|---|---|
| `get_server_capabilities` | ✅ Pass | Exemplary self-description; `capabilities_version` hash enables drift-skip. |
| `get_gencc_diagnostics` | ✅ Pass | Freshness, ETag, build duration, refresh-scheduler state, live quota (0/20). |
| `search_genes` | ✅ Pass | FTS-backed; empty → `invalid_input`; injection-safe; `BRCA*` & lowercase OK. |
| `search_diseases` | ✅ Pass | No-match returns clean empty + cross-tool fallback (`→ search_genes`). |
| `get_gene_curations` | ✅ Pass | `minimal`/`compact` correctly reduce; lowercase & whitespace inputs resolve. |
| `get_disease_curations` | ✅ Pass | Accepts OMIM CURIE (`OMIM:182212` → MONDO); conflict logic correct. |
| `get_genes_curations` | ✅ Pass | Dedupes duplicate inputs; `>20` → `invalid_input`; all-unresolved still `success:true`. |
| `get_diseases_curations` | ✅ Pass | Mixed batch → `unresolved[]` + per-miss `next_commands`. |
| `get_gene_disease_assertion` | ⚠️ Pass w/ defect | `full` is rich (raw submissions, notes, PMIDs); **`minimal` is mis-wired — see D1.** |
| `find_curations` | ✅ Pass | Honest `total` + `truncated.next_offset`; deterministic order; OR across classifications; bounds-guarded. |
| `list_submitters` | ✅ Pass | 18 submitters w/ counts; consistent with diagnostics. |
| `resolve_identifier` | ✅ Pass | Exact match for HGNC/MONDO/OMIM/symbol; non-exact (`SGS`) → `not_found` + redirect to search. |

### Verified positives worth keeping

- **Conflict semantics are correct and verbalized.** `DAO` / amyotrophic lateral sclerosis (`HGNC:2671` / `MONDO:0004976`) returns `has_conflict:true` with headline *"…(range Moderate..Refuted Evidence) — CONFLICT"* — a supporting (Moderate) and against (Refuted Evidence) classification coexisting.
- **Case-insensitive filters, exactly as documented** (`gencc://reference`): `classification=["definitive"]` → 3,900; `submitter=["clingen"]`, `moi="autosomal dominant"` → 1,401.
- **PMID normalization corrects malformed source data.** ClinGen's free-text note for SKI contained a malformed `4736733`; the structured `pmids` array carried the corrected `24736733`.
- **Robust input normalization:** lowercase symbols (`brca2`), surrounding whitespace (`"  SKI  "`), and cross-reference CURIEs (`OMIM:182212` → `MONDO:0008426`) all resolve.
- **Injection-safe search:** `search_genes('BRCA2" OR 1=1; --')` returns `count:0` with no error or crash (parameterized FTS5).
- **Deterministic pagination:** an `offset=0` re-run returned byte-identical rows in identical order, so offset paging is safe against duplication/skips within a data version.
- **Operational transparency:** `get_gencc_diagnostics` surfaces refresh-scheduler state and the live 20/IP/day download quota.

### Findings (by severity)

#### D1 — `get_gene_disease_assertion` response-mode verbosity is inverted (Medium)

The verbosity ladder is non-monotonic: `compact` < `minimal` = `standard` < `full`.

- `compact` (req `dc560f7afb8a`) returns a lean `submitter_titles: [...names]`.
- `minimal` (req `13b83aaceee2`) returns the **full** `submitters[]` array — classification, MOI, both date formats, report URLs — **identical to `standard`** and heavier than `compact`.

This both violates the documented contract (`minimal` = "ids + headline + counts only") and inverts the token incentive: an agent choosing `minimal` to save tokens gets *more* than if it asked for `compact`. The `minimal` branch for this one tool appears to fall through to standard rendering.

**Fix:** make `minimal` emit summary-only (no `submitters[]`), so size is strictly `minimal ≤ compact ≤ standard ≤ full`.

#### D2 — Error-envelope surface is inconsistent (Low–Medium)

- **(a) Schema-level violations bypass the structured envelope.** `response_mode="ultra"` (a `Literal`) and a wrong arg name (`identifier=` vs `query=`) return a raw Pydantic dump with a `pydantic.dev` URL — no `error_code`, no `next_commands`, not agent-recoverable. Domain violations (bad classification/submitter/moi) by contrast return the polished envelope.
  **Fix:** catch validation errors at the tool boundary and re-wrap as `invalid_input`; optionally accept `identifier` as an alias for `query`.
- **(b) `next_commands` missing on shape/bounds errors.** Vocabulary errors (bad classification/submitter/moi) include `next_commands`; but empty query, `>20` batch, negative offset, and no-filter `find_curations` omit it — yet capabilities promises `next_commands` "on success **and error** envelopes."
  **Fix:** always attach `next_commands` (e.g., `→ get_server_capabilities` / the same tool with corrected args).

#### D3 — Offset pagination has no refresh-safe cursor (Low)

Ordering is deterministic (verified), so paging is correct *within a data version*. But it's position-based and the sort key is undocumented; the weekly refresh could shift rows mid-page-walk (silent skip/dup).

**Fix:** document that offsets are valid only within a given `gencc_release` (already in every envelope, so a client can detect drift), or switch to an opaque cursor.

#### D4 — Truncated results don't surface the page-forward call (Nit)

On a truncated `find_curations`, `truncated.next_offset` is correct, but `_meta.next_commands` points at row 1's assertion, not the `find_curations(offset=next_offset)` continuation — so an agent that mechanically follows `next_commands` never pages.

**Fix:** when `truncated` is present, prepend the continuation call to `next_commands`.

#### D5 — `field_errors[]` is undocumented (Nit)

The `invalid_input` envelope returns a useful `field_errors[]` array, but it isn't described in capabilities `response_fields` or `gencc://reference`. Document it.

#### D6 — `ambiguous_query` advertised but unreachable in testing (Nit)

It's in the error taxonomy, but `resolve_identifier` does exact-match only and returned `not_found` for non-exact input (`SGS`). Confirm the code path is wired, or drop it from the advertised set. Minor sibling: the "Did you mean" suggestion for `moi="Recessive"` proposed *X-linked recessive* over the more intuitive *Autosomal recessive* — suggestion ranking could prefer the closest edit-distance match.

### Recommended changes, prioritized

1. **Fix D1** — correct `get_gene_disease_assertion` `minimal` to be summary-only. The one change with both a correctness and a cost impact; ship first.
2. **Fix D2** — unify the error surface: wrap schema-validation errors into the structured `invalid_input` envelope, and always include `next_commands`. Restores the "every envelope is chainable" guarantee the server markets.
3. **Address D3/D4** — document offset/`gencc_release` paging semantics and add the page-forward `next_command` on truncation. Cheap; makes large sweeps robust and fully autonomous.
4. **Docs (D5/D6)** — add `field_errors` to the field glossary; verify or prune `ambiguous_query`.

The data layer, conflict analytics, observability, and chaining are all solid — these are polish, not blockers.

---

## Appendix — Test inventory

Representative calls exercised during the pass (inputs → observed outcome):

| Tool | Input | Outcome |
|---|---|---|
| `get_genes_curations` | `["BRCA2","NAA10"]` | 2/2 resolved; both strongest=Definitive, no conflict |
| `get_server_capabilities` | — | Full surface; `capabilities_version` `1604f03824d7c2a9` |
| `get_gencc_diagnostics` | — | run 2026-06-07; quota 0/20; scheduler pending |
| `search_genes` | `"BRCA"` / `"BRCA*"` / `""` | 2 hits / 2 hits / `invalid_input` (empty) |
| `search_genes` | `'BRCA2" OR 1=1; --'` | `count:0`, injection-safe |
| `search_diseases` | `"Shprintzen-Goldberg"` / `"zzzzzzzzzqqqq"` | 2 hits / clean empty + cross-tool fallback |
| `resolve_identifier` | `SKI` / `MONDO:0008426` / `OMIM:182212` / `SGS` | gene / disease / disease / `not_found` + redirect |
| `get_gene_curations` | `brca2` / `"  SKI  "` / `NOT_A_REAL_GENE_XYZ` | normalized resolve / normalized resolve / `not_found` |
| `get_disease_curations` | `MONDO:0008426` / `OMIM:182212` | SKI + FBN1 / same (OMIM→MONDO) |
| `get_gene_disease_assertion` | `SKI`/`MONDO:0008426` ×(minimal,compact,standard,full) | **D1: minimal == standard > compact** |
| `get_gene_disease_assertion` | `DAO`/`MONDO:0004976` | `has_conflict:true`, "— CONFLICT" headline |
| `get_gene_disease_assertion` | `BRCA2`/`MONDO:0008426` / `HGNC:99999999`/… | `not_found` (no link) / `not_found` (no gene) |
| `find_curations` | `Definitive` (offset 0 / 50 / -5) | 3,900 total; deterministic paging; `-5` → `invalid_input` |
| `find_curations` | `has_conflict:true` | 33 conflict pairs |
| `find_curations` | `["definitive"]` / `["clingen"]`+`"autosomal dominant"` | case-insensitive: 3,900 / 1,401 |
| `find_curations` | invalid submitter / classification / moi / no filter | structured `invalid_input` (+ suggestion for moi) |
| `get_genes_curations` | 21 genes / `["BRCA2","BRCA2","SKI"]` / 2 fakes | `>20` rejected / deduped to 2 / 0 resolved + `unresolved[]` |
| `list_submitters` | — | 18 orgs with submission/gene/disease counts |
| Resources | `gencc://usage,reference,license,citation` | all resolve; accurate and consistent |

---

## Resolution (v0.3.0, 2026-06-12)

All findings addressed: **D1** (minimal summary-only), **D2a** (validation errors →
structured `invalid_input` via `InputValidationMiddleware`), **D2b** (`next_commands`
on every error), **D3/D4** (release-bound opaque cursor + autonomous page-forward),
**D5** (`field_errors`, `cursor`/`next_cursor` documented), **D6** (`ambiguous_query`
reachability test + case-insensitive multi-suggestion hints), and the Part-1 citation
tax (cite-by-ref extended to `standard`). See
`docs/superpowers/specs/2026-06-12-mcp-consumer-uplift-9.5-design.md`,
`docs/superpowers/plans/2026-06-12-mcp-consumer-uplift-9.5.md`, and the 0.3.0
CHANGELOG entry.

*Research use only; not for clinical decision support. GenCC data: CC0-1.0, GenCC (thegencc.org).*
