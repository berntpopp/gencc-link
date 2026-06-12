# MCP Consumer-Uplift to >9.5/10 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve every finding in `docs/MCP-ASSESSMENT.md` (D1–D6 + the per-call citation tax) to lift the `gencc-link` MCP from 9/10 to >9.5/10, in line with the MCP `2025-11-25` tools spec and FastMCP 3.4.2 behavior.

**Architecture:** Keep `run_mcp_tool` as the single success/domain-error shaper. Add exactly one new seam — a FastMCP `on_call_tool` middleware — to catch the one error class that structurally cannot reach `run_mcp_tool`: pre-body argument validation. Every other fix is localized to the layer that owns it (service, shaping, next_commands, capabilities, resources, filters). Add two small stateless modules: `mcp/middleware.py` and `services/cursor.py`.

**Tech Stack:** Python 3.12, FastMCP 3.4.2, Pydantic v2, SQLite/FTS5, pytest (+ pytest-asyncio, in-memory `fastmcp.Client`), Ruff (100-col), mypy strict.

**Reference (verified) call path for D2a:** FastMCP runs `type_adapter.validate_python(arguments)` in `FunctionTool.run` (`fastmcp/tools/function_tool.py:286+`) *before* the tool body; an invalid `response_mode` or unknown arg raises `pydantic.ValidationError` there. The inner `call_tool(run_middleware=False)` re-raises it **without** masking, so an `on_call_tool` middleware wrapping the chain sees the raw error with `.errors()` intact and may return a synthetic `ToolResult` (short-circuiting masking + output-schema validation).

**Verified imports:**
- `from fastmcp.server.middleware import Middleware, MiddlewareContext`
- `from fastmcp.tools.tool import ToolResult`
- `from pydantic import ValidationError` (this is `pydantic_core.ValidationError`)
- `context.message.name` / `context.message.arguments` on the `on_call_tool` context.

**Conventions:** Tests access the envelope via `result.structured_content`. Run the suite with `make test` (fast, excludes integration) or a single file via `uv run pytest tests/<file>::<test> -v`. Final gate: `make ci-local`.

---

## Task 1: D1 — restore the assertion verbosity ladder

**Files:**
- Modify: `gencc_link/services/gencc_service.py:347-350`
- Test: `tests/test_tools.py`, `tests/test_service.py`

- [ ] **Step 1: Write the failing e2e test** (append to `tests/test_tools.py`, inside `class TestEvalHardening`):

```python
    async def test_assertion_minimal_omits_submitters(self, mcp_client) -> None:
        result = await mcp_client.call_tool(
            "get_gene_disease_assertion",
            {"gene": "GLA", "disease": "MONDO:0010526", "response_mode": "minimal"},
        )
        a = result.structured_content["assertion"]
        assert "submitters" not in a
        assert "submitter_titles" not in a  # that's a compact-only field
        assert a["strongest_classification"]
        assert "has_conflict" in a

    async def test_assertion_mode_size_ladder(self, mcp_client) -> None:
        async def keys(mode: str) -> set[str]:
            r = await mcp_client.call_tool(
                "get_gene_disease_assertion",
                {"gene": "GLA", "disease": "MONDO:0010526", "response_mode": mode},
            )
            return set(r.structured_content["assertion"].keys())

        minimal, compact, standard = await keys("minimal"), await keys("compact"), await keys("standard")
        assert minimal < compact < standard  # strict subset ladder
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest "tests/test_tools.py::TestEvalHardening::test_assertion_minimal_omits_submitters" "tests/test_tools.py::TestEvalHardening::test_assertion_mode_size_ladder" -v`
Expected: FAIL — `minimal` currently returns the full `submitters` array (so `"submitters" in a`) and `minimal == standard`.

- [ ] **Step 3: Fix the service** — in `gencc_link/services/gencc_service.py`, change the assertion shaping call:

```python
        payload: dict[str, Any] = {
            "assertion": shaping.assertion_dict(assertion, mode),
            "headline": shaping.assertion_headline(assertion),
        }
```

(Remove the `"standard" if mode == "minimal" else mode` override; pass `mode` directly. `mode` is already the validated `ResponseMode` from `self._validate_mode(response_mode)`.)

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest "tests/test_tools.py::TestEvalHardening::test_assertion_minimal_omits_submitters" "tests/test_tools.py::TestEvalHardening::test_assertion_mode_size_ladder" -v`
Expected: PASS

- [ ] **Step 5: Regression-check the full file**

Run: `uv run pytest tests/test_tools.py tests/test_service.py tests/test_shaping.py -q`
Expected: PASS (no existing test asserted the buggy `minimal == standard`).

- [ ] **Step 6: Commit**

```bash
git add gencc_link/services/gencc_service.py tests/test_tools.py
git commit -m "fix(D1): get_gene_disease_assertion minimal is summary-only (verbosity ladder)"
```

---

## Task 2: D2b — every error envelope carries a recovery command

**Files:**
- Modify: `gencc_link/mcp/next_commands.py:106-143` (`recovery_commands`)
- Test: `tests/test_next_commands.py`, `tests/test_tools.py`

- [ ] **Step 1: Write failing unit tests** (append to `tests/test_next_commands.py`):

```python
import pytest

from gencc_link.mcp.next_commands import recovery_commands


@pytest.mark.parametrize(
    "tool, field",
    [
        ("search_genes", "query"),
        ("get_genes_curations", "genes"),
        ("get_diseases_curations", "diseases"),
        ("find_curations", None),  # no-filter find_curations
        ("find_curations", "offset"),
        ("get_gene_disease_assertion", "response_mode"),
    ],
)
def test_invalid_input_always_has_recovery(tool, field):
    cmds = recovery_commands(tool, "invalid_input", {}, field)
    assert cmds, f"{tool}/{field} produced no recovery command"


def test_invalid_submitter_still_routes_to_list_submitters():
    cmds = recovery_commands("find_curations", "invalid_input", {}, "submitter")
    assert cmds[0]["tool"] == "list_submitters"


