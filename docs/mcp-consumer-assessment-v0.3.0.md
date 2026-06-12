# GenCC-Link MCP - Consumer & Tester Assessment (v0.3.0)

Point-in-time evaluation of the GenCC-Link MCP server from the perspective of
an LLM consuming it, followed by a structured senior-tester report.

A prior assessment of server v0.1.0 lives in
`docs/mcp-consumer-assessment.md`; this document is a fresh pass against v0.3.0
and supersedes it for that release. Several v0.1.0 findings appear resolved in
v0.3.0 (multi-result headlines now summarize the set, e.g. "3 genes match
'SKI': SKI, SKIC2, SKIC3"; the pair field is now named `strongest_classification`
rather than `consensus_classification`).

| Field | Value |
|-------|-------|
| Date | 2026-06-12 |
| Server version | 0.3.0 |
| MCP protocol | 2025-11-25 |
| GenCC release | 2026-06-07 |
| capabilities_version | f8007316b48ed2e1 |
| Data scale | 29,846 submissions, 6,095 genes, 8,149 diseases, 18 submitters |
| Method | ~45 live tool calls across all 12 tools (happy paths, boundaries, malformed input, batch limits, paging, forged cursor) |

Research use only; not for clinical decision support. GenCC data is CC0-1.0.

---

## Part 1 - Consumer UX Rating

Ratings reflect the experience of an LLM agent calling the server, scale 1-10.

| Dimension | Score | Basis |
|-----------|-------|-------|
| Discoverability | 9/10 | One capabilities doc carries everything needed |
| Observability | 10/10 | Best-in-class for an MCP |
| Error handling | 9/10 | Structured, self-correcting |
| Speed | 9/10 | Server-side sub-25ms; network not measurable from client |
| Ergonomics / chaining | 9/10 | Uniform envelope, next_commands everywhere |
| Token efficiency | 8/10 | Strong mode system, but real redundancy in full mode |
| Overall | 9/10 | |

### Strengths

- Observability (10): every envelope carries `request_id` + server-side
  `elapsed_ms`. `get_gencc_diagnostics` exposes build provenance (source ETag,
  Last-Modified, run date, build duration, schema version, row/gene/disease
  counts), the refresh scheduler's live state, and the download quota
  (used_today / remaining). The `capabilities_version` content hash lets a warm
  client detect drift in near-zero tokens.
- Discoverability (9): `get_server_capabilities` is a single self-describing
  contract - tool list, the full 9-rank classification vocabulary,
  response-mode semantics, recommended workflows, parameter conventions, error
  taxonomy, per-tool token-cost hints, a response-field glossary, and resource
  URIs. Combined with `next_commands` on every response (success and error),
  the whole server is navigable without external docs.
- Error handling (9): a bad `classification` value returned
  `error_code: invalid_input`, a `field_errors` array pinpointing the bad
  field with the accepted set inline, `retryable: false`,
  `recovery_action: reformulate_input`, and a `next_commands` pointer back to
  `get_server_capabilities`.
- Speed (9): server-side timings ran 0.06-21.82 ms (local SQLite + FTS5). Only
  network/transport latency on the hosted deployment is not visible from the
  client, so this is a data-layer score.

### Improvements identified

1. Full-mode assertion payloads are ~2x redundant - the biggest token win. In
   `get_gene_disease_assertion` full mode the `assertion.submitters[]` array and
   the top-level `submissions[]` array carry nearly identical fields, and a
   top-level `pmids[]` re-lists the per-submitter PMIDs a third time. Make
   `submissions[]` opt-in or merge the two.
2. The full ~250-char `recommended_citation` repeats in every standard/full
   envelope. Extend the existing `citation_ref` / `citation_short` indirection
   to standard/full and to error envelopes.
3. `_meta` static fields repeat on every call (`unsafe_for_clinical_use`,
   `data_license`, `gencc_release`). These are session-invariant and belong in
   the capabilities contract.
4. No one-shot "answer" tool. Sibling servers in the family offer a single
   grounded entry point; here a caller composes search -> get_*. `next_commands`
   makes that painless, so this is a nice-to-have.
5. Per-tool default `response_mode` varies (`get_gene_disease_assertion`
   defaults `standard`, the rest `compact`). Sensible, but state the per-tool
   default explicitly in capabilities.

---

## Part 2 - Senior MCP Tester Report

### Coverage

All 12 tools exercised across approximately 45 calls.

