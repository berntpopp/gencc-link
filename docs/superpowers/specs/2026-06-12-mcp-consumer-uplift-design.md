# GenCC-Link MCP Consumer Uplift — Design

**Date:** 2026-06-12
**Author:** MCP engineering pass (autonomous)
**Goal:** Close every finding in `docs/mcp-consumer-assessment.md` (F1–F7 plus the
`ambiguous_query` coverage gap) and lift the consumer-facing quality from the
assessed **9/10** to **>9.5/10**, in line with the MCP 2025-11-25 spec and current
tool-design best practices.

## Source of truth

- Consumer assessment: `docs/mcp-consumer-assessment.md` (35 live tool calls,
  protocol 2025-11-25, server 0.1.0).
- MCP spec (2025-06-18 / 2025-11-25, identical structured-output language):
  `structuredContent` is a sibling of `content`; an `outputSchema`, when present,
  is a contract the server **MUST** conform to and clients **SHOULD** validate;
  servers **SHOULD** also emit the serialized JSON as a text block (dual emission).
- Anthropic "Writing effective tools for AI agents": prefer natural-language /
  non-misleading field names; return high-signal data; expose verbosity controls;
  give actionable next steps and errors.

## Empirically verified current state (not assumed)

1. **Structured content already works.** Every tool returns a `dict`, so FastMCP
   3.4.2 already emits `structuredContent` *and* a JSON text block. The existing
   test-suite reads `result.structured_content`.
2. **`outputSchema` is contentless.** All 12 tools advertise
   `{"type":"object","additionalProperties":true}` with **no** properties — clients
   cannot validate or introspect field shapes. This is the real F4 gap (narrower and
   safer than "add structured content").
3. **`output_schema=` is supported** on `@mcp.tool` in FastMCP 3.4.2: it is
   advertised verbatim and structured content still conforms with extra fields
   preserved (`additionalProperties: true`). Verified by probe.
4. **`consensus_classification` is the max-rank title.** `aggregate_gene_disease`
   sets it to `_title_for_rank(submitters, max(ranks))` — it is the *strongest*
   assertion, confirming F3.
5. **`AmbiguousQueryError` is unreachable.** It exists in the taxonomy and the
   envelope maps it, but no code path raises it (confirming the coverage gap).

## Scope & guardrails

- **No SQLite schema change, no DB rebuild.** The physical column
  `gene_disease.consensus_classification` stays; the rename happens only at the
  consumer-facing boundary (model field + shaped output + headline), translated in
  the existing `assertion_from_row` mapping layer. This keeps `schema_version = 1`
  and avoids the download-quota'd rebuild path. (Confirmed every change below is
  reachable without touching `schema.sql`/the build SQL.)
- **File-size discipline (<600 LOC/module)** respected; F4 schemas live in a new
  `gencc_link/mcp/schemas.py` so tool modules stay lean.
- **Read-only, research-use-only contract** unchanged.
- **Out of scope (considered, declined):** setting MCP `isError: true` on error
  envelopes (SEP-1303). The server deliberately returns a structured error *body*
  (`success:false`, `error_code`, `recovery_action`, `next_commands`) as a normal
  result so the model always sees the self-correction payload; flipping `isError`
  risks clients hiding that body. Documented as a conscious choice. Tool names
  already satisfy the 2025-11-25 naming charset.

---

## F1 — Multi-result headline summarizes the set (information-loss fix)

**Problem:** `search_genes`/`search_diseases` set `headline = <first hit only>`, so
a consumer that trusts the headline silently drops every result after row 1.

**Design:** Add set-aware headline builders in `services/shaping.py`:

- `genes_search_headline(query, hits, total)` and
  `diseases_search_headline(query, hits, total)`.
- `count == 1` → the existing rich single-entity headline (`gene_headline` /
  `disease_headline`).
- `count > 1` → e.g.
  `"2 genes match 'BRCA': BRCA1, BRCA2."` and, when the page is a slice of a larger
  set, `"3 of 1920 diseases match 'syndrome': Crouzon syndrome, …, +2 shown."`
  Names are capped at 5 with a `+N more` suffix; when `total > returned`, the
  headline leads with `"<returned> of <total>"`.
- `services.search_genes` / `search_diseases` call the new builder (replacing the
  `hits[0]`-only line). `count == 0` keeps today's behavior (no `headline` key).

**Verification:** unit tests in `test_shaping.py` (single/multi/sliced cases assert
all returned symbols appear and `+N more` is correct); `test_tools.py` asserts the
multi-hit `search_genes("…")` headline names every returned symbol.

## F2 — `next_commands` covers every resolved entity (capped)

**Problem:** Multi-result and batch responses populate `next_commands` with one
item (and batch points only at the *unresolved* input).

