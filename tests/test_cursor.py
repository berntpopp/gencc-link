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


class TestDecodePagedCursor:
    def test_round_trip(self) -> None:
        from gencc_link.services.cursor import decode_paged_cursor, encode_cursor

        tok = encode_cursor(release="2026-06-07", offset=4, limit=2, filters={"query": "col"})
        st = decode_paged_cursor(tok, current_release="2026-06-07")
        assert st["o"] == 4 and st["lim"] == 2 and st["flt"]["query"] == "col"

    def test_rejects_stale_release(self) -> None:
        import pytest

        from gencc_link.services.cursor import decode_paged_cursor, encode_cursor

        tok = encode_cursor(release="2026-05-01", offset=0, limit=2, filters={})
        with pytest.raises(ValueError) as exc:
            decode_paged_cursor(tok, current_release="2026-06-07")
        assert "2026-05-01" in str(exc.value) and "2026-06-07" in str(exc.value)

    def test_rejects_malformed(self) -> None:
        import pytest

        from gencc_link.services.cursor import decode_paged_cursor

        with pytest.raises(ValueError):
            decode_paged_cursor("!!!notbase64!!!", current_release="2026-06-07")