def test_invalid_classification_still_routes_to_capabilities():
    cmds = recovery_commands("find_curations", "invalid_input", {}, "classification")
    assert cmds[0]["tool"] == "get_server_capabilities"


def test_cursor_drift_routes_to_diagnostics():
    cmds = recovery_commands("find_curations", "invalid_input", {}, "cursor")
    assert cmds[0]["tool"] == "get_gencc_diagnostics"
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_next_commands.py -k "invalid_input_always or cursor_drift" -v`
Expected: FAIL — `recovery_commands` currently returns `[]` for `query`, `genes`, `diseases`, `None`, `offset`, `response_mode`, and `cursor`.

- [ ] **Step 3: Rewrite the `invalid_input` branch** in `recovery_commands` (`gencc_link/mcp/next_commands.py`). Replace the existing `if error_code == "invalid_input":` block with:

```python
    if error_code == "invalid_input":
        if field == "submitter":
            return [cmd("list_submitters")]
        if field == "cursor":
            return [cmd("get_gencc_diagnostics"), cmd("get_server_capabilities")]
        # classification, moi, response_mode, empty query, >20 batch, bad
        # offset/limit, no-filter find_curations: the authoritative parameter
        # contract is get_server_capabilities. Guarantees every invalid_input
        # envelope is chainable.
        return [cmd("get_server_capabilities")]
```

(Leave the `not_found`, `ambiguous_query`, and `data_unavailable` branches unchanged.)

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_next_commands.py -v`
Expected: PASS

- [ ] **Step 5: Add an e2e invariant test** (append to `tests/test_tools.py`, inside `class TestEvalHardening`):

```python
    async def test_empty_and_overcap_errors_are_chainable(self, mcp_client) -> None:
        # empty query
        r1 = await mcp_client.call_tool("search_genes", {"query": "   "})
        d1 = r1.structured_content
        assert d1["success"] is False and d1["error_code"] == "invalid_input"
        assert d1["_meta"]["next_commands"], "empty-query error must be chainable"
        # >20 batch
        r2 = await mcp_client.call_tool(
            "get_genes_curations", {"genes": [f"G{i}" for i in range(21)]}
        )
        d2 = r2.structured_content
        assert d2["success"] is False and d2["error_code"] == "invalid_input"
        assert d2["_meta"]["next_commands"], ">20 batch error must be chainable"
        # no-filter find_curations
        r3 = await mcp_client.call_tool("find_curations", {})
        d3 = r3.structured_content
        assert d3["success"] is False
        assert d3["_meta"]["next_commands"], "no-filter find_curations must be chainable"
```

- [ ] **Step 6: Run to verify pass**

Run: `uv run pytest "tests/test_tools.py::TestEvalHardening::test_empty_and_overcap_errors_are_chainable" tests/test_tools.py -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add gencc_link/mcp/next_commands.py tests/test_next_commands.py tests/test_tools.py
git commit -m "fix(D2b): attach next_commands to every invalid_input envelope"
```

---

## Task 3: D2a — wrap argument-validation errors in the structured envelope

**Files:**
- Modify: `gencc_link/mcp/envelope.py` (add `validation_error_envelope`)
- Create: `gencc_link/mcp/middleware.py`
- Modify: `gencc_link/mcp/facade.py` (register middleware)
- Modify: `gencc_link/mcp/tools/assertions.py` (`resolve_identifier` `identifier` alias)
- Test: `tests/test_envelope.py`, `tests/test_tools.py`

- [ ] **Step 1: Write a failing unit test for the envelope builder** (append to `tests/test_envelope.py`):

```python
from pydantic import BaseModel, ValidationError

from gencc_link.mcp.envelope import validation_error_envelope


def _make_validation_error() -> ValidationError:
    class _M(BaseModel):
        response_mode: str

    try:
        _M(response_mode=["not", "a", "str"])  # type: ignore[arg-type]
    except ValidationError as exc:
        return exc
    raise AssertionError("expected ValidationError")


def test_validation_error_envelope_shape() -> None:
    env = validation_error_envelope(
        tool_name="get_gene_disease_assertion",
        arguments={"response_mode": "ultra"},
        exc=_make_validation_error(),
    )
    assert env["success"] is False
    assert env["error_code"] == "invalid_input"
    assert env["retryable"] is False
    assert env["recovery_action"] == "reformulate_input"
    assert env["field_errors"]
    assert env["_meta"]["tool"] == "get_gene_disease_assertion"
    assert env["_meta"]["next_commands"]
    assert isinstance(env["_meta"]["request_id"], str)
    assert "elapsed_ms" in env["_meta"]
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_envelope.py::test_validation_error_envelope_shape -v`
Expected: FAIL — `validation_error_envelope` does not exist.

- [ ] **Step 3: Add `validation_error_envelope` to `gencc_link/mcp/envelope.py`** (place after `_error_envelope`, reusing the existing helpers so the shape is identical to a body-raised `invalid_input`):

```python
def validation_error_envelope(
    *,
    tool_name: str,
    arguments: dict[str, Any],
    exc: PydanticValidationError,
) -> dict[str, Any]:
    """Structured ``invalid_input`` envelope for a pre-body argument-validation
    failure (caught by the MCP middleware before the tool body runs).

    Mirrors ``_error_envelope`` exactly so an arg-validation failure is
    byte-compatible with a domain ``invalid_input`` raised inside a tool.
    """
    ctx = McpErrorContext(tool_name=tool_name, arguments=arguments)
    return _error_envelope(
        exc,
        ctx,
        request_id=uuid.uuid4().hex[:12],
        elapsed_ms=0.0,
    )
```

Note: `_classify` already maps `PydanticValidationError` to `("invalid_input", ...)` and `_field_errors` already expands `.errors()`; `_error_envelope` already routes `recovery_commands(tool, "invalid_input", arguments, field)` where `field` is `exc.errors()[0]["loc"][-1]` via `getattr(exc, "field", None)` — but a `PydanticValidationError` has no `.field`. To route recovery by the failing field, update `_error_envelope`'s `field_name` line to fall back to the first pydantic loc:

In `_error_envelope`, replace:

