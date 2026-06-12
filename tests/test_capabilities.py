"""Tests for the capabilities surface (gencc_link.mcp.capabilities)."""

from __future__ import annotations

import re

from gencc_link.mcp.capabilities import (
    TOOLS,
    build_capabilities,
    capabilities_version,
)


class TestBuildCapabilities:
    def test_ten_tools(self) -> None:
        caps = build_capabilities()
        assert len(caps["tools"]) == 10
        assert len(TOOLS) == 10

    def test_has_classifications(self) -> None:
        caps = build_capabilities()
        assert caps["classifications"]
        definitive = next(c for c in caps["classifications"] if c["title"] == "Definitive")
        assert definitive["rank"] == 6
        # Ordered best -> worst.
        ranks = [c["rank"] for c in caps["classifications"]]
        assert ranks == sorted(ranks, reverse=True)

    def test_response_modes(self) -> None:
        caps = build_capabilities()
        assert set(caps["response_modes"]) == {"minimal", "compact", "standard", "full"}
        assert caps["response_modes_list"] == ["minimal", "compact", "standard", "full"]

    def test_error_codes(self) -> None:
        caps = build_capabilities()
        for code in ("invalid_input", "not_found", "data_unavailable", "internal_error"):
            assert code in caps["error_codes"]

    def test_capabilities_version_16_hex(self) -> None:
        caps = build_capabilities()
        version = caps["capabilities_version"]
        assert len(version) == 16
        assert re.fullmatch(r"[0-9a-f]{16}", version)

    def test_data_status_valid(self) -> None:
        caps = build_capabilities()
        assert caps["data"]["status"] in {"ready", "unavailable"}

    def test_resources_listed(self) -> None:
        caps = build_capabilities()
        assert "gencc://capabilities" in caps["resources"]


class TestCapabilitiesVersion:
    def test_stable_across_calls(self) -> None:
        assert capabilities_version() == capabilities_version()

    def test_matches_surface(self) -> None:
        caps = build_capabilities()
        assert capabilities_version() == caps["capabilities_version"]