**Design:** `mcp/next_commands.py`, new cap `_MAX_NEXT_COMMANDS = 5`:

- `after_search_genes(curies, query)`: on hits → one `get_gene_curations(gene=c)`
  per returned curie, capped. Zero-hit cross-over to `search_diseases(query)`
  unchanged.
- `after_search_diseases(curies, query)`: symmetric with `get_disease_curations`.
- `after_genes_curations(payload)`: **resolved drill-downs first** — one
  `get_gene_disease_assertion(gene, top_disease)` per resolved gene (capped) — then,
  if any unresolved, append a single `search_genes(query=<first unresolved input>)`
  recovery step (an addition, no longer the only entry). Total capped at
  `_MAX_NEXT_COMMANDS`.
- `after_diseases_curations(payload)`: symmetric.

**Verification:** `test_next_commands.py` (per-entity fan-out, cap enforced,
unresolved recovery present-but-not-sole). Update
`test_tools.py::test_genes_curations_partial_next_command` to assert the
`search_genes(NOTAGENE)` recovery command is **present** alongside the resolved
drill-down, rather than being first.

## F3 — Rename `consensus_classification` → `strongest_classification`

**Problem:** The field name implies agreement it does not measure; on a conflicted
pair it reads "Definitive" while a submitter asserts No Known Disease Relationship.

**Design (rename at the API boundary only):**