```python
    field_name = getattr(exc, "field", None)
```

with:

```python
    field_name = getattr(exc, "field", None)
    if field_name is None and isinstance(exc, PydanticValidationError):
        errs = exc.errors()
        if errs and errs[0]["loc"]:
            field_name = str(errs[0]["loc"][-1])
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_envelope.py::test_validation_error_envelope_shape -v`
Expected: PASS

- [ ] **Step 5: Create the middleware** — `gencc_link/mcp/middleware.py`:

```python
"""FastMCP middleware that converts pre-body argument-validation failures into
the structured ``invalid_input`` envelope.

FastMCP validates tool arguments (Pydantic ``TypeAdapter``) inside
``FunctionTool.run`` *before* the tool body runs, so an invalid ``response_mode``
or an unknown argument name raises ``pydantic.ValidationError`` where the body's
``run_mcp_tool`` boundary can never catch it. This middleware wraps the call,
catches that error, and returns a normal ``ToolResult`` whose structured content
is the same ``invalid_input`` envelope a domain error would produce — so *every*
error the client sees is chainable, never a raw Pydantic/JSON-RPC dump.
"""

from __future__ import annotations

from typing import Any

from fastmcp.server.middleware import Middleware, MiddlewareContext
from fastmcp.tools.tool import ToolResult
from pydantic import ValidationError

from gencc_link.mcp.envelope import validation_error_envelope


class InputValidationMiddleware(Middleware):
    """Re-wrap argument-validation errors as a structured ``invalid_input`` envelope."""

    async def on_call_tool(
        self,
        context: MiddlewareContext[Any],
        call_next: Any,
    ) -> ToolResult:
        try:
            return await call_next(context)
        except ValidationError as exc:
            envelope = validation_error_envelope(
                tool_name=context.message.name,
                arguments=dict(context.message.arguments or {}),
                exc=exc,
            )
            return ToolResult(structured_content=envelope)
```

- [ ] **Step 6: Register the middleware first** in `gencc_link/mcp/facade.py` — add the import and `mcp.add_middleware` before tool registration:

```python
from gencc_link.mcp.capabilities import register_capability_resources
from gencc_link.mcp.middleware import InputValidationMiddleware
from gencc_link.mcp.resources import GENCC_SERVER_INSTRUCTIONS
```

and inside `create_gencc_mcp`, immediately after constructing `mcp`:

```python
    mcp = FastMCP(
        name="gencc-link",
        instructions=GENCC_SERVER_INSTRUCTIONS,
        mask_error_details=True,
    )
    # Error-handling middleware goes first so it wraps every tool call.
    mcp.add_middleware(InputValidationMiddleware())

    register_discovery_tools(mcp)
```

- [ ] **Step 7: Add the `identifier` alias** to `resolve_identifier` in `gencc_link/mcp/tools/assertions.py`. Change the signature and body:

```python
    async def resolve_identifier(
        query: str | None = None,
        kind: str = "auto",
        identifier: str | None = None,
    ) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            q = query if query is not None else identifier
            if q is None:
                from gencc_link.exceptions import InvalidInputError

                raise InvalidInputError("query must not be empty.", field="query")
            payload = get_gencc_service().resolve_identifier(q, kind=kind)
            nexts: list[dict[str, Any]] = []
            if payload.get("gene"):
                nexts.append(cmd("get_gene_curations", gene=payload["gene"]["gene_curie"]))
            if payload.get("disease"):
                nexts.append(
                    cmd("get_disease_curations", disease=payload["disease"]["disease_curie"])
                )
            payload["_meta"] = {"next_commands": nexts}
            return payload

        return await run_mcp_tool(
            "resolve_identifier",
            call,
            context=McpErrorContext(
                "resolve_identifier", arguments={"query": query or identifier or ""}
            ),
        )
```

Also update the tool `description` to mention the alias — append: `" Accepts query or its alias identifier."`

- [ ] **Step 8: Write failing e2e tests** (append to `tests/test_tools.py`, inside `class TestEvalHardening`):

```python
    async def test_invalid_response_mode_is_structured(self, mcp_client) -> None:
        result = await mcp_client.call_tool(
            "get_gene_disease_assertion",
            {"gene": "SKI", "disease": "MONDO:0008426", "response_mode": "ultra"},
        )
        data = result.structured_content
        assert data["success"] is False
        assert data["error_code"] == "invalid_input"
        assert data["field_errors"]
        assert data["_meta"]["next_commands"][0]["tool"] == "get_server_capabilities"
        assert isinstance(data["_meta"]["request_id"], str)

    async def test_unknown_argument_is_structured(self, mcp_client) -> None:
        result = await mcp_client.call_tool("search_genes", {"identifier": "SKI"})
        data = result.structured_content
        assert data["success"] is False
        assert data["error_code"] == "invalid_input"
        assert data["_meta"]["next_commands"]

    async def test_resolve_identifier_alias(self, mcp_client) -> None:
        result = await mcp_client.call_tool("resolve_identifier", {"identifier": "SKI"})
        data = result.structured_content
        assert data["success"] is True
        assert data["gene"]["gene_symbol"] == "SKI"
```

- [ ] **Step 9: Run to verify pass**

Run: `uv run pytest "tests/test_tools.py::TestEvalHardening::test_invalid_response_mode_is_structured" "tests/test_tools.py::TestEvalHardening::test_unknown_argument_is_structured" "tests/test_tools.py::TestEvalHardening::test_resolve_identifier_alias" tests/test_envelope.py -v`
Expected: PASS. (If `test_unknown_argument_is_structured` errors because the in-memory client raises instead of returning — confirm the middleware import path and that `add_middleware` ran; the middleware must catch `pydantic.ValidationError`.)

- [ ] **Step 10: Full regression**

Run: `uv run pytest tests/test_tools.py tests/test_envelope.py -q`
Expected: PASS

- [ ] **Step 11: Commit**

