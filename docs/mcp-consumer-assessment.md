# GenCC-Link MCP - Consumer Assessment

Assessment of the `gencc-link` MCP server from the perspective of an LLM client
consuming the tools over the wire. Two parts:

1. **LLM Consumer UX Assessment** - dimensional ratings of the day-to-day
   experience of calling the server.
2. **Senior MCP Tester Evaluation** - a structured test campaign across all 12
   tools with findings and prioritized recommendations.

- **Date:** 2026-06-12
- **Server version:** 0.1.0
- **MCP protocol:** 2025-11-25
- **Data release:** GenCC 2026-06-07 (29,846 submissions; 6,095 genes; 8,149
  diseases; 18 submitters)
- **Method:** ~35 live tool calls across three waves (happy paths, all four
  response-mode tiers, pagination boundaries, batch limits, cross-ontology
  resolution, filter validation, deliberate error/edge cases).

---

## Part 1 - LLM Consumer UX Assessment

**Verdict: 9/10 overall.** One of the better-built MCP servers in use. It does
the friction-reducing things deliberately rather than accidentally: cheap
discovery, real token tiers, ready-to-call next steps, per-call tracing,
consistent safety/citation hygiene. The gaps are small and mostly cosmetic.

| Dimension | Score | Basis |
|---|---|---|
| Speed | 10 | Server-side `elapsed_ms` of 0.2-22 ms on every call (local SQLite). |
| Discoverability | 9 | `get_server_capabilities` is a genuine one-stop map. |
| Token efficiency | 9 | Real, layered controls - not just a default. |
| Observability | 9 | Per-call trace id + deep build provenance. |
| Safety / citation hygiene | 9 | Consistent and machine-actionable. |
| Workflow / chaining | 8 | `next_commands` is great but under-populated on batch/multi-hit. |
| Error handling / robustness | 8 | Strong, well-documented contract. |

### Discoverability (9)
`get_server_capabilities` is the gold standard for an LLM client: tool
inventory, the full classification rank vocabulary, response-mode semantics,
`recommended_workflows` as literal call recipes, `parameter_conventions`, the
error-code taxonomy, a `response_fields` glossary, and the live
`inheritance_modes` enum. Tool descriptions are self-contained enough to build
valid calls without reading the doc first. The `capabilities_version` content
hash (echoed by diagnostics) lets a warm client skip re-fetching a large static
doc with a near-zero-token drift probe.

### Token efficiency (9)
Four-tier `response_mode` (minimal -> compact -> standard -> full) with compact
as the default, `ids_only` paging on `find_curations`, `limit_per_gene` /
`limit_per_disease` caps, batch tools that collapse N round-trips into one,
published `token_cost_hints`, and the `citation_ref`-instead-of-full-citation
trick in compact mode. The one tradeoff: compact forces a second round-trip to
`gencc://citation` when a verbatim citation is needed.

### Observability (9)
Every envelope carries `request_id` + `elapsed_ms`. Diagnostics expose source
ETag/Last-Modified, row/gene/disease/submitter counts, schema version, build
timestamp and duration, the refresh-scheduler state, and the download-quota
counter (`used_today` / `remaining`). Better instrumentation than most
production APIs.

### Workflow / chaining (8)
`headline` + `_meta.next_commands` let a client advance without guessing the
next tool, on both success and error envelopes. Held back from a 9 by two
issues confirmed in Part 2: batch/multi-hit responses populate `next_commands`
with only one item, and multi-result `headline` text describes only the first
hit.

### Error handling (8)
Excellent documented contract - a real error taxonomy, `invalid_input`
returning the accepted vocabulary, validation of submitter/MOI against the live
roster, and `next_commands` present on error envelopes. Rated partly on the
documented surface in the first pass; fully exercised in Part 2.

### Obvious improvements (from this pass)
1. Fix multi-result headlines so they summarize the set, not just row 1.
2. Populate `next_commands` per-item on batch calls.
3. Declare `outputSchema` / return structured content (responses are JSON text).
4. Optionally inline a short citation stub in compact mode.

---

## Part 2 - Senior MCP Tester Evaluation

