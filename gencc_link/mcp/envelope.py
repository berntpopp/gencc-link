"""Shared MCP envelope boundary for GenCC-Link tools.

Tools return a plain dict; ``run_mcp_tool`` injects ``success``/``_meta`` on the
happy path and converts any exception into a structured error envelope dict
(returned, never raised) so the model sees a structured failure with a stable
``error_code`` instead of an opaque masked message.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError as PydanticValidationError

from gencc_link.constants import DATA_LICENSE, RECOMMENDED_CITATION
from gencc_link.exceptions import (
    AmbiguousQueryError,
    DataUnavailableError,
    DownloadError,
    InvalidInputError,
    NotFoundError,
    QuotaExceededError,
)

logger = logging.getLogger(__name__)

# Mutable provenance: the data release (GenCC run date) is known only after the
# database is built, so service_adapters calls set_data_release() at startup.
_DATA_RELEASE: str | None = None

_BASE_META: dict[str, Any] = {
    "unsafe_for_clinical_use": True,
    "data_license": DATA_LICENSE,
    "recommended_citation": RECOMMENDED_CITATION,
}


def set_data_release(run_date: str | None) -> None:
    """Record the GenCC data release surfaced in every tool's ``_meta``."""
    global _DATA_RELEASE
    _DATA_RELEASE = run_date


@dataclass
class McpErrorContext:
    """Per-call context so envelopes can name the failing tool."""

    tool_name: str


class McpToolError(Exception):
    """Raised inside a tool body to emit a specific error code/message."""

    def __init__(self, *, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message


def _provenance_meta() -> dict[str, Any]:
    meta = dict(_BASE_META)
    if _DATA_RELEASE:
        meta["gencc_release"] = _DATA_RELEASE
    return meta


def _classify(exc: BaseException) -> tuple[str, str, bool]:
    """Return (error_code, client_safe_message, retryable)."""
    if isinstance(exc, McpToolError):
        return (
            exc.error_code,
            exc.message,
            exc.error_code in {"rate_limited", "upstream_unavailable"},
        )
    if isinstance(exc, QuotaExceededError):
        return "rate_limited", "GenCC download quota exceeded. Try again later.", True
    if isinstance(exc, DownloadError):
        return "upstream_unavailable", "Could not reach thegencc.org. Try again later.", True
    if isinstance(exc, DataUnavailableError):
        return (
            "data_unavailable",
            "GenCC database is not built. Run `make data` (gencc-link-data build).",
            False,
        )
    if isinstance(exc, NotFoundError):
        return "not_found", str(exc), False
    if isinstance(exc, AmbiguousQueryError):
        return "ambiguous_query", str(exc), False
    if isinstance(exc, InvalidInputError):
        field = f"`{exc.field}`: " if exc.field else ""
        return "invalid_input", f"Invalid input -- {field}{exc.message}", False
    if isinstance(exc, PydanticValidationError):
        first = exc.errors()[0]
        loc = ".".join(str(p) for p in first["loc"]) or "input"
        return "invalid_input", f"Invalid input -- `{loc}`: {first['msg']}", False
    return "internal_error", "An internal error occurred. The request was not completed.", False


def _recovery_action(error_code: str, retryable: bool) -> str:
    if retryable:
        return "retry_backoff"
    if error_code in {"invalid_input", "not_found", "ambiguous_query"}:
        return "reformulate_input"
    if error_code == "data_unavailable":
        return "build_database"
    return "switch_tool"


def _field_errors(exc: BaseException) -> list[dict[str, str]] | None:
    if isinstance(exc, InvalidInputError) and exc.field:
        return [{"field": exc.field, "reason": exc.message}]
    if isinstance(exc, PydanticValidationError):
        return [
            {"field": ".".join(str(p) for p in e["loc"]) or "input", "reason": e["msg"]}
            for e in exc.errors()
        ]
    return None


def _error_envelope(exc: BaseException, context: McpErrorContext) -> dict[str, Any]:
    error_code, message, retryable = _classify(exc)
    envelope: dict[str, Any] = {
        "success": False,
        "error_code": error_code,
        "message": message,
        "retryable": retryable,
        "recovery_action": _recovery_action(error_code, retryable),
        "_meta": {"tool": context.tool_name, **_provenance_meta()},
    }
    field_errors = _field_errors(exc)
    if field_errors is not None:
        envelope["field_errors"] = field_errors
    return envelope


async def run_mcp_tool(
    tool_name: str,
    call: Callable[[], Awaitable[dict[str, Any]]],
    *,
    context: McpErrorContext | None = None,
) -> dict[str, Any]:
    """Execute a tool body, returning the result dict or a structured error dict."""
    ctx = context or McpErrorContext(tool_name=tool_name)
    try:
        result = await call()
        if isinstance(result, dict):
            result.setdefault("success", True)
            existing_meta: dict[str, Any] = result.get("_meta") or {}
            result["_meta"] = {**existing_meta, **_provenance_meta()}
        return result
    except Exception as exc:  # broad catch is the error-boundary contract
        envelope = _error_envelope(exc, ctx)
        logger.warning(
            "mcp_tool_error tool=%s code=%s exc=%s",
            tool_name,
            envelope["error_code"],
            exc.__class__.__name__,
        )
        return envelope