- `models/records.py`: `GeneDiseaseAssertion.consensus_classification` →
  `strongest_classification` (description: "Strongest (highest-rank) classification
  asserted by any submitter; not an agreement measure — see `has_conflict` /
  `min_classification`"). Internal `consensus_rank` stays (never emitted).
- `data/queries.py::assertion_from_row`:
  `strongest_classification=row["consensus_classification"]` (DB column unchanged;
  this mapping layer is the translation point — comment added).
- `services/shaping.py`: emitted key `consensus_classification` →
  `strongest_classification`; `assertion_headline` uses `a.strongest_classification`
  and reworded ("strongest = …" with the existing `range …` / `— CONFLICT` spread).
- `services/consensus.py` `Aggregate` and the ingest write path keep their internal
  `consensus_classification` names (they map 1:1 to the DB column).
- **Docs/discovery:** `mcp/resources.py` reference note, `mcp/capabilities.py`
  `response_fields` (add a precise `strongest_classification` definition + the
  aggregation algorithm: "max rank across submitters; conflict and range are
  reported separately"), `docs/architecture.md`, `docs/usage.md`,
  `docs/MCP_CONNECTION_GUIDE.md`, `README.md`.
- No backward-compat alias (pre-1.0; an alias would re-introduce the misleading
  name). `server_version` bumps `0.1.0 → 0.2.0`; `capabilities_version` re-hashes
  automatically so warm clients re-fetch.

**No new metric.** `min_classification`, `classification_titles`, and `has_conflict`
already express spread; adding a modal/agreement field is YAGNI for this fix.

**Verification:** update `test_shaping.py`, `test_service.py`, `test_repository.py`
to the new field; `test_consensus.py`/`test_ingest.py` keep the internal/DB name. A
grep gate confirms no consumer-facing `consensus_classification` remains.

## F4 — Declare a meaningful `outputSchema` for every tool

**Problem:** Contentless schemas defeat client-side validation/introspection;
sibling `uniprot-link` advertises typed tools.

**Design:** New `gencc_link/mcp/schemas.py`:

- Reusable fragments: `_META` (request_id, elapsed_ms, response_mode, data_license,
  unsafe_for_clinical_use, gencc_release, recommended_citation, citation_ref,
  citation_short, next_commands[{tool, arguments}]); error props (error_code,
  message, retryable, recovery_action, field_errors); a `tool_output_schema(**top)`
  builder that emits `{type:object, properties:{success, headline, _meta, …error…,
  **top}, required:["success"], additionalProperties:true}`.
- Per-tool top-level properties documenting the high-signal fields (e.g. `genes`,
  `diseases`, `gene`, `disease`, `assertion`, `submissions`, `results`,
  `unresolved`, `count`, `total`, `truncated`, `filters`, `query`, plus
  capabilities/diagnostics-specific blocks).
- `additionalProperties: true` throughout so `response_mode` variance and optional
  blocks always conform (satisfies the spec's MUST-conform rule while still giving a
  real field glossary). Errors share the schema (their fields are optional).
- Wire `output_schema=<schema>` into all 12 `@mcp.tool(...)` registrations.

**Verification:** a probe-style test asserts each tool's `outputSchema` now has a
non-empty `properties` set and that `success`/`_meta` are described; existing
`structured_content` tests continue to pass (conformance preserved).

## F5 — Normalized ISO date field

**Problem:** `submitted_as_date` mixes `"2017-08-29 00:00:00"` and
`"2024-08-29T00:00:00.000000Z"` within one response.

**Design:** Pure helper `normalize_submitted_date(raw) -> str | None` in
`services/shaping.py`, normalizing to an ISO-8601 **date** (`YYYY-MM-DD`, the
reliably-present comparable granularity): handle space- and `T`-separated
datetimes, trailing `Z`/microseconds, and bare dates; return `None` on unparseable
input (no exceptions). Emit `submitted_as_date_iso` alongside the verbatim value in
`_submitter_dict` (standard/full) and `submission_dict` (full). The verbatim field
is retained unchanged. Update capabilities `data_notes`/`response_fields`.

**Verification:** `test_shaping.py` parametrized cases for each observed format plus
a junk-string → `None` case.

## F6 — Minimal-mode field/headline parity

**Problem:** `get_gene_curations(minimal)` drops `n_submitters` from the `gene`
block but the headline still asserts "6 submitter(s)".

**Design:** Keep `n_submitters` in the always-present set of
`gene_summary_dict` / `disease_summary_dict` (it is cited by the headline and
minimal is documented as "ids + headline + **counts** only"). `n_submissions`
stays omitted in minimal (finest-grained, not cited). One extra int per summary.

**Verification:** update the two `test_shaping.py` minimal tests to assert
`n_submitters` present and `n_submissions` absent.

## F7 — Inline citation stub in compact/minimal

**Problem:** Compact returns only `citation_ref`, forcing a round-trip to cite a
sourced answer.

**Design:** Add `CITATION_SHORT = "GenCC (thegencc.org), CC0-1.0"` to
`constants.py`. In `envelope._provenance_meta`, for `minimal`/`compact` emit
`citation_short` alongside `citation_ref` (full verbatim citation stays behind the
ref / standard+full). The short form is clearly an attribution stub, not a
substitute for `recommended_citation`. Glossary updated.

**Verification:** `test_envelope.py`/`test_tools.py` assert `citation_short` present
in compact, `recommended_citation` (not `citation_short`) present in standard/full.

## Coverage gap — make `ambiguous_query` reachable

**Problem:** No input triggers the documented `ambiguous_query` code.

**Design:** In `services.resolve_identifier`, `kind='auto'` only: when the query
resolves to **both** a gene and a disease, raise
`AmbiguousQueryError("'<q>' matches both a gene (<curie>) and a disease (<curie>); "
"re-run with kind='gene' or kind='disease'.", candidates=[gene_curie, disease_curie])`
instead of returning both. `kind='gene'`/`'disease'` are unaffected. Update the
tool description (auto resolves to a single kind; genuine collisions return
`ambiguous_query`). Add `ambiguous_query` recovery in
`next_commands.recovery_commands` for `resolve_identifier`:
`[get_gene_curations(gene=query), get_disease_curations(disease=query)]`.

**Verification:** `test_service.py` uses a tiny in-test fake repository (resolving
one token as both gene and disease) so the shared `sample.tsv` counts are untouched;
asserts `AmbiguousQueryError` + candidates. `test_tools.py` asserts the error
envelope `error_code == "ambiguous_query"` with the two recovery commands.

---

## Cross-cutting deliverables

- **Version & changelog:** bump `0.1.0 → 0.2.0` (pyproject); CHANGELOG entry
  summarizing the rename (breaking field), new `outputSchema`, `submitted_as_date_iso`,
  `citation_short`, richer headlines/next_commands, and reachable `ambiguous_query`.
- **Docs:** architecture, usage, connection guide, README field references and the
  capabilities/reference resources reconciled with the rename and new fields.
- **Gate:** `make ci-local` green (ruff, mypy strict, lint-loc <600, ≥85% coverage,
  unit tests). New behavior is TDD-first.

## Risks & mitigations

| Risk | Mitigation |
|---|---|
| Rename misses a doc/test reference | grep gate for consumer-facing `consensus_classification` after edits |
| `output_schema` over-constrains and breaks conformance | `additionalProperties:true` + required only `["success"]`; probe-verified |
| `ambiguous_query` change regresses existing resolve tests | only `kind='auto'` + both-match; no fixture token collides; fake repo for the new test |
| Headline/next_commands token bloat | names capped at 5, `next_commands` capped at 5 |
| Minimal-mode token creep (F6/F7) | one int + one short string only, both already justified by "counts only" / citation contract |

## Definition of done

All seven findings and the coverage gap resolved per above; `make ci-local` green;
`docs/mcp-consumer-assessment.md` cross-checked so each F-item maps to a shipped
change; server reads as ≥9.5/10 against the assessment's own rubric (no silent
result loss, full chaining fan-out, accurate field naming, typed tools, normalized
dates, minimal-mode parity, inline citation, reachable error taxonomy).
