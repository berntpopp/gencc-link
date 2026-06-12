"""Batch input hygiene for the multi-gene / multi-disease curation tools.

Pure helpers shared by ``get_genes_curations`` / ``get_diseases_curations``:
validate + de-duplicate the raw input list (echoing folded duplicates instead
of silently collapsing the count), and assemble the batch response envelope.
"""

from __future__ import annotations

from typing import Any

from gencc_link.exceptions import InvalidInputError

_BATCH_MAX = 20


def dedupe_batch(items: list[str], *, field: str) -> tuple[list[str], list[str]]:
    """Validate and case-insensitively de-duplicate a batch input list.

    Returns ``(ordered, duplicates)`` where ``duplicates`` are the folded
    (dropped) raw values, so the caller can echo them instead of silently
    collapsing the requested count. Raises ``InvalidInputError`` on an empty
    list, an over-cap list (> ``_BATCH_MAX``), or a non-string/blank value.
    """
    if not items:
        raise InvalidInputError(f"{field} must not be empty.", field=field)
    if len(items) > _BATCH_MAX:
        raise InvalidInputError(
            f"Too many values ({len(items)}); max {_BATCH_MAX} per call.", field=field
        )
    seen: set[str] = set()
    ordered: list[str] = []
    duplicates: list[str] = []
    for raw in items:
        if not isinstance(raw, str) or not raw.strip():
            raise InvalidInputError(f"each {field} value must be a non-empty string.", field=field)
        value = raw.strip()
        if value.lower() in seen:
            duplicates.append(value)
            continue
        seen.add(value.lower())
        ordered.append(value)
    return ordered, duplicates


def batch_payload(
    *,
    noun: str,
    received: int,
    ordered: list[str],
    results: list[dict[str, Any]],
    unresolved: list[dict[str, str]],
    duplicates: list[str],
) -> dict[str, Any]:
    """Assemble a batch response: headline + received/requested counts + echoes."""
    fold = f" ({len(duplicates)} duplicate(s) folded)" if duplicates else ""
    payload: dict[str, Any] = {
        "headline": (
            f"Curations for {len(results)} of {len(ordered)} requested {noun}(s) "
            f"({len(unresolved)} unresolved){fold}."
        ),
        "received": received,
        "requested": len(ordered),
        "count": len(results),
        "results": results,
    }
    if duplicates:
        payload["duplicates"] = duplicates
    if unresolved:
        payload["unresolved"] = unresolved
    return payload
