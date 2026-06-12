"""Opaque, stateless pagination cursor for ``find_curations``.

A cursor encodes the full query -- canonical filters, response mode, offset, and
limit -- plus the GenCC data release it was minted against. A page-forward call
therefore reproduces the exact next page with no server state, and the server can
reject a cursor minted against a now-stale release (refresh-safe paging) instead
of silently skipping or duplicating rows across a weekly data refresh.
"""

from __future__ import annotations

import base64
import json
from typing import Any

_CURSOR_VERSION = 1


def encode_cursor(
    *,
    release: str | None,
    offset: int,
    limit: int,
    filters: dict[str, Any],
) -> str:
    """Encode an opaque, url-safe cursor token (no padding)."""
    payload = {"v": _CURSOR_VERSION, "r": release, "o": offset, "lim": limit, "flt": filters}
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(token: str) -> dict[str, Any]:
    """Decode a cursor token; raise ``ValueError`` on any malformation."""
    try:
        padded = token + "=" * (-len(token) % 4)
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
        payload = json.loads(raw)
    except Exception as exc:  # malformed base64 / json
        raise ValueError("cursor is malformed") from exc
    if not isinstance(payload, dict) or payload.get("v") != _CURSOR_VERSION:
        raise ValueError("cursor version is unsupported")
    if not isinstance(payload.get("o"), int) or not isinstance(payload.get("lim"), int):
        raise ValueError("cursor offset/limit invalid")
    if not isinstance(payload.get("flt"), dict):
        raise ValueError("cursor filters invalid")
    return payload
