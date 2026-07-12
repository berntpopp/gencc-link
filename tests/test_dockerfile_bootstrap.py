"""Security guard: the builder must install ``uv`` from a digest-pinned image
layer (a reproducible, supply-chain-anchored artifact) rather than a floating
``pip install --upgrade`` bootstrap. Research use only; not clinical decision
support."""

from __future__ import annotations

from pathlib import Path


def test_dockerfile_pins_uv_and_has_no_floating_pip_upgrade() -> None:
    text = Path("docker/Dockerfile").read_text()
    assert "pip install --upgrade" not in text
    assert (
        "ghcr.io/astral-sh/uv:0.8.7@sha256:"
        "1e26f9a868360eeb32500a35e05787ffff3402f01a8dc8168ef6aee44aef0aab" in text
    )
