# GenCC-Link MCP — Consumer-Uplift to >9.5/10 (Design Spec)

> Historical record — this document records the design or plan as of its date. Current behavior is
> defined by implemented code, standards, release evidence, and tests.

| | |
|---|---|
| **Status** | Approved (autonomous goal directive) |
| **Date** | 2026-06-12 |
| **Author** | Claude (MCP engineer role) |
| **Source assessment** | `docs/MCP-ASSESSMENT.md` (scored 9/10 by an LLM consumer) |
| **Target** | >9.5/10 across the UX dimensions |
| **Release** | 0.2.0 → 0.3.0 |

## Problem

`docs/MCP-ASSESSMENT.md` is a black-box evaluation of the live `gencc-link` MCP
by an LLM consumer + senior-tester pass. It scores 9/10 ("reference-grade") and
enumerates one behavioral defect (D1), two contract inconsistencies (D2a/D2b),
and four nits (D3–D6), plus three Part-1 improvements. None are data-correctness
bugs. The gap to >9.5 is polish on the agent-facing contract: verbosity ladder
monotonicity, a uniformly chainable error surface, refresh-safe autonomous
paging, and lower per-call token tax.

This spec resolves **every** finding, grounded in the MCP `2025-11-25` tools
spec and FastMCP 3.4.2 internals (both verified against the installed code).

## Root-cause findings (verified in code)

1. **D1 — `minimal` is inverted (Medium).** `gencc_service.py:349` renders the
   assertion with `"standard" if mode == "minimal" else mode`, forcing the
   `minimal` branch to emit the full `submitters[]` array (identical to
   `standard`, heavier than `compact`). `shaping.assertion_dict` *already*
   early-returns a summary for `minimal` (`shaping.py:150`); the override
   defeats it. Verbosity becomes `compact < minimal == standard < full`.

