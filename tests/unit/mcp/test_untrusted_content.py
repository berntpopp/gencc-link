"""Structural untrusted-text fencing contracts."""

from __future__ import annotations

import hashlib

import pytest

from gencc_link.mcp.untrusted_content import (
    UntrustedTextLimitError,
    enforce_untrusted_text_limits,
    fence_untrusted_text,
)


def test_fence_normalizes_and_removes_forbidden_controls() -> None:
    raw = "Cafe\u0301\x00\u200b\u202e\nBRCA1"
    fenced = fence_untrusted_text(raw, source="gencc", record_id="SGC-100001")

    assert fenced.kind == "untrusted_text"
    assert fenced.text == "Caf\u00e9\nBRCA1"
    assert fenced.raw_sha256 == hashlib.sha256(raw.encode("utf-8")).hexdigest()
    assert fenced.provenance.source == "gencc"
    assert fenced.provenance.record_id == "SGC-100001"


def test_fence_preserves_tabs_newlines_and_scientific_symbols() -> None:
    raw = "p.Gly12Asp\t\u0394G = \u22121.2 kcal/mol\r\n"
    assert fence_untrusted_text(raw, source="gencc", record_id="SGC-100002").text == raw


def test_limits_reject_oversized_object() -> None:
    big = fence_untrusted_text("x" * 10, source="gencc", record_id="SGC-100003")
    with pytest.raises(UntrustedTextLimitError):
        enforce_untrusted_text_limits([big], max_text_bytes=5)


def test_limits_reject_too_many_objects() -> None:
    objs = [fence_untrusted_text("x", source="gencc", record_id=str(i)) for i in range(3)]
    with pytest.raises(UntrustedTextLimitError):
        enforce_untrusted_text_limits(objs, max_objects=2)


def test_limits_allow_a_large_object_count_under_a_generous_ceiling() -> None:
    """A legitimately large batch of fenced objects must not raise under a
    generous ceiling -- proves the DoS backstop is a real ceiling, not a
    disguised low default (fleet Object-count constraint)."""
    objs = [fence_untrusted_text("x", source="gencc", record_id=str(i)) for i in range(200)]
    enforce_untrusted_text_limits(objs, max_objects=10_000)
