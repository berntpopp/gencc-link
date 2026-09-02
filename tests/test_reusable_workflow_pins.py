"""Guard the reviewed router reusable-workflow revision."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUTER_WORKFLOW_SHA = "db47bd3357cebf33e6722615c4f0e7419a64857e"
# container-release.yml pins the deployed-overlay-gate revision (router #172).
ROUTER_RELEASE_WORKFLOW_SHA = "31ea81cee5475fc3655c047c63a89739948f99a9"


def test_reusable_container_workflows_use_reviewed_router_revision() -> None:
    expected = {
        "container-ci.yml": ROUTER_WORKFLOW_SHA,
        "container-release.yml": ROUTER_RELEASE_WORKFLOW_SHA,
    }
    for workflow, sha in expected.items():
        content = (ROOT / ".github" / "workflows" / workflow).read_text(encoding="utf-8")
        assert "berntpopp/genefoundry-router/.github/workflows/_container-" in content
        assert f"@{sha}" in content


def test_data_bound_release_explicitly_remains_unadopted_without_runtime_evidence() -> None:
    config = json.loads((ROOT / "container-release.json").read_text(encoding="utf-8"))

    assert config["definitions"]["contract"] == "data-bound"
    assert config["data_identity_contract"] == "unadopted"
