"""Guard: every emitted next_command is a VALID call against its target tool's schema.

Issue #40 D1: find_curations emitted get_gene_disease_assertion(gene=...) but that
tool has no `gene` property (it takes gene_symbol) and sets additionalProperties:
false, so the server's own recommended next step was rejected with invalid_input.

This guard performs REAL JSON Schema validation (Draft 2020-12) of each emitted
`_meta.next_commands` affordance against the **target tool's live inputSchema** —
required fields, types, enums and additionalProperties, not merely argument names.
So an affordance that omits a required field (e.g. `search_genes(cursor=...)` with
no `query`) is caught here, exactly the class this PR claims to close.

The source calls are DERIVED FROM THE REGISTRY: every tool is exercised with a valid
call built from its own `examples` (plus a few error paths for recovery coverage),
so a newly-added tool is swept automatically with nothing to hand-maintain.
"""

from __future__ import annotations

from typing import Any

import pytest
from jsonschema import Draft202012Validator

pytestmark = pytest.mark.mcp


async def _tools(mcp_client: object) -> list[Any]:
    return await mcp_client.list_tools()  # type: ignore[attr-defined]


def _valid_args_from_examples(schema: dict[str, Any]) -> dict[str, Any] | None:
    """Build a minimal valid call from a tool's own required-property examples."""
    props = schema.get("properties") or {}
    args: dict[str, Any] = {}
    for name in schema.get("required") or []:
        examples = (props.get(name) or {}).get("examples")
        if not examples:
            return None
        args[name] = examples[0]
    return args


async def _collect(mcp_client: object, tools: list[Any]) -> list[dict[str, Any]]:
    """Drive a registry-derived call set; collect every emitted next_command."""
    # Registry-derived: one valid call per tool, built from its own examples.
    calls: list[tuple[str, dict[str, Any]]] = []
    for t in tools:
        args = _valid_args_from_examples(t.inputSchema or {})
        if args is not None:
            calls.append((t.name, args))
    # A few extra paths the example-built calls don't reach: pagination follow-ups
    # and error-envelope recovery commands.
    calls += [
        ("search_genes", {"query": "col", "limit": 1}),
        ("get_gene_curations", {"gene_symbol": "COL1A1", "limit": 1}),
        ("find_curations", {}),  # browse
        ("get_gene_curations", {"gene_symbol": "NOTAGENE"}),  # not_found recovery
        ("find_curations", {"submitter": ["__bogus__"]}),  # invalid_input recovery
        ("search_genes", {"query": "   "}),  # blank-query recovery
    ]
    out: list[dict[str, Any]] = []
    for name, args in calls:
        result = await mcp_client.call_tool(name, args, raise_on_error=False)  # type: ignore[attr-defined]
        env = result.structured_content or {}
        for cmd in (env.get("_meta") or {}).get("next_commands") or []:
            out.append(cmd)
    return out


async def test_every_next_command_is_valid_against_its_target_schema(mcp_client) -> None:
    tools = await _tools(mcp_client)
    validators = {t.name: Draft202012Validator(t.inputSchema or {}) for t in tools}

    affordances = await _collect(mcp_client, tools)
    assert affordances, "expected the representative calls to emit next_commands"

    for cmd in affordances:
        tool = cmd["tool"]
        assert tool in validators, f"next_command targets unknown tool {tool!r}"
        errors = sorted(validators[tool].iter_errors(cmd.get("arguments") or {}), key=str)
        assert not errors, (
            f"emitted next_command for {tool!r} is not a valid call: "
            f"{[e.message for e in errors]} (args={cmd.get('arguments')!r})"
        )


async def test_the_guard_has_teeth(mcp_client) -> None:
    """A next_command missing a required arg MUST be caught (proves the guard works)."""
    tools = await _tools(mcp_client)
    schema = next(t.inputSchema for t in tools if t.name == "search_genes")
    validator = Draft202012Validator(schema)
    # `query` is required; a cursor-only affordance (a broken pagination shape) is invalid.
    assert list(validator.iter_errors({"cursor": "abc"})), (
        "guard must reject an affordance missing required `query`"
    )
    # A wrong-name affordance (the exact D1 shape) is also invalid.
    assertion_schema = next(t.inputSchema for t in tools if t.name == "get_gene_disease_assertion")
    v2 = Draft202012Validator(assertion_schema)
    assert list(v2.iter_errors({"gene": "HGNC:1", "disease": "MONDO:1"})), (
        "guard must reject the `gene=` D1 affordance shape"
    )


async def test_out_of_enum_classification_item_is_rejected(mcp_client) -> None:
    """An unknown classification ITEM (array vocabulary) errors, never silent-empty."""
    result = await mcp_client.call_tool(
        "find_curations", {"classification": ["__bogus__"]}, raise_on_error=False
    )
    data = result.structured_content
    assert data["success"] is False, "an out-of-vocabulary classification must not succeed"
    assert data["error_code"] == "invalid_input"


async def test_classification_is_case_insensitive(mcp_client) -> None:
    """The runtime accepts lowercase (matches the description); the schema enum is
    documented in canonical case but is not strictly pydantic-enforced."""
    result = await mcp_client.call_tool(
        "find_curations", {"classification": ["definitive"], "limit": 1}, raise_on_error=False
    )
    data = result.structured_content
    assert data["success"] is True, "lowercase 'definitive' must be accepted (case-insensitive)"


async def test_out_of_enum_submitter_item_is_rejected(mcp_client) -> None:
    """An unknown submitter ITEM errors with the accepted-roster hint, never silent-empty."""
    result = await mcp_client.call_tool(
        "find_curations", {"submitter": ["__bogus__"]}, raise_on_error=False
    )
    data = result.structured_content
    assert data["success"] is False, "an out-of-vocabulary submitter must not succeed"
    assert data["error_code"] == "invalid_input"


async def test_blank_filter_value_is_invalid_not_browse(mcp_client) -> None:
    """A blank filter value must be invalid_input, never an unfiltered whole-catalog browse."""
    for args in ({"gene_symbol": " "}, {"disease": ""}, {"classification": []}, {"submitter": []}):
        result = await mcp_client.call_tool("find_curations", args, raise_on_error=False)
        data = result.structured_content
        assert data["success"] is False, f"blank filter {args} must not browse the whole catalog"
        assert data["error_code"] == "invalid_input"
