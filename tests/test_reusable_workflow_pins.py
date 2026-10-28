"""Guard the reviewed router reusable-workflow revision."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# genefoundry-router v0.10.5
# Both reusable workflows must pin the same router revision: _container-ci.yml
# also loads ReleaseConfig from the pinned commit to validate
# container-release.json, so an older pin there rejects the new fields.
ROUTER_WORKFLOW_SHA = "5fed6be02ea0a598b56f7d1a69efcc47ff5796c8"


def test_reusable_container_workflows_use_reviewed_router_revision() -> None:
    for workflow in ("container-ci.yml", "container-release.yml"):
        content = (ROOT / ".github" / "workflows" / workflow).read_text(encoding="utf-8")
        assert "berntpopp/genefoundry-router/.github/workflows/_container-" in content
        assert f"@{ROUTER_WORKFLOW_SHA}" in content


def test_data_bound_release_explicitly_remains_unadopted_without_runtime_evidence() -> None:
    config = json.loads((ROOT / "container-release.json").read_text(encoding="utf-8"))

    assert config["definitions"]["contract"] == "data-bound"
    assert config["data_identity_contract"] == "unadopted"
