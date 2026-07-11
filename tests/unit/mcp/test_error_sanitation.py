"""Unit contract for the ``sanitize_message`` error-string primitive.

``sanitize_message`` strips the fence's ratified control/zero-width/bidi/NUL code
points from every caller-visible message/error/diagnostics string and length-caps
the result. It does NOT (and is not meant to) remove injection prose -- that is
severed at the source for attacker-influenceable strings.
"""

from __future__ import annotations

from gencc_link.mcp.untrusted_content import (
    FORBIDDEN_CODEPOINTS,
    MAX_MESSAGE_CHARS,
    sanitize_message,
)


def test_strips_nul() -> None:
    assert sanitize_message("a\x00b") == "ab"


def test_strips_zero_width_joiner() -> None:
    assert sanitize_message("a‍b") == "ab"


def test_strips_bom() -> None:
    assert sanitize_message("a﻿b") == "ab"


def test_strips_rtl_override() -> None:
    assert sanitize_message("a‮b") == "ab"


def test_preserves_ordinary_prose() -> None:
    text = "GenCC database is not built. Run `make data`."
    assert sanitize_message(text) == text


def test_preserves_tabs_and_newlines_absent_from_forbidden_set() -> None:
    # Tab (0x09) and newline (0x0A) are deliberately NOT in the forbidden set.
    assert sanitize_message("a\tb\nc") == "a\tb\nc"


def test_removes_every_forbidden_codepoint() -> None:
    hostile = "safe" + "".join(chr(cp) for cp in sorted(FORBIDDEN_CODEPOINTS)) + "tail"
    cleaned = sanitize_message(hostile)
    assert cleaned == "safetail"
    assert not any(ord(ch) in FORBIDDEN_CODEPOINTS for ch in cleaned)


def test_length_capped() -> None:
    out = sanitize_message("x" * 1000)
    assert len(out) == MAX_MESSAGE_CHARS == 280