2. **D2a — schema-validation errors bypass the envelope (Low–Med).** FastMCP
   builds a Pydantic `TypeAdapter` from each tool's signature and runs
   `type_adapter.validate_python(arguments)` inside `FunctionTool.run` *before*
   the tool body executes (`fastmcp/tools/function_tool.py:286+`). An invalid
   `response_mode` (a `Literal`) or an unknown arg name raises
   `pydantic_core.ValidationError` there — the body's `run_mcp_tool` try/except
   never sees it, so the client gets a raw/masked Pydantic dump with no
   `error_code`, no `next_commands`, not agent-recoverable. (Confirmed by
   FastMCP issue #1606.) The inner `call_tool(run_middleware=False)` re-raises
   `PydanticValidationError` *without* masking, so an `on_call_tool` middleware
   wrapped around it sees the **raw** error with `.errors()` intact.

3. **D2b — `next_commands` missing on shape/bounds errors (Low–Med).**
   `recovery_commands()` returns `[]` for empty-query, `>20`-batch,
   negative-offset, and no-filter `find_curations`, yet capabilities promises
   `next_commands` "on success **and error**."

4. **D3 — offset paging has no refresh-safe cursor (Low).** Ordering is
   deterministic within a data version, but offsets are position-based and the
   weekly refresh can shift rows mid-walk (silent skip/dup). MCP spec recommends
   opaque cursors.

5. **D4 — truncation doesn't surface the page-forward call (Nit).**
   `find_curations` `_meta.next_commands` points at row 1's assertion, not the
   continuation — an agent following `next_commands` mechanically never pages.

6. **D5 — `field_errors[]` undocumented (Nit).** Emitted by the `invalid_input`
   envelope but absent from capabilities `response_fields` and `gencc://reference`.

7. **D6 — `ambiguous_query` reachability + suggestion ranking (Nit).** The code
   path *is* wired (`resolve_identifier(kind="auto")` raising `AmbiguousQueryError`
   when text matches both a gene and a disease) but the tester couldn't trigger
   it. Separately, `_suggest` (`filters.py:19`) is case-sensitive and
   length-biased: for `moi="Recessive"` it ranks `"X-linked recessive"` (shorter)
   above the more intuitive `"Autosomal recessive"`.

8. **Part-1 #3 — repeated citation boilerplate (Token efficiency).** `standard`
   and `full` embed the ~260-char `recommended_citation` in every `_meta`; a
   multi-call loop pays it on each step.

## Design

### Architecture principle

Keep the existing envelope boundary (`run_mcp_tool`) as the single success/domain-
error shaper. Add **one** new seam — a FastMCP middleware — to catch the *only*
error class that structurally cannot reach `run_mcp_tool`: pre-body argument
validation. Everything else is a localized fix in the layer that already owns it
(service, shaping, next_commands, capabilities, resources, filters).

### Change 1 — D1: restore the verbosity ladder (service)

`gencc_service.get_gene_disease_assertion`: pass `mode` directly to
`shaping.assertion_dict` (drop the `"standard" if mode == "minimal"` override).
Result: `minimal ≤ compact ≤ standard ≤ full` strictly. `full`'s extra
`submissions[]` block is unaffected.

### Change 2 — D2a: `InputValidationMiddleware` (new `gencc_link/mcp/middleware.py`)

A `fastmcp.server.middleware.Middleware` subclass overriding `on_call_tool`:

```
async def on_call_tool(self, context, call_next):
    try:
        return await call_next(context)
    except PydanticValidationError as exc:
        envelope = validation_error_envelope(
            tool_name=context.message.name,
            arguments=context.message.arguments or {},
            exc=exc,
        )
        return ToolResult(structured_content=envelope)
```

- `validation_error_envelope` is a small builder added to `envelope.py` that
  reuses `_classify`/`_field_errors`/`_provenance_meta` so the shape is byte-for-
  byte identical to a body-raised `invalid_input` (success:false, error_code,
  message, retryable:false, recovery_action:"reformulate_input", field_errors[],
  `_meta` with request_id/elapsed_ms/next_commands).
- `next_commands` for an arg-validation failure: always `→ get_server_capabilities`
  (the authoritative parameter contract); when the failing field is a known enum
  (`response_mode`), the message names the accepted set.
- Returning a `ToolResult` short-circuits before FastMCP's masking layer and
  before output-schema validation; the permissive output schemas
  (`required:["success"]`, `additionalProperties:true`) already admit error
  envelopes, so structured clients stay happy.
- Registered **first** in `create_gencc_mcp` (before tools) so it wraps every
  tool. Ordering: error-handling middleware goes early (FastMCP guidance).

`resolve_identifier` additionally accepts `identifier` as an alias for `query`
(assessment's optional ergonomic suggestion): signature gains
`identifier: str | None = None`; body coalesces `query = query or identifier`
and raises the normal `invalid_input` (with `next_commands`) if both are absent.

### Change 3 — D2b: complete the recovery surface (next_commands)

Extend `recovery_commands()` so the four gap cases return a step:

- empty query (`invalid_input`, field `query`/`gene`/`disease`) →
  `→ get_server_capabilities`.
- `>20` batch (`invalid_input`, field `genes`/`diseases`) →
  `→ get_server_capabilities`.
- negative/!int offset (`invalid_input`, field `offset`) → the same tool with
  `offset=0` (corrected args, reusing `arguments`).
- no-filter `find_curations` (`invalid_input`, no field) →
  `→ get_server_capabilities`.

Net guarantee: **every** error envelope carries `≥1` next_command. A test asserts
this invariant across all tools/error codes.

### Change 4 — D3 + D4: opaque cursor for `find_curations` (refresh-safe, autonomous)

Add a stateless, opaque cursor (`gencc_link/services/cursor.py`):

- **Encode:** base64url(JSON) of
  `{"v":1, "r":<gencc_release>, "o":<offset>, "lim":<limit>, "flt":{...all filters...}}`.
  No server state; the cursor fully reproduces the next page.
- **`find_curations` gains `cursor: str | None = None`.** When present it is the
  source of truth: decode → if `r != current gencc_release` raise
  `invalid_input(field="cursor", "GenCC data refreshed (<old>→<new>); restart the
  sweep.")` with `next_commands → find_curations(<original filters>)` +
  `→ get_gencc_diagnostics`. Otherwise apply its offset/limit/filters and ignore
  the other filter params (documented). Malformed cursor → `invalid_input`.
- **`shaping.truncation_block` gains `next_cursor`** (encoded from
  release+next_offset+filters) alongside the existing `next_offset`. Signature
  extended with the filter context; `search_*`/`get_*_curations` keep passing
  only offset (their `next_cursor` is omitted — cursor is a `find_curations`
  feature) — documented as release-scoped offsets for those tools.
- **D4:** when `find_curations` is truncated, **prepend**
  `find_curations(cursor=<next_cursor>)` to `_meta.next_commands` (before the
  drill-into-row-1 step). An agent following `next_commands[0]` pages the full
  result set autonomously; the cursor makes the walk refresh-safe.
- `offset` keeps working standalone (back-compat); if both given, `cursor` wins.

### Change 5 — D6: reachable `ambiguous_query` + better suggestions

- **Suggestions (`filters._suggest`):** compare case-folded, return up to 3 close
  matches ("Did you mean one of: 'Autosomal recessive', 'X-linked recessive'?").
  Single match keeps the singular form. Fixes the `"Recessive"` ranking and is
  strictly more helpful.
- **Reachability:** add a fixture row / test so a token that resolves to **both**
  a gene and a disease triggers `ambiguous_query` end-to-end; document in
  `gencc://reference` how it arises (`resolve_identifier(kind="auto")` on text
  matching both). No code change to the (correct) path — this closes the "confirm
  it's wired" ask with a regression test.

### Change 6 — Token efficiency (Part-1 #3): extend cite-by-ref to `standard`

`_provenance_meta`: emit `citation_ref` + `citation_short` for
`minimal | compact | standard`; reserve the full `recommended_citation` for
`full` (the raw-detail mode). No information loss — `citation_short` attributes a
sourced answer, `citation_ref`/`gencc://citation` give the full citation on
demand. Update `GENCC_SERVER_INSTRUCTIONS`, capabilities `response_fields`, and
`gencc://reference` wording to match.

### Change 7 — D5 + housekeeping: documentation parity

- Add `field_errors`, `cursor`, and `next_cursor` to capabilities
  `response_fields` and `gencc://reference`.
- Add the already-registered `gencc://research-use` resource to the capabilities
  `resources` map.
- These edits change the hashed static surface → `capabilities_version` rolls
  (intended; it is a content hash). Update any test asserting a *literal* hash to
  assert *stability/shape* instead.

### Out of scope (YAGNI)

- Opaque cursors for `search_*`/`get_*_curations` (assessment flags sweeps =
  `find_curations`; others get release-scoped-offset docs).
- Replacing offset entirely (kept for back-compat).
- Per-tool `response_mode` default reconciliation (not flagged; defaults are
  intentional — `compact` everywhere except `get_gene_disease_assertion`).

## Testing strategy

TDD per change. Fixtures: extend `tests/fixtures/sample.tsv` only if needed for
the `ambiguous_query` reachability test (a gene symbol that is also a disease
title token). New/updated tests:

- **D1:** `get_gene_disease_assertion(response_mode="minimal")` omits
  `submitters[]` and is a strict subset of `compact`; assert size ladder
  `minimal ⊆ compact ⊆ standard ⊆ full`.
- **D2a:** invalid `response_mode="ultra"` and unknown arg name each return a
  well-formed `invalid_input` envelope (error_code, field_errors, next_commands,
  request_id) via the middleware — exercised through the real FastMCP client
  used in `tests/test_tools.py`. `resolve_identifier(identifier=...)` alias works.
- **D2b:** parametric test — every error path emits `≥1` next_command.
- **D3/D4:** cursor round-trips a full sweep; a cursor minted under release A is
  rejected with `invalid_input` under release B; truncated `find_curations`
  prepends the `cursor` continuation and following it reaches the next page with
  no dup/skip.
- **D6:** `moi="Recessive"` suggestion includes `"Autosomal recessive"`;
  `ambiguous_query` is reachable and carries both recovery commands.
- **Token:** `standard` `_meta` has `citation_ref`/`citation_short`, no
  `recommended_citation`; `full` retains it.
- **Capabilities:** `response_fields` documents `field_errors`/`cursor`/
  `next_cursor`; `resources` includes `gencc://research-use`; version hash stable
  across repeated calls.

Gate: `make ci-local` (ruff, mypy strict, pytest ≥85% cov, `lint-loc` 600-line
cap). New module `middleware.py` and `cursor.py` stay well under the cap.

## Docs & release

- `CHANGELOG.md`: 0.3.0 entry grouped Fixed/Added/Changed, noting the citation
  contract refinement (standard now cite-by-ref) and the new `cursor`.
- `pyproject.toml`: version 0.3.0 (package metadata is the single source of truth
  per commit 3a4a321).
- README / connection-guide tables: update response-mode + citation rows and add
  `cursor`/`next_cursor` to the `find_curations` row if such tables exist.
- Mark the assessment's findings resolved (append a short resolution note to
  `docs/MCP-ASSESSMENT.md` or a sibling changelog) so the doc and code agree.

## Risks & mitigations

- **Citation-contract change (Change 6)** is the only consumer-visible breaking
  change. Mitigation: `citation_short` always present for attribution;
  `citation_ref` + `gencc://citation` for the formal citation; documented in
  CHANGELOG under Changed; pre-1.0 surface.
- **Middleware output bypass** could in theory desync from `run_mcp_tool`'s
  shape. Mitigation: the middleware calls the *same* envelope builders; a test
  asserts the middleware `invalid_input` envelope matches the body-raised one
  field-for-field (minus request-specific ids).
- **Cursor opacity**: encode version (`"v":1`) so the format can evolve; decode
  failures degrade to a clean `invalid_input`, never a crash.
