"""Response-Envelope Standard v1.2: every data tool's result validates against the
published JSON Schema and names its provenance."""

from __future__ import annotations

import hashlib
import json
from typing import Any

import jsonschema
import pytest

from gencc_link.mcp.envelope import set_data_release
from tests.conformance.envelope_schema import SCHEMA, SCHEMA_FILE, assert_data_envelope

# Orient a client and return no upstream data: outside the v1.2 provenance rule.
OPS_TOOLS = {"get_server_capabilities", "get_gencc_diagnostics"}
# The schema example of this tool is not in the sample database.
ARGS = {"resolve_identifier": {"query": "SKI"}}


@pytest.fixture
def release(repository: Any) -> Any:
    """Publish the sample database's release the way server startup does."""
    meta = repository.get_meta()
    set_data_release(meta.gencc_run_date, meta.build_utc)
    yield meta
    set_data_release(None)


def test_vendored_schema_matches_pinned_sha256() -> None:
    pinned = SCHEMA_FILE.with_suffix(".sha256").read_text().split()[0]
    assert hashlib.sha256(SCHEMA_FILE.read_bytes()).hexdigest() == pinned


async def test_every_data_tool_result_validates_and_carries_provenance(
    mcp_client: Any, release: Any
) -> None:
    checked = 0
    for tool in await mcp_client.list_tools():
        if tool.name in OPS_TOOLS:
            continue
        schema = tool.input_schema
        args = ARGS.get(tool.name) or {
            k: schema["properties"][k]["examples"][0] for k in schema.get("required", [])
        }
        result = await mcp_client.call_tool(tool.name, args)
        envelope = result.structured_content
        assert json.loads(result.content[0].text) == envelope, tool.name
        try:
            assert_data_envelope(envelope)
        except (AssertionError, jsonschema.ValidationError) as exc:
            raise AssertionError(f"{tool.name}: {exc}") from exc
        meta = envelope["_meta"]
        assert meta["source"] == "gencc"
        assert meta["data_version"] == release.gencc_run_date
        assert meta["retrieved_at"][:19] == release.build_utc[:19]
        checked += 1
    assert checked == 10


async def test_error_envelope_validates_against_schema(mcp_client: Any) -> None:
    result = await mcp_client.call_tool("get_gene_curations", {"gene_symbol": "NOTAGENE1"})
    assert result.structured_content["success"] is False
    jsonschema.validate(result.structured_content, SCHEMA)
