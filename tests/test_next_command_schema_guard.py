"""Guard: every emitted next_command is callable against its target tool's schema.

Issue #40 D1: find_curations emitted get_gene_disease_assertion(gene=...) but that
tool has no `gene` property (it takes gene_symbol) and sets additionalProperties:
false, so the server's own recommended next step was rejected with invalid_input.

This guard DERIVES the contract from each tool's live inputSchema -- there is no
hardcoded per-tool affordance list to forget. It drives a representative set of
success- and error-path calls, collects every `_meta.next_commands` affordance
they emit, and asserts each one targets a real tool and passes only arguments that
tool actually declares. Prove it by breaking it: change any emitted affordance to a
param the target rejects and this fails.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.mcp


async def _tool_schemas(mcp_client: object) -> dict[str, dict[str, object]]:
    """Map tool name -> its advertised inputSchema (properties/required/addl-props)."""
    tools = await mcp_client.list_tools()  # type: ignore[attr-defined]
    return {t.name: (t.inputSchema or {}) for t in tools}


def _assert_callable(cmd: dict[str, object], schemas: dict[str, dict[str, object]]) -> None:
    tool = cmd["tool"]
    assert tool in schemas, f"next_command targets unknown tool {tool!r}"
    schema = schemas[tool]
    props = set((schema.get("properties") or {}).keys())
    args = cmd.get("arguments") or {}
    assert isinstance(args, dict)
    # additionalProperties defaults to false in FastMCP-generated schemas: every
    # argument name MUST be a declared property of the target tool.
    if schema.get("additionalProperties") is not True:
        unknown = set(args) - props
        assert not unknown, f"{tool}: emitted next_command args {unknown} are not in its schema"
    # A schema-`required` field with no supplied value would also be rejected at
    # the wire, unless the emitted value substitutes for it (e.g. cursor carries
    # the query). We only assert argument NAMES here; the behaviour gate exercises
    # the wire acceptance end-to-end.


async def _collect(mcp_client: object) -> list[dict[str, object]]:
    """Drive representative success/error calls; collect every emitted affordance."""
    calls: list[tuple[str, dict[str, object]]] = [
        ("search_genes", {"query": "col", "limit": 1}),
        ("search_genes", {"query": "ZZZZQQQ"}),  # zero hits -> cross-over
        ("search_diseases", {"query": "syndrome", "limit": 1}),
        ("get_gene_curations", {"gene_symbol": "COL1A1", "limit": 1}),
        ("get_disease_curations", {"disease": "MONDO:0008426", "limit": 1}),
        ("get_gene_disease_assertion", {"gene_symbol": "SKI", "disease": "MONDO:0008426"}),
        ("get_genes_curations", {"genes": ["SKI", "NOTAGENE"]}),
        ("find_curations", {"classification": ["Definitive"], "limit": 1}),
        ("find_curations", {}),  # browse
        ("resolve_identifier", {"query": "SKI"}),
        ("list_submitters", {}),
        # error paths that emit recovery next_commands
        ("get_gene_curations", {"gene_symbol": "NOTAGENE"}),
        ("find_curations", {"submitter": ["__bogus__"]}),
        ("search_genes", {"query": "   "}),
    ]
    out: list[dict[str, object]] = []
    for name, args in calls:
        result = await mcp_client.call_tool(name, args)  # type: ignore[attr-defined]
        env = result.structured_content or {}
        for cmd in (env.get("_meta") or {}).get("next_commands") or []:
            out.append(cmd)
    return out


async def test_every_next_command_matches_its_target_tool_schema(mcp_client) -> None:
    schemas = await _tool_schemas(mcp_client)
    affordances = await _collect(mcp_client)
    assert affordances, "expected the representative calls to emit next_commands"
    for cmd in affordances:
        _assert_callable(cmd, schemas)


async def test_find_curations_next_command_replays_successfully(mcp_client) -> None:
    """The exact D1 repro: replay find_curations' emitted assertion step verbatim."""
    result = await mcp_client.call_tool(
        "find_curations", {"classification": ["Definitive"], "limit": 2}
    )
    nexts = (result.structured_content["_meta"] or {}).get("next_commands") or []
    step = next(c for c in nexts if c["tool"] == "get_gene_disease_assertion")
    replay = await mcp_client.call_tool("get_gene_disease_assertion", step["arguments"])
    assert replay.structured_content["success"] is True


async def test_out_of_enum_classification_item_is_rejected(mcp_client) -> None:
    """An unknown classification ITEM (array vocabulary) errors, never silent-empty."""
    result = await mcp_client.call_tool("find_curations", {"classification": ["__bogus__"]})
    data = result.structured_content
    assert data["success"] is False, "an out-of-vocabulary classification must not succeed"
    assert data["error_code"] == "invalid_input"
    assert data.get("total", 0) == 0 or "results" not in data


async def test_out_of_enum_submitter_item_is_rejected(mcp_client) -> None:
    """An unknown submitter ITEM errors with the accepted-roster hint, never silent-empty."""
    result = await mcp_client.call_tool("find_curations", {"submitter": ["__bogus__"]})
    data = result.structured_content
    assert data["success"] is False, "an out-of-vocabulary submitter must not succeed"
    assert data["error_code"] == "invalid_input"