```bash
git add gencc_link/mcp/envelope.py gencc_link/mcp/middleware.py gencc_link/mcp/facade.py gencc_link/mcp/tools/assertions.py tests/test_envelope.py tests/test_tools.py
git commit -m "fix(D2a): wrap arg-validation errors in structured invalid_input envelope via middleware; add resolve_identifier identifier alias"
```

---

## Task 4: D3 — opaque pagination cursor module

**Files:**
- Create: `gencc_link/services/cursor.py`
- Test: `tests/test_cursor.py` (new)

- [ ] **Step 1: Write failing unit tests** — create `tests/test_cursor.py`:

```python
"""Unit tests for the opaque find_curations pagination cursor."""

from __future__ import annotations

import pytest

from gencc_link.services.cursor import decode_cursor, encode_cursor


def test_round_trip() -> None:
    token = encode_cursor(
        release="2026-06-07",
        offset=50,
        limit=50,
        filters={"classification": ["Definitive"], "has_conflict": None},
    )
    assert isinstance(token, str)
    assert "=" not in token  # url-safe, unpadded
    decoded = decode_cursor(token)
    assert decoded["o"] == 50
    assert decoded["lim"] == 50
    assert decoded["r"] == "2026-06-07"
    assert decoded["flt"]["classification"] == ["Definitive"]


def test_malformed_cursor_raises_value_error() -> None:
    with pytest.raises(ValueError):
        decode_cursor("!!!not-base64!!!")


def test_wrong_version_raises_value_error() -> None:
    import base64
    import json

    raw = base64.urlsafe_b64encode(json.dumps({"v": 999}).encode()).decode().rstrip("=")
    with pytest.raises(ValueError):
        decode_cursor(raw)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_cursor.py -v`
Expected: FAIL — module `gencc_link.services.cursor` does not exist.

- [ ] **Step 3: Create `gencc_link/services/cursor.py`:**

```python
"""Opaque, stateless pagination cursor for ``find_curations``.

A cursor encodes the full query — canonical filters, response mode, offset, and
limit — plus the GenCC data release it was minted against. A page-forward call
therefore reproduces the exact next page with no server state, and the server can
reject a cursor minted against a now-stale release (refresh-safe paging) instead
of silently skipping or duplicating rows across a weekly data refresh.
"""

from __future__ import annotations

import base64
import json
from typing import Any

_CURSOR_VERSION = 1


def encode_cursor(
    *,
    release: str | None,
    offset: int,
    limit: int,
    filters: dict[str, Any],
) -> str:
    """Encode an opaque, url-safe cursor token (no padding)."""
    payload = {"v": _CURSOR_VERSION, "r": release, "o": offset, "lim": limit, "flt": filters}
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(token: str) -> dict[str, Any]:
    """Decode a cursor token; raise ``ValueError`` on any malformation."""
    try:
        padded = token + "=" * (-len(token) % 4)
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
        payload = json.loads(raw)
    except Exception as exc:  # malformed base64 / json
        raise ValueError("cursor is malformed") from exc
    if not isinstance(payload, dict) or payload.get("v") != _CURSOR_VERSION:
        raise ValueError("cursor version is unsupported")
    if not isinstance(payload.get("o"), int) or not isinstance(payload.get("lim"), int):
        raise ValueError("cursor offset/limit invalid")
    if not isinstance(payload.get("flt"), dict):
        raise ValueError("cursor filters invalid")
    return payload
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_cursor.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add gencc_link/services/cursor.py tests/test_cursor.py
git commit -m "feat(D3): opaque, release-bound pagination cursor module"
```

---

## Task 5: D3 + D4 — wire the cursor into find_curations + autonomous page-forward

**Files:**
- Modify: `gencc_link/services/shaping.py:227-237` (`truncation_block`)
- Modify: `gencc_link/services/gencc_service.py` (`find_curations`)
- Modify: `gencc_link/mcp/tools/assertions.py` (`find_curations` tool: `cursor` param + page-forward next_command)
- Test: `tests/test_shaping.py`, `tests/test_service.py`, `tests/test_tools.py`

- [ ] **Step 1: Write failing tests for `truncation_block` next_cursor** (append to `tests/test_shaping.py`):

```python
from gencc_link.services.cursor import decode_cursor
from gencc_link.services.shaping import truncation_block


def test_truncation_block_without_cursor_context() -> None:
    block = truncation_block(100, 50, 0)
    assert block is not None
    assert block["next_offset"] == 50
    assert "next_cursor" not in block


def test_truncation_block_with_cursor_context() -> None:
    block = truncation_block(
        100,
        50,
        0,
        cursor_context={"release": "2026-06-07", "filters": {"has_conflict": True}},
    )
    assert block is not None
    decoded = decode_cursor(block["next_cursor"])
    assert decoded["o"] == 50
    assert decoded["r"] == "2026-06-07"
    assert decoded["flt"]["has_conflict"] is True
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_shaping.py -k truncation_block -v`
Expected: FAIL — `truncation_block` takes no `cursor_context`.

- [ ] **Step 3: Extend `truncation_block`** in `gencc_link/services/shaping.py` (add the import at top of file and the param):

At the top with the other imports, add:

```python
from gencc_link.services.cursor import encode_cursor
```

Replace `truncation_block` with:

```python
def truncation_block(
    total: int,
    limit: int,
    offset: int,
    *,
    cursor_context: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Return a truncation hint when more rows exist beyond this page.

    When ``cursor_context`` (``{"release": str|None, "filters": dict}``) is given,
    also mint an opaque ``next_cursor`` that reproduces the next page and is bound
    to the data release (refresh-safe). Callers that page by raw offset only
    (search_*, get_*_curations) omit it.
    """
    returned = max(0, min(limit, total - offset))
    if offset + returned >= total:
        return None
    block: dict[str, Any] = {
        "total": total,
        "returned": returned,
        "next_offset": offset + returned,
        "hint": "More results available; re-call with next_offset, or follow "
        "next_cursor for refresh-safe paging.",
    }
    if cursor_context is not None:
        block["next_cursor"] = encode_cursor(
            release=cursor_context["release"],
            offset=offset + returned,
            limit=limit,
            filters=cursor_context["filters"],
        )
    return block
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_shaping.py -k truncation_block -v`
Expected: PASS

