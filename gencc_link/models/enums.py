"""Enums and literals shared across GenCC-Link layers."""

from __future__ import annotations

from typing import Literal, get_args

from gencc_link.constants import CLASSIFICATION_ORDER

# Response verbosity. Tools default to "compact"; widen only when needed.
#   minimal  - ids + headline + counts only
#   compact  - default; consensus + submitter summary, no free-text notes
#   standard - adds per-submitter MOI, dates, report URLs
#   full     - adds raw submission rows incl. notes and submitted_as_* fields
ResponseMode = Literal["minimal", "compact", "standard", "full"]

RESPONSE_MODES: tuple[ResponseMode, ...] = ("minimal", "compact", "standard", "full")

# Closed GenCC classification vocabulary, ranked best -> worst. Declared as a
# Literal so the enum appears in every tool's inputSchema (TOOL-SCHEMA-DOCUMENTATION
# S4): a value outside the set is rejected at the schema boundary, never silently
# matched to zero rows. The runtime filter (services.filters) is a case-insensitive
# SUPERSET of this schema, so a schema-valid (exact-case) value always resolves.
Classification = Literal[
    "Definitive",
    "Strong",
    "Moderate",
    "Supportive",
    "Limited",
    "Disputed Evidence",
    "Refuted Evidence",
    "Animal Model Only",
    "No Known Disease Relationship",
]

# Guard: the declared Literal MUST stay byte-identical to the authoritative
# CLASSIFICATION_ORDER in constants.py (a drift there would silently narrow the
# schema below the runtime and reject a valid classification). Fails at import
# time so the mismatch can never ship.
if tuple(get_args(Classification)) != tuple(CLASSIFICATION_ORDER):
    raise RuntimeError(
        "Classification Literal is out of sync with CLASSIFICATION_ORDER; "
        "update models/enums.py to match constants.py."
    )

# resolve_identifier scope: which record type(s) to resolve against.
ResolveKind = Literal["auto", "gene", "disease"]
