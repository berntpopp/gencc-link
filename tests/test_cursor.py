"""Unit tests for the opaque find_curations pagination cursor."""

from __future__ import annotations

import base64
import json

import pytest

from gencc_link.services.cursor import decode_cursor, encode_cursor


def test_round_trip() -> None:
    token = encode_cursor(
        release="2026-06-07",
        offset=50,
        limit=50,
        filters={"classification": ["Definitive"], "has_conflict": None},
    )
    assert isinstance(token, str)
    assert "=" not in token  # url-safe, unpadded
    decoded = decode_cursor(token)
    assert decoded["o"] == 50
    assert decoded["lim"] == 50
    assert decoded["r"] == "2026-06-07"
    assert decoded["flt"]["classification"] == ["Definitive"]


def test_malformed_cursor_raises_value_error() -> None:
    with pytest.raises(ValueError):
        decode_cursor("!!!not-base64!!!")


def test_wrong_version_raises_value_error() -> None:
    raw = base64.urlsafe_b64encode(json.dumps({"v": 999}).encode()).decode().rstrip("=")
    with pytest.raises(ValueError):
        decode_cursor(raw)