- [ ] **Step 5: Write failing service tests** (append to `tests/test_service.py`):

```python
import pytest

from gencc_link.exceptions import InvalidInputError
from gencc_link.services.cursor import encode_cursor


def test_find_curations_truncation_has_next_cursor(service) -> None:
    page = service.find_curations(classification=["Definitive"], limit=2, offset=0)
    assert page["total"] > 2
    assert "next_cursor" in page["truncated"]


def test_find_curations_cursor_resumes_same_query(service) -> None:
    first = service.find_curations(classification=["Definitive"], limit=2, offset=0)
    cursor = first["truncated"]["next_cursor"]
    second = service.find_curations(cursor=cursor)
    assert second["total"] == first["total"]
    first_ids = {(r["gene_curie"], r["disease_curie"]) for r in first["results"]}
    second_ids = {(r["gene_curie"], r["disease_curie"]) for r in second["results"]}
    assert first_ids.isdisjoint(second_ids)  # no overlap across the page boundary


def test_find_curations_stale_cursor_rejected(service) -> None:
    stale = encode_cursor(
        release="1999-01-01",
        offset=0,
        limit=2,
        filters={"classification": ["Definitive"]},
    )
    with pytest.raises(InvalidInputError) as exc:
        service.find_curations(cursor=stale)
    assert exc.value.field == "cursor"
```

- [ ] **Step 6: Run to verify failure**

Run: `uv run pytest tests/test_service.py -k "next_cursor or cursor_resumes or stale_cursor" -v`
Expected: FAIL — `find_curations` has no `cursor` parameter / no `next_cursor`.

- [ ] **Step 7: Wire the cursor into `GenCCService.find_curations`** (`gencc_link/services/gencc_service.py`). Add `cursor: str | None = None` to the signature (after `offset`), add the cursor import at the top, and decode-then-validate at the top of the method, then mint the cursor in the truncation block.

At the top of `gencc_link/services/gencc_service.py` with the other imports:

```python
from gencc_link.services.cursor import decode_cursor
```

Change the signature:

```python
    def find_curations(
        self,
        *,
        gene: str | None = None,
        disease: str | None = None,
        classification: list[str] | None = None,
        submitter: list[str] | None = None,
        moi: str | None = None,
        has_conflict: bool | None = None,
        response_mode: str = "compact",
        ids_only: bool = False,
        limit: int = 50,
        offset: int = 0,
        cursor: str | None = None,
    ) -> dict[str, Any]:
```

Immediately after the signature (before `mode = self._validate_mode(...)`), insert the cursor-decode block:

```python
        if cursor is not None:
            try:
                cur = decode_cursor(cursor)
            except ValueError as exc:
                raise InvalidInputError(str(exc), field="cursor") from exc
            current_release = self.get_meta().gencc_run_date
            if cur["r"] != current_release:
                raise InvalidInputError(
                    f"Cursor was minted against GenCC release {cur['r']!r} but the "
                    f"current release is {current_release!r}; restart the sweep.",
                    field="cursor",
                )
            flt = cur["flt"]
            gene = flt.get("gene")
            disease = flt.get("disease")
            classification = flt.get("classification")
            submitter = flt.get("submitter")
            moi = flt.get("moi")
            has_conflict = flt.get("has_conflict")
            response_mode = flt.get("response_mode", response_mode)
            ids_only = flt.get("ids_only", ids_only)
            offset = cur["o"]
            limit = cur["lim"]
```

Then, where the truncation block is built at the end of the method, replace:

```python
        trunc = shaping.truncation_block(total, limit, offset)
        if trunc:
            payload["truncated"] = trunc
        return payload
```

with (mint a release-bound cursor from the *canonical* filters):

```python
        cursor_filters = {
            "gene": gene,
            "disease": disease,
            "classification": classification,
            "submitter": submitter,
            "moi": moi,
            "has_conflict": has_conflict,
            "response_mode": mode,
            "ids_only": ids_only,
        }
        trunc = shaping.truncation_block(
            total,
            limit,
            offset,
            cursor_context={
                "release": self.get_meta().gencc_run_date,
                "filters": cursor_filters,
            },
        )
        if trunc:
            payload["truncated"] = trunc
        return payload
```

- [ ] **Step 8: Run to verify pass**

Run: `uv run pytest tests/test_service.py -k "next_cursor or cursor_resumes or stale_cursor" -v`
Expected: PASS

- [ ] **Step 9: Wire the tool param + page-forward next_command** in `gencc_link/mcp/tools/assertions.py`. Add `cursor: str | None = None` to the `find_curations` tool signature (after `offset: int = 0`), pass it through to the service, and prepend the continuation command when truncated.

Update the signature and body of the `find_curations` tool:

```python
    async def find_curations(
        gene: str | None = None,
        disease: str | None = None,
        classification: list[str] | None = None,
        submitter: list[str] | None = None,
        moi: str | None = None,
        has_conflict: bool | None = None,
        response_mode: _MODE = "compact",
        ids_only: bool = False,
        limit: int = 50,
        offset: int = 0,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            payload = get_gencc_service().find_curations(
                gene=gene,
                disease=disease,
                classification=classification,
                submitter=submitter,
                moi=moi,
                has_conflict=has_conflict,
                response_mode=response_mode,
                ids_only=ids_only,
                limit=limit,
                offset=offset,
                cursor=cursor,
            )
            nexts: list[dict[str, Any]] = []
            trunc = payload.get("truncated") or {}
            if trunc.get("next_cursor"):
                # Page-forward first so an agent following next_commands[0]
                # sweeps the full result set autonomously (refresh-safe).
                nexts.append(cmd("find_curations", cursor=trunc["next_cursor"]))
            results = payload.get("results", [])
            if results:
                top = results[0]
                nexts.append(
                    cmd(
                        "get_gene_disease_assertion",
                        gene=top["gene_curie"],
                        disease=top["disease_curie"],
                    )
                )
            payload["_meta"] = {"next_commands": nexts}
            return payload
```

