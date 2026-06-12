# GenCC-Link — Gene Validity Lookup & MCP UX Assessment

> Generated 2026-06-12 from a live session against the `gencc-link` MCP server.
> GenCC release **2026-06-07** (29,846 submissions; 6,095 genes; 8,149 diseases; 18 submitters).
> Research use only — not for clinical decision support, diagnosis, or treatment without review by a genetics professional.

---

## Part 1 — Gene-disease validity status

GenCC harmonized consensus across member submitters. Neither gene has any conflicting assertions.

### BRCA2 (HGNC:1101)

8 disease associations from 6 submitters; strongest classification **Definitive**, no conflicts.

| Disease | Consensus | Inheritance | Submitters |
|---|---|---|---|
| BRCA2-related cancer predisposition | Definitive | AD | ClinGen |
| Fanconi anemia complementation group D1 | Definitive | AR | Ambry, ClinGen, Labcorp/Invitae, G2P |
| Breast-ovarian cancer, familial, susceptibility to, 2 | Definitive | AD | Ambry, Genomics England, Labcorp/Invitae |
| Pancreatic cancer, susceptibility to, 2 | Strong | AD | Genomics England |
| Sarcoma | Moderate | AD | Genomics England |
| Fanconi anemia | Supportive | AR | Orphanet |
| Hereditary breast ovarian cancer syndrome | Supportive | AD | Orphanet |
| Medulloblastoma | Limited | AD | Ambry |

### NAA10 (HGNC:18704)

4 disease associations from 7 submitters; strongest classification **Definitive**, no conflicts.

| Disease | Consensus | Inheritance | Submitters |
|---|---|---|---|
| NAA10-related syndrome | Definitive | X-linked | ClinGen, Broad CMG, PanelApp Australia |
| Ogden syndrome | Definitive | X-linked | Ambry, Labcorp/Invitae, Orphanet, G2P |
| Microphthalmia, syndromic 1 | Moderate | X-linked / Unknown | Ambry, Labcorp/Invitae, G2P |
| Microphthalmia, Lenz type | Supportive | X-linked | Orphanet |

**Summary:** Both genes have Definitive-level disease associations with no submitter conflicts — BRCA2 anchored in hereditary breast/ovarian cancer and Fanconi anemia D1, NAA10 in NAA10-related/Ogden syndrome (X-linked).

**Citation:** DiStefano MT, Goehringer S, Babb L, et al. The Gene Curation Coalition: A global effort to harmonize gene-disease evidence resources. *Genet Med.* 2022;24(8):1732-1742. doi:10.1016/j.gim.2022.04.017. Data: GenCC (thegencc.org), CC0 1.0.

---

## Part 2 — MCP user-experience assessment

Method: exercised the server end-to-end — `get_server_capabilities`, `get_gencc_diagnostics`, a deep `full`-mode `get_gene_disease_assertion`, a `minimal` vs `compact` token comparison on `get_gene_curations`, a submission-level `find_curations` filter, and a deliberate bad-gene error to probe error handling.

### Bottom line

**Overall: 9/10.** One of the better-engineered MCP servers. The envelope discipline is the standout: every response — success *and* error — carries a plain-English `headline`, a `request_id` + server-side `elapsed_ms`, provenance (`gencc_release`), and `_meta.next_commands` with ready-to-call `{tool, arguments}` next steps. When sent `BRCA9999`, the error returned `error_code: not_found`, a `recovery_action`, and `next_commands` pointing straight at `search_genes`. Self-healing by design.

### Ratings by dimension

| Dimension | Score | Why |
|---|---|---|
| Observability | 10 | `request_id` + `elapsed_ms` on *every* envelope; `get_gencc_diagnostics` exposes build provenance (ETag, last-modified, build duration), entity counts, refresh-scheduler state, **and** live download-quota headroom (`used_today`/`daily_quota`/`remaining`). |
| Discoverability | 9 | `get_server_capabilities` is exemplary — tool inventory, classification ranks, response-mode semantics, `recommended_workflows`, `parameter_conventions`, `error_codes`, `token_cost_hints`, MOI enum, and `data_notes` warning about messy passthrough fields. Five `gencc://` resources. `capabilities_version` hash for cache skipping. |
| Error handling | 9 | Structured envelope: `success`, documented `error_code`, actionable `message`, `retryable`, `recovery_action`, plus recovery `next_commands`. |
| Speed | 9 | Local SQLite/FTS5 — most calls returned in **0.1–0.8 ms** server-side. One outlier (below). |
| Ergonomics / consistency | 9 | Uniform envelope shape; `gene` accepts symbol or HGNC, `disease` accepts MONDO/OMIM/title; `headline` gives a quotable one-liner. |
| Token efficiency | 8 | Four graduated `response_mode`s that genuinely trim; `token_cost_hints` in kB; `minimal`/`compact` emit a short `citation_ref` instead of the ~300-char citation string, which only materializes in `standard`/`full`. |

### Highest-impact improvements

1. **Add a batch tool — biggest LLM-UX win.** The "BRCA2 and NAA10" request forced two `get_gene_curations` round trips. Multi-entity questions are the common case for an LLM. A `get_genes_curations(genes=[...])` / `get_diseases_curations(...)` batch (as `genereviews-link` does with `get_passages_batch`) would collapse N calls into one. Clearest gap.

2. **Profile `find_curations` — the one speed outlier.** It returned in **59 ms** vs sub-millisecond for everything else (~100–600× slower). Its classification/submitter/MOI filters match at the *submission* level, so this is likely a full scan or Python-side filter over the 29,846 submission rows. A composite index on the submission-level filter columns (or a precomputed match table) should bring it in line.

3. **Expose a lightweight version probe.** `capabilities_version` ships for cache invalidation, but checking it requires fetching the whole ~4 kB capabilities doc. Either echo `capabilities_version` in the tiny `get_gencc_diagnostics` payload, or add a near-zero-token ping returning just the hash + data freshness.

4. **Minor token trim.** `headline` restates facts already in structured fields, and there's no field-projection / `ids_only` mode for `find_curations` paging. Low priority given existing cost hints and citation deferral.

### Caveat (not the server's fault)

In the Claude Code harness all 10 tools start *deferred* behind `ToolSearch`, adding a cold-start step before any call. That's harness behavior, not server design — mitigated well by the MCP instructions string and `next_commands` once loaded.

**Net:** discoverability, observability, and error recovery are already best-in-class; the two concrete wins are a **batch tool** (round-trip efficiency) and an **index on `find_curations`** (the lone latency outlier).
