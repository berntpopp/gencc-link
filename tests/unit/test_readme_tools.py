"""README Standard v1 guard -- the '## Tools' table is the registered tool surface.

The README's tool table is the front door's contract: a reader (and every fleet
audit) trusts it to be the complete, current list of what this server exposes.
Hand-maintained tables rot the moment a tool is added or renamed, so this test
owns it: the table's tool names must equal the *live* registered tools exactly.

The live list is obtained exactly as ``tests/test_tool_naming.py`` obtains it --
``create_gencc_mcp().list_tools()`` on the real facade -- so the two guards can
never disagree about what "registered" means.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from gencc_link.mcp.facade import create_gencc_mcp

pytestmark = pytest.mark.mcp

README = Path(__file__).resolve().parents[2] / "README.md"

#: A table row's first cell, when it is a single `backticked` tool name.
_TOOL_CELL_RE = re.compile(r"^\|\s*`([a-z0-9_]+)`\s*\|")


def _readme_tool_table_names() -> set[str]:
    """Tool names listed in the README's '## Tools' table."""
    lines = README.read_text(encoding="utf-8").splitlines()
    try:
        start = lines.index("## Tools")
    except ValueError:  # pragma: no cover - defended by test_tools_section_exists
        pytest.fail("README.md has no '## Tools' section")

    names: set[str] = set()
    for line in lines[start + 1 :]:
        if line.startswith("## "):  # next section ends the table
            break
        if match := _TOOL_CELL_RE.match(line):
            names.add(match.group(1))
    return names


async def _registered_tool_names() -> set[str]:
    """The live tool names registered on the facade (same source as test_tool_naming)."""
    return {tool.name for tool in await create_gencc_mcp().list_tools()}


def test_tools_section_exists() -> None:
    assert "## Tools" in README.read_text(encoding="utf-8").splitlines()


async def test_readme_tool_table_matches_registered_tools() -> None:
    documented = _readme_tool_table_names()
    registered = await _registered_tool_names()

    assert documented == registered, (
        "README '## Tools' table has drifted from the registered tool surface. "
        f"Missing from README: {sorted(registered - documented)}; "
        f"listed but not registered: {sorted(documented - registered)}"
    )