**Headline verdict: solid, ships above the typical MCP quality bar. No blockers,
no correctness failures in the returned data.** The defects are in presentation
and naming, not in the data layer. The most important one (F1) causes real
information loss for an LLM consumer because it defeats the server's own
"read the headline" contract.

### Coverage and verdict per tool

| Tool | What was exercised | Verdict |
|---|---|---|
| get_server_capabilities | full surface, version hash | Pass |
| get_gencc_diagnostics | provenance, quota, scheduler | Pass |
| search_genes | compact/minimal/standard, multi-hit, prefix | Headline/next_commands defect |
| search_diseases | title/empty/paging (1920 hits), OMIM-shaped | Same headline defect |
| get_gene_curations | minimal/compact/full, offset=6 (tail), offset=100 (empty), not_found | Pass |
| get_disease_curations | MONDO + OMIM input | Pass |
| get_genes_curations | batch, unresolved mix, >20 limit | next_commands defect |
| get_diseases_curations | batch, unresolved mix | next_commands defect |
| get_gene_disease_assertion | full/minimal, conflict pair, not_found | Pass |
| find_curations | no-filter guard, bad enum, multi-filter, has_conflict, ids_only, CURIE + lowercase | Pass (excellent validation) |
| list_submitters | full roster (18, matches diagnostics) | Pass |
| resolve_identifier | gene/disease/OMIM/title/not_found | Pass (ambiguous path untested) |

### What works (verified, not assumed)

- **The conflict-detection value-add is real and well-surfaced.**
  `get_gene_disease_assertion` on GNAS / progressive osseous heteroplasia
  (req `37fec3abc4f0`) returned `has_conflict: true` with submitters spanning
  Definitive (G2P) to No Known Disease Relationship (Ambry), and the headline
  ends in "-- CONFLICT." This is the analytical core and it delivers.
- **Error envelopes are best-in-class.** Failures carry `error_code`, a specific
  `message`, `retryable`, `recovery_action`, a `next_commands` recovery step,
  and a structured `field_errors` array. The bad-enum case (`7eb515e350c9`)
  names the offending value and lists the full accepted vocabulary; the
  no-filter guard (`0b44903e1b2d`) and the >20 batch cap (`13ffa74e3a11`) both
  fire cleanly.
- **Resolution is robust across ontologies and formatting.** OMIM:300855 ->
  MONDO:0010457 (Ogden) end-to-end; submitter filter accepts both the title and
  the `GENCC:000102` CURIE; classification matches case-insensitively
  (`"definitive"` worked).
- **Pagination is consistent and safe.** Uniform `truncated` block
  (`total` / `returned` / `next_offset` / `hint`) across search, curation, and
  find tools; `offset=6` returned the correct tail and `offset=100` returned an
  empty set gracefully (no error, empty `next_commands`).
- **Response-mode tiers are meaningfully distinct.** `full` adds raw submission
  rows with `sgc_id`, `notes`, normalized `pmids`, and `disease_original_curie`
  provenance (e.g. OMIM:166350 behind the MONDO id); `minimal` strips
  per-submitter detail. The token ladder is real.

### Findings, ranked by severity

**F1 - Medium-High - Multi-result `headline` describes only the first hit
(information loss).**
Every multi-row search narrates row 1 only, with no signal that more exist:
- `search_genes("BRCA")` -> `count: 2` but headline = "BRCA1 (HGNC:1100): 6
  disease(s)..." - BRCA2 is absent from the headline entirely (req
  `693d84a0767b`).
- `search_diseases("breast cancer")` -> `count: 8`, headline names only
  `breast cancer` (`c5b0476cab17`).
- `search_diseases("syndrome")` -> `count: 3 of 1920`, headline names only
  Crouzon (`5c7293fdf5fa`).

Capabilities bills `headline` as "the plain-English answer at the top of each
payload." A consumer that trusts the headline (which the design invites)
silently drops every result after the first.

**F2 - Medium - `next_commands` references only one item on multi-result and
batch responses.**
- `search_genes("BRCA")` offers only `get_gene_curations(HGNC:1100)` (BRCA1) -
  no chain to BRCA2.
- `get_genes_curations([BRCA2, FAKEGENE1, TP53])` offers only
  `search_genes(FAKEGENE1)` - it steers to the unresolved input and offers no
  follow-up for the two genes that resolved (req `203e00b370a6`).
