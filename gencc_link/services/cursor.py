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


def decode_paged_cursor(token: str, *, current_release: str | None) -> dict[str, Any]:
    """Decode a page cursor and reject one minted against a stale data release.

    The single decode + stale-reject helper shared by every paged tool
    (find_curations, search_genes/diseases, get_gene/disease_curations). Returns
    the decoded payload (``{"v","r","o","lim","flt"}``). Raises ``ValueError`` on
    malformation/version mismatch (via :func:`decode_cursor`) or when the
    cursor's release no longer matches ``current_release`` -- the refresh-safe
    guarantee that a weekly data refresh can't silently skip or duplicate rows.
    """
    payload = decode_cursor(token)
    if payload["r"] != current_release:
        raise ValueError(
            f"Cursor was minted against GenCC release {payload['r']!r} but the "
            f"current release is {current_release!r}; restart the sweep."
        )
    return payload
