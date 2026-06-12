"""Enums and literals shared across GenCC-Link layers."""

from __future__ import annotations

from typing import Literal

# Response verbosity. Tools default to "compact"; widen only when needed.
#   minimal  - ids + headline + counts only
#   compact  - default; consensus + submitter summary, no free-text notes
#   standard - adds per-submitter MOI, dates, report URLs
#   full     - adds raw submission rows incl. notes and submitted_as_* fields
ResponseMode = Literal["minimal", "compact", "standard", "full"]

RESPONSE_MODES: tuple[ResponseMode, ...] = ("minimal", "compact", "standard", "full")