- `get_diseases_curations` behaves identically (`c0f49b03812e`).

The chaining affordance is the server's signature feature; on its highest
fan-out responses it under-delivers.

**F3 - Medium - `consensus_classification` is the max-rank assertion, not a
consensus - misleading on conflicted pairs.**
In all observed cases the field equals the single strongest classification
present, not an agreement measure. On GNAS/POH it reports "Definitive" while a
submitter asserts No Known Disease Relationship and `has_conflict: true`. A
consumer reading `consensus_classification` alone would see "Definitive" for a
pair that is actively disputed. `min_classification` / `has_conflict` and the
"-- CONFLICT" headline mitigate this, but the field name implies agreement it
does not measure. Rename (e.g. `strongest_classification`) or document the exact
aggregation algorithm in capabilities.

**F4 - Low-Medium - No `outputSchema` / structured content.** All payloads
arrive as JSON-encoded text, so clients parse strings rather than receiving
validated structured output. A sibling in the same fleet (`uniprot-link`)
already advertises typed tools with `outputSchema`.

**F5 - Low - Heterogeneous dates passed through unnormalized.**
`submitted_as_date` mixes `"2017-08-29 00:00:00"` and ISO-8601
`"2024-08-29T00:00:00.000000Z"` within a single response (NAA10 full,
`af213f6d7f59`). Documented in `data_notes`, but a normalized ISO field would be
a cheap value-add.

**F6 - Low - Minimal-mode field/headline mismatch.**
`get_gene_curations(minimal)` drops `n_submitters` from the structured `gene`
block but the headline still asserts "6 submitter(s)" (req `7bd9c5bb750a`).

**F7 - Low - Compact mode omits an inline citation.** Compact returns only
`citation_ref: "gencc://citation"`, forcing a second round-trip to cite a
sourced answer.

**Coverage gap (disclosed):** No input was found that triggers the documented
`ambiguous_query` error code - `resolve_identifier` resolved every test cleanly.
A repro would need a string that exactly matches both a gene symbol and a
disease title; worth a dedicated test fixture.

### Recommended changes, prioritized

1. **Fix multi-result headlines (F1).** For `count > 1`, summarize the set -
   e.g. "2 genes match 'BRCA': BRCA1, BRCA2 (both Definitive)" or at minimum
   "showing 3 of 1920; top hit: ...". Highest impact: prevents silent result
   loss.
2. **Enrich `next_commands` on multi-result/batch responses (F2).** Emit one
   follow-up per resolved entity (capped), keeping the unresolved-recovery hint
   as an addition rather than the only entry.
3. **Disambiguate `consensus_classification` (F3).** Rename to reflect
   "strongest," or document the aggregation precisely. Optionally add a true
   agreement signal (modal classification or submitter spread).
4. **Declare `outputSchema` and return structured content (F4).**
5. **Add a normalized ISO date field (F5)** alongside the verbatim
   `submitted_as_date`.
6. **Tidy minimal-mode parity (F6)** and **add a compact citation stub (F7).**
7. **Add an `ambiguous_query` test fixture** to close the coverage gap.

### Overall

**9/10.** The data layer, validation, error contract, and conflict analysis are
excellent, and nothing was found wrong in the returned facts. The defects are
presentational - F1 is the one to treat as a near-term fix because it defeats
the server's own "read the headline" contract. Address F1-F3 and this is a 10.

---

## Appendix - notable evidence (request ids)

| Observation | request_id |
|---|---|
| Conflict surfaced in headline (GNAS/POH) | `37fec3abc4f0` |
| Bad-enum error lists accepted vocabulary | `7eb515e350c9` |
| No-filter guard on find_curations | `0b44903e1b2d` |
| >20 batch cap enforced | `13ffa74e3a11` |
| Multi-hit headline names only first gene (BRCA1) | `693d84a0767b` |
| Batch next_commands points only at unresolved input | `203e00b370a6` |
| offset=100 returns empty set gracefully | `8f684e96dad1` |
| OMIM -> MONDO resolution end-to-end | `30e0ac241bfc` |
| Heterogeneous date formats in one payload | `af213f6d7f59` |
