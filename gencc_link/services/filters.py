"""Validation + canonicalisation of ``find_curations`` enum filters.

Pure functions with no repository or MCP dependency: the caller passes the
data-derived valid sets in. Out-of-vocabulary values raise ``InvalidInputError``
with the accepted values and a "did you mean" suggestion, turning the previous
silent ``count: 0`` into an actionable error. Canonicalisation also fixes the
case-sensitivity trap (``"definitive"``/``"clingen"`` previously matched nothing
because the underlying SQL uses case-sensitive ``IN (...)``).
"""

from __future__ import annotations

import difflib

from gencc_link.constants import CLASSIFICATION_ORDER
from gencc_link.exceptions import InvalidInputError


def _suggest(value: str, options: list[str]) -> str:
    match = difflib.get_close_matches(value, options, n=1, cutoff=0.4)
    return f" Did you mean {match[0]!r}?" if match else ""


def _canonical_map(values: set[str]) -> dict[str, str]:
    """Map a case-folded form to the canonical stored value."""
    return {v.casefold(): v for v in values}


def _validate_list(
    values: list[str],
    canon: dict[str, str],
    *,
    field: str,
    label: str,
    accepted_hint: str,
) -> list[str]:
    out: list[str] = []
    invalid: list[str] = []
    for v in values:
        hit = canon.get(v.strip().casefold())
        if hit is None:
            invalid.append(v)
        else:
            out.append(hit)
    if invalid:
        listed = ", ".join(repr(x) for x in invalid)
        suggestion = _suggest(invalid[0], list(canon.values()))
        verb = "is not a valid" if len(invalid) == 1 else "are not valid"
        noun = label if len(invalid) == 1 else f"{label} values"
        raise InvalidInputError(
            f"{listed} {verb} {noun}.{suggestion} {accepted_hint}",
            field=field,
        )
    return out


def validate_find_filters(
    *,
    classification: list[str] | None,
    submitter: list[str] | None,
    moi: str | None,
    valid_submitter_titles: set[str],
    valid_submitter_curies: set[str],
    valid_moi_titles: set[str],
) -> tuple[list[str] | None, list[str] | None, str | None]:
    """Validate + canonicalise enum filters, or raise ``InvalidInputError``.

    Returns the canonical ``(classification, submitter, moi)`` to hand to the
    repository so case and vocabulary mismatches can never silently match zero.
    """
    canon_class: list[str] | None = None
    if classification:
        canon_class = _validate_list(
            classification,
            {c.casefold(): c for c in CLASSIFICATION_ORDER},
            field="classification",
            label="classification",
            accepted_hint=f"Accepted: {', '.join(CLASSIFICATION_ORDER)}.",
        )

    canon_subm: list[str] | None = None
    if submitter:
        canon_subm = _validate_list(
            submitter,
            _canonical_map(valid_submitter_titles | valid_submitter_curies),
            field="submitter",
            label="submitter",
            accepted_hint="Call list_submitters for the accepted roster.",
        )

    canon_moi: str | None = None
    if moi and moi.strip():
        accepted = ", ".join(sorted(valid_moi_titles))
        canon_moi = _validate_list(
            [moi],
            _canonical_map(valid_moi_titles),
            field="moi",
            label="mode of inheritance",
            accepted_hint=f"Accepted: {accepted}.",
        )[0]

    return canon_class, canon_subm, canon_moi