| Tool | Exercised |
|------|-----------|
| get_server_capabilities | full payload, version hash |
| get_gencc_diagnostics | provenance, refresh state, quota |
| search_genes | symbol, HGNC id, empty -> error |
| search_diseases | title (stemmed), OMIM id, truncation |
| get_gene_curations | compact/minimal/full, not-found, whitespace, bare-numeric |
| get_disease_curations | standard/minimal, lowercase title, partial -> error, offset-past-end |
| get_genes_curations | batch, unresolved, dup, 21>20 -> error |
| get_diseases_curations | batch with unresolved |
| get_gene_disease_assertion | full/compact/minimal, conflict, cross-pair miss |
| find_curations | 6 filter combos, ids_only, CURIE submitter, bad MOI, rare classes, no-filter, cursor round-trip, malformed + stale cursor |
| list_submitters | full roster |
| resolve_identifier | auto/gene/disease, id, bad kind, dual-arg |

### What holds up under adversarial testing (verified, not assumed)

- Refresh-safe cursor is real. A base64-forged cursor stamped with release
  `2026-05-01` was rejected precisely: "Cursor was minted against GenCC release
  '2026-05-01' but the current release is '2026-06-07'; restart the sweep."
  Page ordering is stable and alphabetical by gene across pages.
- Input validation is excellent. Every bad input returned structured
  `invalid_input` + `field_errors` + `recovery_action`, including a
  did-you-mean for MOI ("Recessive" suggests Autosomal recessive, X-linked
  recessive). Over-limit batch (21>20), empty query, no-filter, malformed
  cursor, and invalid `kind` were all rejected cleanly.
- Submission-level filtering is correct. `find_curations` matches at the
  submitter level and names the triggering submission in `matched`; submitter
  CURIEs (GENCC:000102) work as aliases for titles; OR-semantics across a
  classification list confirmed (257 hits for the two negative-rank classes).
- Conflict logic is sound. `has_conflict` fires exactly when strong-support
  (Definitive/Strong/Moderate) coexists with against (Disputed/Refuted/No-Known);
  compact assertion headlines append "- CONFLICT". Neutral tiers
  (Supportive/Limited) correctly do not trigger it.
- Resolution is forgiving where it should be. Case-insensitive symbols and
  titles, whitespace trimming (" brca2 " resolved), HGNC-id and OMIM-id paths
  all work; unresolved batch inputs return success with a structured
  `unresolved[]`.
- Graceful boundaries. Offset past the end returns count:0, total:20, genes:[]
  with empty next_commands rather than erroring.

### Defects and issues

Medium:

1. `resolve_identifier` error message ignores the `kind` scope. With
   kind="disease", query="BRCA2" the message reads "Could not resolve 'BRCA2'
   to a GenCC gene or disease" - but it only searched diseases. The text should
   say "to a GenCC disease."
2. Batch dedup is silent. `get_genes_curations(["BRCA2","NOTAGENE","brca2"])`
   returned requested:2 - it case-folded BRCA2/brca2 into one before counting
   and dropped the duplicate with no echo. Echo a duplicates/normalized block or
   set requested to the raw input length.
3. `resolve_identifier` silently ignores `identifier` when `query` is also
   passed. query="SKI", identifier="BRCA2" returned SKI with no signal that the
   aliased arg was dropped.
4. Refresh-safe paging is find_curations-only. search_genes / search_diseases /
   get_*_curations page by raw offset with no release stamp, so deep paging
   across a weekly refresh can skip/dupe. Either extend the cursor pattern or
   document that only find_curations paging is refresh-safe.

Low / documentation:

5. Full-mode payload redundancy (biggest token sink). In get_gene_curations
   full, each disease carries per-submitter pmids and a disease-level union
   pmids[]. In get_gene_disease_assertion full, assertion.submitters[] and
   top-level submissions[] are ~90% identical and pmids is unioned a third time.
   Gate the union arrays behind a flag or drop them.
6. Errors carry the full ~250-char recommended_citation. A 0.06 ms
   invalid_input response is majority citation boilerplate. Use citation_ref in
   error envelopes.
7. Two declared behaviors are unreachable from outside. ambiguous_query only
   fires when a string is exactly both an approved symbol and a harmonized
   title; rate_limited / upstream_unavailable / data_unavailable are
   ingest/quota-only. Provide a documented example/fixture for ambiguous_query
   and mark which error codes are operational-only.
8. get_*_curations title input is exact-only. "Noonan" -> not_found (correctly
   redirected to search_diseases), while "noonan syndrome" resolves. A
   single-unambiguous-hit auto-resolve would save a round trip. Also state the
   per-tool default response_mode in capabilities.

### Recommended changes, prioritized

