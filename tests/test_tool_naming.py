"""Tool-Naming Standard v1 guard -- every registered MCP tool must be fleet-compliant.

The contract is a verbatim copy of genefoundry-router's ``cli.check_leaf_name``
(``CANONICAL_VERBS``, ``ACTION_VERB_EXCEPTIONS``, ``LEAF_NAME_RE``) so the gateway
and every ``-link`` leaf agree on what a compliant tool name is. Adding a
non-compliant tool (server-prefixed, camelCase, non-canonical verb, or >50 chars)
fails CI here -- this is issue #3 Rule 8 / the Definition-of-Done lint guard.
"""

from __future__ import annotations

import re

import pytest

from gencc_link.mcp.capabilities import TOOLS
from gencc_link.mcp.facade import create_gencc_mcp

pytestmark = pytest.mark.mcp

# --- Tool-Naming Standard v1 contract (mirror of genefoundry-router/cli.py) ---
LEAF_NAME_RE = re.compile(r"^[a-z0-9_]{1,50}$")
CANONICAL_VERBS = {"get", "search", "list", "resolve", "find", "compare", "compute"}
ACTION_VERB_EXCEPTIONS = {
    "predict",
    "analyze",
    "annotate",
    "submit",
    "export",
    "generate",
    "download",
}


def check_leaf_name(leaf: str) -> list[str]:
    """Return Tool-Naming Standard v1 violations for a single leaf tool name."""
    issues: list[str] = []
    if not LEAF_NAME_RE.match(leaf):
        issues.append(f"charset/length: {leaf!r} must match ^[a-z0-9_]{{1,50}}$ (<=50)")
    verb = leaf.split("_", 1)[0]
    if verb not in CANONICAL_VERBS and verb not in ACTION_VERB_EXCEPTIONS:
        issues.append(f"verb: {leaf!r} starts with non-canonical verb {verb!r}")
    return issues


async def _registered_tools() -> list:
    """The live tool objects (name + tags) registered on the facade."""
    return await create_gencc_mcp().list_tools()


async def test_every_tool_name_is_standard_v1_compliant() -> None:
    tools = await _registered_tools()
    assert tools, "no tools registered"
    violations = {t.name: issues for t in tools if (issues := check_leaf_name(t.name))}
    assert not violations, f"Tool-Naming Standard v1 violations: {violations}"


async def test_every_tool_has_a_domain_tag() -> None:
    tools = await _registered_tools()
    untagged = [t.name for t in tools if not getattr(t, "tags", None)]
    assert not untagged, f"tools missing a domain tag (Rule 6): {untagged}"


async def test_live_tools_match_capabilities_tools() -> None:
    live = {t.name for t in await _registered_tools()}
    assert live == set(TOOLS), f"capabilities.TOOLS drift: {live ^ set(TOOLS)}"


def test_check_leaf_name_flags_known_violations() -> None:
    # server-prefixed + camelCase + non-canonical verb
    assert check_leaf_name("gnomad_fetchVariant")
    # >50 chars trips the length rule
    assert any("50" in i for i in check_leaf_name("get_" + "x" * 60))
    # a compliant name has no issues
    assert check_leaf_name("get_gene_curations") == []