Also extend the tool `description` — append before the closing `)`:

```python
            "Large sweeps: follow truncated.next_cursor (an opaque, "
            "release-bound page token) via _meta.next_commands to page the full "
            "set; a cursor minted under a prior data release is rejected so a "
            "weekly refresh can't silently skip or duplicate rows."
```

- [ ] **Step 10: Write failing e2e test** (append to `tests/test_tools.py`, inside `class TestEvalHardening`):

```python
    async def test_find_curations_pages_forward_with_cursor(self, mcp_client) -> None:
        first = await mcp_client.call_tool(
            "find_curations", {"classification": ["Definitive"], "limit": 2}
        )
        d1 = first.structured_content
        assert "next_cursor" in d1["truncated"]
        cont = d1["_meta"]["next_commands"][0]
        assert cont["tool"] == "find_curations"
        assert "cursor" in cont["arguments"]
        # follow the continuation
        second = await mcp_client.call_tool("find_curations", cont["arguments"])
        d2 = second.structured_content
        assert d2["success"] is True
        ids1 = {(r["gene_curie"], r["disease_curie"]) for r in d1["results"]}
        ids2 = {(r["gene_curie"], r["disease_curie"]) for r in d2["results"]}
        assert ids1.isdisjoint(ids2)
```

- [ ] **Step 11: Run to verify pass**

Run: `uv run pytest "tests/test_tools.py::TestEvalHardening::test_find_curations_pages_forward_with_cursor" tests/test_service.py tests/test_shaping.py -q`
Expected: PASS

- [ ] **Step 12: Full regression on the touched areas**

Run: `uv run pytest tests/test_tools.py tests/test_service.py tests/test_shaping.py tests/test_cursor.py -q`
Expected: PASS

- [ ] **Step 13: Commit**

```bash
git add gencc_link/services/shaping.py gencc_link/services/gencc_service.py gencc_link/mcp/tools/assertions.py tests/test_shaping.py tests/test_service.py tests/test_tools.py
git commit -m "feat(D3,D4): refresh-safe cursor for find_curations with autonomous page-forward next_command"
```

---

## Task 6: D6 — reachable ambiguous_query + better filter suggestions

**Files:**
- Modify: `gencc_link/services/filters.py:19-21` (`_suggest`)
- Test: `tests/test_service.py` (or `tests/test_filters.py` if it exists), `tests/test_tools.py`

- [ ] **Step 1: Write failing unit tests for suggestions.** First check whether a filters test file exists:

Run: `ls tests/ | grep -i filter || echo "no filters test file"`

Append these to `tests/test_service.py` (they import the pure function directly):

```python
from gencc_link.services.filters import _suggest


def test_suggest_is_case_insensitive_and_prefers_autosomal_recessive() -> None:
    options = ["Autosomal dominant", "Autosomal recessive", "X-linked recessive"]
    msg = _suggest("Recessive", options)
    assert "Autosomal recessive" in msg


def test_suggest_offers_multiple_close_matches() -> None:
    options = ["Autosomal dominant", "Autosomal recessive", "X-linked recessive"]
    msg = _suggest("recessive", options)
    # both recessive modes are close; the agent should see them
    assert "Autosomal recessive" in msg and "X-linked recessive" in msg
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_service.py -k suggest -v`
Expected: FAIL — current `_suggest` is case-sensitive, returns a single length-biased match (`X-linked recessive`).

- [ ] **Step 3: Rewrite `_suggest`** in `gencc_link/services/filters.py` to be case-insensitive and offer up to three matches:

```python
def _suggest(value: str, options: list[str]) -> str:
    """Case-insensitive 'did you mean' hint (up to 3 closest matches)."""
    folded = {opt.casefold(): opt for opt in options}
    matches = difflib.get_close_matches(value.casefold(), list(folded), n=3, cutoff=0.4)
    if not matches:
        return ""
    canonical = [folded[m] for m in matches]
    if len(canonical) == 1:
        return f" Did you mean {canonical[0]!r}?"
    listed = ", ".join(repr(c) for c in canonical)
    return f" Did you mean one of: {listed}?"
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_service.py -k suggest -v`
Expected: PASS

- [ ] **Step 5: Add the e2e `ambiguous_query` reachability test** (append to `tests/test_tools.py`, inside `class TestEvalHardening`). It monkeypatches the shared service's repository so a known gene symbol also resolves as a disease — no fixture change:

```python
    async def test_resolve_identifier_ambiguous_query(
        self, mcp_client, service, monkeypatch
    ) -> None:
        a_disease = service._repo.resolve_disease("MONDO:0008426")
        orig = service._repo.resolve_disease

        def both(ident: str):
            return a_disease if ident.strip().casefold() == "ski" else orig(ident)

        monkeypatch.setattr(service._repo, "resolve_disease", both)
        result = await mcp_client.call_tool("resolve_identifier", {"query": "SKI"})
        data = result.structured_content
        assert data["success"] is False
        assert data["error_code"] == "ambiguous_query"
        nxt = data["_meta"]["next_commands"]
        tools = {c["tool"] for c in nxt}
        assert tools == {"get_gene_curations", "get_disease_curations"}
```

- [ ] **Step 6: Run to verify pass**

Run: `uv run pytest "tests/test_tools.py::TestEvalHardening::test_resolve_identifier_ambiguous_query" -v`
Expected: PASS. (Confirms the `ambiguous_query` path is wired end-to-end and carries both recovery commands.)

- [ ] **Step 7: Document reachability** in `gencc_link/mcp/resources.py` `GENCC_REFERENCE_NOTES` — after the `Error codes:` sentence, add:

```python
    "ambiguous_query arises only from resolve_identifier(kind='auto') when the "
    "text exactly matches both a gene symbol and a disease title; re-run with "
    "kind='gene' or kind='disease'. "
```

- [ ] **Step 8: Commit**

```bash
git add gencc_link/services/filters.py gencc_link/mcp/resources.py tests/test_service.py tests/test_tools.py
git commit -m "fix(D6): reachable ambiguous_query test + case-insensitive multi-suggestion filter hints"
```

