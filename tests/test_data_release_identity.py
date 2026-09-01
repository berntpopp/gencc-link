"""Regression guards for the observed upstream-live GenCC data identity."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_container_release_tracks_current_observed_sqlite_identity() -> None:
    config = json.loads((ROOT / "container-release.json").read_text(encoding="utf-8"))
    data = config["data"]

    assert data["mode"] == "upstream-live"
    assert data["release_tag"] == "observed-2026.08.30"
    assert (
        data["digest"] == "sha256:04834b2adb9134a451eb4458cdf929e164be04757422e777336b0e05fe3cf1f0"
    )
    assert data["reproducible_rollback"] is False
    assert config["data_identity_contract"] == "unadopted"


def test_data_lifecycle_records_capture_only_provenance() -> None:
    evidence = (ROOT / "docs/data-lifecycle.md").read_text(encoding="utf-8")

    assert "observed-2026.08.30" in evidence
    assert "69cabf794f61c2680a5e9e28d00a6fa7276722392fba4b249a5cfe021f43d362" in evidence
    assert "04834b2adb9134a451eb4458cdf929e164be04757422e777336b0e05fe3cf1f0" in evidence
    assert "capture-only" in evidence
    assert "does not establish" in evidence.lower()
    assert "upstream authenticity" in evidence.lower()
