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


class TestEvalAdditions:
    def test_inheritance_modes_data_derived(self, service) -> None:
        from gencc_link.mcp.capabilities import build_capabilities
        from gencc_link.mcp.service_adapters import (
            reset_gencc_service,
            set_service_for_testing,
        )

        set_service_for_testing(service)
        try:
            caps = build_capabilities()
            titles = {m["title"] for m in caps["inheritance_modes"]}
            assert {"Autosomal dominant", "Autosomal recessive"} <= titles
            assert all("curie" in m for m in caps["inheritance_modes"])
        finally:
            set_service_for_testing(None)
            reset_gencc_service()

    def test_data_notes_document_passthrough(self) -> None:
        caps = build_capabilities()
        assert any("assertion_criteria_url" in note for note in caps["data_notes"])
        assert any("submission level" in note for note in caps["data_notes"])

    def test_inheritance_modes_empty_without_service(self) -> None:
        # Direct call with no service injected degrades gracefully.
        caps = build_capabilities()
        assert isinstance(caps["inheritance_modes"], list)

    def test_moi_in_parameter_conventions(self) -> None:
        caps = build_capabilities()
        assert "moi" in caps["parameter_conventions"]

    def test_response_fields_document_new_fields(self) -> None:
        caps = build_capabilities()
        for field in ("matched", "citation_ref", "request_id"):
            assert field in caps["response_fields"]

    def test_capabilities_version_stable_vs_live_data(self) -> None:
        # Data-derived additions live outside the hashed static surface.
        assert build_capabilities()["capabilities_version"] == capabilities_version()