---

## Task 7: Token efficiency — extend cite-by-ref to standard mode

**Files:**
- Modify: `gencc_link/mcp/envelope.py:65-80` (`_provenance_meta`)
- Modify: `gencc_link/mcp/resources.py` (`GENCC_SERVER_INSTRUCTIONS`)
- Test: `tests/test_envelope.py`, `tests/test_tools.py`

- [ ] **Step 1: Write/adjust failing tests.** First find any test asserting standard's citation:

Run: `uv run grep -rn "recommended_citation\|citation_ref\|citation_short" tests/`

Append to `tests/test_tools.py` (inside `class TestEvalHardening`):

```python
    async def test_standard_uses_citation_ref_not_full(self, mcp_client) -> None:
        result = await mcp_client.call_tool(
            "get_gene_curations", {"gene": "SKI", "response_mode": "standard"}
        )
        meta = result.structured_content["_meta"]
        assert meta["citation_ref"] == "gencc://citation"
        assert meta["citation_short"] == "GenCC (thegencc.org), CC0-1.0"
        assert "recommended_citation" not in meta
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest "tests/test_tools.py::TestEvalHardening::test_standard_uses_citation_ref_not_full" -v`
Expected: FAIL — standard currently emits the full `recommended_citation`.

- [ ] **Step 3: Update `_provenance_meta`** in `gencc_link/mcp/envelope.py` — broaden the cite-by-ref branch to include `standard`:

```python
    if response_mode in ("minimal", "compact", "standard"):
        meta["citation_ref"] = _CITATION_REF
        meta["citation_short"] = CITATION_SHORT
    else:  # full (and the unset/error default) keep the verbatim citation
        meta["recommended_citation"] = RECOMMENDED_CITATION
```

- [ ] **Step 4: Run to verify pass; then check for any now-stale test**

Run: `uv run pytest tests/test_envelope.py tests/test_tools.py -q`
Expected: PASS. If a pre-existing test asserted `standard` had `recommended_citation`, update it to expect `citation_ref`/`citation_short` (mirror `test_standard_uses_citation_ref_not_full`). Error envelopes (no `response_mode`) still get the full citation — keep any such assertion intact.

- [ ] **Step 5: Update the server instructions** in `gencc_link/mcp/resources.py` `GENCC_SERVER_INSTRUCTIONS` — change the citation sentence from:

```python
        "flag, a plain-English `headline`, `_meta.next_commands`, and "
        "`recommended_citation`. response_mode (minimal|compact|standard|full) trims "
```

to:

```python
        "flag, a plain-English `headline`, `_meta.next_commands`, and a citation "
        "(full `recommended_citation` in full mode; `citation_short` + "
        "`citation_ref` to gencc://citation otherwise). "
        "response_mode (minimal|compact|standard|full) trims "
```

- [ ] **Step 6: Run to verify pass**

Run: `uv run pytest tests/test_tools.py tests/test_envelope.py -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add gencc_link/mcp/envelope.py gencc_link/mcp/resources.py tests/test_tools.py
git commit -m "perf(tokens): cite-by-ref for standard mode; reserve full citation for full mode"
```

---

## Task 8: D5 + doc parity — capabilities, reference, resources

**Files:**
- Modify: `gencc_link/mcp/capabilities.py` (`response_fields`, `resources`)
- Modify: `gencc_link/mcp/resources.py` (`GENCC_REFERENCE_NOTES`)
- Test: `tests/test_capabilities.py`, `tests/test_tools.py`

- [ ] **Step 1: Inspect the capabilities version test** to see whether it hardcodes a literal hash:

Run: `uv run grep -n "capabilities_version\|1604f0\|version" tests/test_capabilities.py`

If a literal hash is asserted, change that assertion to verify *stability* (two calls return the same value) and *format* (16 hex chars), since this task intentionally changes the static surface:

```python
def test_capabilities_version_is_stable_16_hex(service) -> None:
    from gencc_link.mcp.capabilities import capabilities_version

    v1 = capabilities_version()
    v2 = capabilities_version()
    assert v1 == v2
    assert len(v1) == 16
    int(v1, 16)  # hex-parseable
```

- [ ] **Step 2: Write failing tests for the new doc fields** (append to `tests/test_tools.py`, inside `class TestEvalHardening`):

```python
    async def test_capabilities_documents_field_errors_and_cursor(self, mcp_client) -> None:
        result = await mcp_client.call_tool("get_server_capabilities", {})
        rf = result.structured_content["response_fields"]
        assert "field_errors" in rf
        assert "next_cursor" in rf
        assert "cursor" in rf
        resources = result.structured_content["resources"]
        assert "gencc://research-use" in resources
```

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest "tests/test_tools.py::TestEvalHardening::test_capabilities_documents_field_errors_and_cursor" -v`
Expected: FAIL — those keys aren't in the surface yet.

- [ ] **Step 4: Add the fields** in `gencc_link/mcp/capabilities.py`. In `response_fields`, add three entries:

```python
            "field_errors": "invalid_input only: a list of {field, reason} objects "
            "pinpointing each rejected argument (schema-level and domain validation).",
            "cursor": "find_curations only: an opaque, release-bound page token "
            "from a prior truncated.next_cursor; reproduces the exact next page and "
            "is rejected if the data was refreshed since it was minted.",
            "next_cursor": "find_curations truncated block: the opaque cursor to pass "
            "back as `cursor` for refresh-safe page-forward (also surfaced as the "
            "first _meta.next_commands entry).",
```

In the `resources` dict, add:

```python
            "gencc://research-use": "research-use-only notice",
```

- [ ] **Step 5: Document in the reference resource** — in `gencc_link/mcp/resources.py` `GENCC_REFERENCE_NOTES`, append (after the find_curations matching sentence):

```python
    "find_curations paging is by limit/offset within a data release, or by an "
    "opaque truncated.next_cursor that is release-bound (refresh-safe); offsets "
    "and cursors are only valid for the gencc_release shown in _meta. The "
    "invalid_input envelope includes field_errors: a list of {field, reason}. "