1. Trim full-mode redundancy (#5) and drop the full citation from error
   envelopes (#6) - pure token wins, no behavior change.
2. Fix the kind-scoped resolve message (#1) and surface batch dedup / dual-arg
   precedence (#2, #3) - correctness and observability, small edits.
3. Decide on cross-tool paging consistency (#4) - either give search/curation
   paging the release-stamped cursor or document the limitation.
4. Documentation: precise has_conflict semantics, a reachable ambiguous_query
   example, operational-only error codes, and per-tool default modes (#7, #8).

### Verdict

No functional bugs - every tool returned correct data, validated inputs
rigorously, and the standout cursor refresh-safety guarantee held up to a
forged-cursor attack. The findings are polish, not breakage: the actionable
wins are full-mode payload slimming and trimming citation boilerplate from
errors; the rest are message-accuracy and documentation fixes. This is a
mature, well-instrumented server.

---

## Appendix - notable evidence (request ids)

| Observation | request_id |
|-------------|-----------|
| Stale-release cursor rejected by release stamp | 788baa4636ba |
| Malformed cursor rejected | 38a1dcb5d288 |
| Cursor round-trip across pages (offset 3 -> 6) | 5d37db8d1b06 |
| did-you-mean on invalid MOI ("Recessive") | b0caa29b0222 |
| >20 batch cap enforced | 2b548142a283 |
| Silent case-insensitive batch dedup (requested:2 of 3) | df9ae91c851c |
| Conflict surfaced in compact headline (BRIP1) | cec4aa75a346 |
| Submitter CURIE filter (GENCC:000102) | 1f5cf9e69f41 |
| Negative-rank classes, OR semantics (257 hits) | e240c893bdee |
| Offset past end returns empty set gracefully | b7cd56af8fdc |
| Partial title "Noonan" -> not_found, redirect to search | 9c036852c883 |

---

## Resolution (v0.4.0)

Every finding above is resolved or explicitly deferred with rationale. See
`docs/superpowers/specs/2026-06-12-mcp-consumer-uplift-v0.4.0-design.md` and the
`## [0.4.0]` CHANGELOG entry. No data-correctness bugs were reported; the work is
token-efficiency, paging consistency, message accuracy, and documentation.

### Part 1 - Consumer UX improvements

| # | Improvement | Status | What changed |
|---|-------------|--------|--------------|
| 1 | Full-mode assertion ~2x redundant | Resolved | Union `pmids` dropped; raw `submissions[]` slimmed to raw-extras (de-dup vs `submitters[]`); per-submitter PMIDs retained |
| 2 | Full citation repeats in standard/full | Resolved | Standard already used `citation_ref`; errors now `citation_ref`-only; `full` keeps the verbatim citation by design (it is the maximum-detail mode) |
| 3 | `_meta` static fields repeat | Resolved | `data_license` emitted only in `full`; documented as session-invariant in capabilities; `unsafe_for_clinical_use` kept on every envelope (safety) |
| 4 | No one-shot "answer" tool | Deferred | A new grounded entry point is the largest-surface, lowest-marginal item; `next_commands` already makes search→get_* painless. Noted as a future enhancement |
| 5 | Per-tool default `response_mode` not stated | Resolved | `tool_defaults` map added to the capabilities contract |

### Part 2 - Tester defects

| # | Severity | Defect | Status | What changed |
|---|----------|--------|--------|--------------|
| 1 | Medium | `resolve_identifier` message ignores `kind` | Resolved | Message reflects gene / disease / gene-or-disease scope |
| 2 | Medium | Batch dedup silent | Resolved | `received` + `duplicates[]` echoed; headline notes folding |
| 3 | Medium | `resolve_identifier` drops `identifier` when `query` set | Resolved | Conflicting aliases now return `invalid_input` |
| 4 | Medium | Refresh-safe paging is `find_curations`-only | Resolved | Release-bound cursor extended to `search_*` and `get_*_curations` |
| 5 | Low | Full-mode payload redundancy | Resolved | Same as Part-1 #1 |
| 6 | Low | Errors carry the full citation | Resolved | Error envelopes carry `citation_ref` only |
| 7 | Low/doc | `ambiguous_query` example + operational-only codes | Resolved | `ambiguous_query_example` + annotated `error_codes` (`operational_only`) |
| 8 | Low/doc | Title input exact-only; per-tool default modes | Resolved (docs) / Deferred (auto-resolve) | Per-tool defaults + exact-match contract documented; single-hit auto-resolve deferred (keeps deterministic redirect-to-search behavior) |
