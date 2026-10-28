"""Regression guards for reviewed fleet release dependencies."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_release_dependencies_use_reviewed_immutable_pins() -> None:
    assert (
        "python:3.14-slim@sha256:0741d101873c12ab927e6f8653feb8862b9bd58771177acb1b885b95141f91b4"
        in (ROOT / "docker/Dockerfile").read_text()
    )
    assert (
        "astral-sh/setup-uv@1c37ad07a6a961277cf70c0d37d6f313000f5884"
        in (ROOT / ".github/workflows/ci.yml").read_text()
    )
    assert (
        "_container-ci.yml@5fed6be02ea0a598b56f7d1a69efcc47ff5796c8"
        in (ROOT / ".github/workflows/container-ci.yml").read_text()
    )
    assert (
        "_container-release.yml@5fed6be02ea0a598b56f7d1a69efcc47ff5796c8"
        in (ROOT / ".github/workflows/container-release.yml").read_text()
    )


def test_prepared_stage_upgrades_the_fixed_openssl_runtime_packages() -> None:
    dockerfile = (ROOT / "docker/Dockerfile").read_text()

    assert "apt-get install -y --only-upgrade --no-install-recommends" in dockerfile
    assert "openssl" in dockerfile
    assert "libssl3t64" in dockerfile
    assert "openssl-provider-legacy" in dockerfile


def test_production_compose_uses_the_approved_restart_policy() -> None:
    compose = (ROOT / "docker/docker-compose.prod.yml").read_text()
    assert "restart: unless-stopped" in compose
    assert "restart: on-failure" not in compose