```

- [ ] **Step 6: Run to verify pass**

Run: `uv run pytest "tests/test_tools.py::TestEvalHardening::test_capabilities_documents_field_errors_and_cursor" tests/test_capabilities.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add gencc_link/mcp/capabilities.py gencc_link/mcp/resources.py tests/test_capabilities.py tests/test_tools.py
git commit -m "docs(D5): document field_errors, cursor/next_cursor, and research-use resource in capabilities + reference"
```

---

## Task 9: Release — version, CHANGELOG, README/guide, assessment resolution, full gate

**Files:**
- Modify: `pyproject.toml` (version 0.2.0 → 0.3.0)
- Modify: `CHANGELOG.md`
- Modify: `README.md` and/or `docs/` connection-guide (only if response-mode / citation / find_curations tables exist)
- Modify: `docs/MCP-ASSESSMENT.md` (resolution note)
- Test: `tests/` (whole suite), `make ci-local`

- [ ] **Step 1: Bump the version** in `pyproject.toml`:

```toml
version = "0.3.0"
```

- [ ] **Step 2: Add a CHANGELOG entry** at the top of `CHANGELOG.md` (above `## [0.2.0]`):

```markdown
## [0.3.0] - 2026-06-12

### Fixed
- `get_gene_disease_assertion` `minimal` mode is now summary-only; verbosity is
  strictly `minimal ≤ compact ≤ standard ≤ full` (was `compact < minimal == standard`). (D1)
- Argument-validation failures (invalid `response_mode`, unknown argument names)
  now return the structured `invalid_input` envelope with `error_code`,
  `field_errors`, and `next_commands` instead of a raw Pydantic/JSON-RPC dump,
  via a new `InputValidationMiddleware`. (D2a)
- Every `invalid_input` envelope now carries `_meta.next_commands` (empty query,
  >20 batch, bad offset, no-filter `find_curations`). (D2b)
- Case-insensitive, multi-suggestion "did you mean" filter hints; `moi="Recessive"`
  now surfaces `Autosomal recessive`. (D6)

### Added
- `find_curations` opaque, release-bound pagination `cursor` + `truncated.next_cursor`;
  the page-forward continuation is the first `_meta.next_commands` entry, so large
  sweeps are autonomous and refresh-safe (a stale cursor is rejected, not silently
  skipped/duplicated). (D3, D4)
- `resolve_identifier` accepts `identifier` as an alias for `query`.
- Capabilities/reference now document `field_errors`, `cursor`/`next_cursor`, the
  `ambiguous_query` trigger, and the `gencc://research-use` resource. (D5, D6)

### Changed
- Token efficiency: `standard` mode now uses `citation_ref` + `citation_short`
  (cite-by-ref); the verbatim `recommended_citation` is reserved for `full` mode.
  No information loss — the full citation stays at `gencc://citation`.
```

- [ ] **Step 3: Update doc tables if present.**

Run: `uv run grep -rln "response_mode\|recommended_citation\|find_curations" README.md docs/*.md 2>/dev/null`

For each hit that is a user-facing table describing response modes or the `find_curations` params, update: note standard's cite-by-ref behavior and add the `cursor`/`next_cursor` paging option. Keep edits minimal and factual. If no such tables exist, skip.

- [ ] **Step 4: Append a resolution note** to `docs/MCP-ASSESSMENT.md` (at the end, before the trailing research-use line):

```markdown
---

## Resolution (v0.3.0, 2026-06-12)

All findings addressed: D1 (minimal summary-only), D2a (validation errors →
structured `invalid_input` via middleware), D2b (next_commands on every error),
D3/D4 (release-bound opaque cursor + autonomous page-forward), D5 (`field_errors`,
`cursor`/`next_cursor` documented), D6 (`ambiguous_query` reachability test +
case-insensitive multi-suggestion hints), and the Part-1 citation tax
(cite-by-ref extended to `standard`). See
`docs/superpowers/specs/2026-06-12-mcp-consumer-uplift-9.5-design.md` and the
0.3.0 CHANGELOG entry.
```

- [ ] **Step 5: Run the full local CI gate**

Run: `make ci-local`
Expected: PASS — ruff (format + lint), mypy strict, pytest with ≥85% coverage, and `lint-loc` (no module >600 lines; `middleware.py` and `cursor.py` are small). Fix any lint/type issues surfaced (e.g., add `from typing import Any` where used, ensure `CallNext` typing on the middleware is acceptable to mypy — if mypy objects to `call_next: Any`, import the precise type: `from fastmcp.server.middleware import CallNext` and annotate `call_next: CallNext`).

- [ ] **Step 6: Verify the capabilities version actually rolled** (sanity, optional):

Run: `uv run python -c "from gencc_link.mcp.capabilities import capabilities_version; print(capabilities_version())"`
Expected: a 16-hex string (different from the assessment's `1604f03824d7c2a9` because the static surface changed).

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml CHANGELOG.md docs/MCP-ASSESSMENT.md README.md docs/*.md
git commit -m "release(0.3.0): MCP consumer-uplift to >9.5 — version, changelog, docs, assessment resolution"
```

---

## Self-review checklist (run after execution, before finishing the branch)

- [ ] **D1** verbosity ladder strict (Task 1) ✔
- [ ] **D2a** invalid response_mode + unknown arg → structured envelope (Task 3) ✔
- [ ] **D2b** every error envelope chainable (Task 2) ✔
- [ ] **D3** release-bound cursor, stale cursor rejected (Tasks 4–5) ✔
- [ ] **D4** page-forward is `next_commands[0]` on truncation (Task 5) ✔
- [ ] **D5** `field_errors` + cursor docs in capabilities/reference (Task 8) ✔
- [ ] **D6** ambiguous_query reachable test + better suggestions (Task 6) ✔
- [ ] **Token tax** standard cite-by-ref (Task 7) ✔
- [ ] `make ci-local` green (Task 9) ✔
- [ ] No module exceeds the 600-line cap (`make lint-loc`).
- [ ] Then: use `superpowers:finishing-a-development-branch` to open a PR / merge.
```
