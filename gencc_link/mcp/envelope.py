"""Shared MCP envelope boundary for GenCC-Link tools.

Tools return a plain dict; ``run_mcp_tool`` injects ``success``/``_meta`` on the
happy path and converts any exception into a structured error envelope dict
(returned, never raised) so the model sees a structured failure with a stable
``error_code`` instead of an opaque masked message.
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError as PydanticValidationError

from gencc_link.constants import CITATION_SHORT, DATA_LICENSE, RECOMMENDED_CITATION
from gencc_link.exceptions import (
    AmbiguousQueryError,
    DataUnavailableError,
    DownloadError,
    InvalidInputError,
    NotFoundError,
    QuotaExceededError,
)
from gencc_link.mcp.next_commands import recovery_commands
from gencc_link.mcp.untrusted_content import UntrustedTextLimitError, sanitize_message

logger = logging.getLogger(__name__)

# Only an identifier-like field name (a declared tool argument) is echoed to the
# caller; an arbitrary (attacker-supplied unknown-argument) name is redacted.
_SAFE_FIELD_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]{0,63}$")

# Fixed, input-free reasons keyed on the pydantic error ``type``. The raw pydantic
# ``msg`` can echo the rejected input value, so it is never surfaced verbatim.
_PYDANTIC_REASONS: dict[str, str] = {
    "missing": "required argument is missing",
    "extra_forbidden": "unexpected argument",
    "string_type": "expected a string",
    "int_type": "expected an integer",
    "int_parsing": "expected an integer",
    "float_type": "expected a number",
    "float_parsing": "expected a number",
    "bool_type": "expected a boolean",
    "bool_parsing": "expected a boolean",
    "list_type": "expected a list",
    "dict_type": "expected an object",
    "enum": "value is not one of the allowed options",
    "literal_error": "value is not one of the allowed options",
    "greater_than": "value is out of the allowed range",
    "greater_than_equal": "value is out of the allowed range",
    "less_than": "value is out of the allowed range",
    "less_than_equal": "value is out of the allowed range",
    "string_too_long": "value length is out of range",
    "string_too_short": "value length is out of range",
    "value_error": "value failed validation",
}


def _pydantic_reason(err_type: str) -> str:
    """Map a pydantic error ``type`` to a fixed, input-free reason string."""
    return _PYDANTIC_REASONS.get(err_type, "value failed validation")


def _safe_field(loc: str) -> str:
    """Return a caller-visible field name with forbidden code points stripped and
    an arbitrary (attacker-supplied unknown-argument) name redacted to ``argument``."""
    clean = sanitize_message(loc)
    return clean if _SAFE_FIELD_RE.match(clean) else "argument"


def _pydantic_loc(err: Mapping[str, Any]) -> str:
    """Safe field name for one pydantic error (``ErrorDetails``): an
    ``extra_forbidden`` key is caller-controlled and always redacted; a declared
    field is passed through ``_safe_field``."""
    if err["type"] == "extra_forbidden":
        return "argument"
    return _safe_field(".".join(str(p) for p in err["loc"]) or "input")


# Mutable provenance: the data release (GenCC run date) is known only after the
# database is built, so service_adapters calls set_data_release() at startup.
_DATA_RELEASE: str | None = None

# Short stable URI for the full citation; emitted instead of the ~260-char string
# in minimal/compact so a warm client can dereference it once and cache.
_CITATION_REF = "gencc://citation"


def set_data_release(run_date: str | None) -> None:
    """Record the GenCC data release surfaced in every tool's ``_meta``."""
    global _DATA_RELEASE
    _DATA_RELEASE = run_date


@dataclass
class McpErrorContext:
    """Per-call context so envelopes can name the failing tool and build recovery steps."""

    tool_name: str
    arguments: dict[str, Any] = field(default_factory=dict)


class McpToolError(Exception):
    """Raised inside a tool body to emit a specific error code/message."""

    def __init__(self, *, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message


def _provenance_meta(response_mode: str | None = None, *, is_error: bool = False) -> dict[str, Any]:
    """Provenance block for ``_meta``; mode-aware to cut per-call tokens.

    Policy (see docs/superpowers/specs/2026-06-12-mcp-consumer-uplift-v0.4.0):

    - ``unsafe_for_clinical_use`` rides *every* envelope (safety; non-negotiable
      for a clinical-adjacent dataset).
    - Errors carry only ``citation_ref`` -- an error has no claim to cite, so the
      verbatim citation (and even ``citation_short``) is pure boilerplate.
    - ``full`` is the maximum-detail mode: it keeps the verbatim
      ``recommended_citation`` and the session-invariant ``data_license``.
    - ``minimal``/``compact``/``standard`` carry ``citation_ref`` +
      ``citation_short`` (the short stub already encodes the CC0 license, so
      ``data_license`` is redundant there and is omitted -- it lives in the
      capabilities contract).
    - ``gencc_release`` (per-call freshness) rides every success envelope.
    """
    meta: dict[str, Any] = {"unsafe_for_clinical_use": True}
    if is_error:
        meta["citation_ref"] = _CITATION_REF
    elif response_mode == "full":
        meta["data_license"] = DATA_LICENSE
        meta["recommended_citation"] = RECOMMENDED_CITATION
    elif response_mode in ("minimal", "compact", "standard"):
        meta["citation_ref"] = _CITATION_REF
        meta["citation_short"] = CITATION_SHORT
    else:  # unset success default (rare): keep a safe verbatim citation
        meta["recommended_citation"] = RECOMMENDED_CITATION
    if response_mode:
        meta["response_mode"] = response_mode
    if _DATA_RELEASE:
        meta["gencc_release"] = _DATA_RELEASE
    return meta


def _classify(exc: BaseException) -> tuple[str, str, bool]:
    """Return (error_code, client_safe_message, retryable).

    Every exception-derived, caller-visible message is routed through
    ``sanitize_message`` (strips the fence's forbidden control/zero-width/bidi/NUL
    code points). Upstream/transport errors (download, quota) map to FIXED,
    body-free messages so an attacker-influenceable upstream body is never echoed;
    the pydantic arg-validation frame maps the error ``type`` to a fixed reason so
    the rejected input value is never surfaced verbatim.
    """
    if isinstance(exc, McpToolError):
        return (
            exc.error_code,
            sanitize_message(exc.message),
            exc.error_code in {"rate_limited", "upstream_unavailable"},
        )
    if isinstance(exc, UntrustedTextLimitError):
        # Response-Envelope v1.1: a fenced-object ceiling was exceeded (DoS
        # backstop). This is a typed limit error, never a masked internal_error.
        return "untrusted_text_limit_exceeded", sanitize_message(str(exc)), False
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
        return "not_found", sanitize_message(str(exc)), False
    if isinstance(exc, AmbiguousQueryError):
        return "ambiguous_query", sanitize_message(str(exc)), False
    if isinstance(exc, InvalidInputError):
        field = f"`{_safe_field(exc.field)}`: " if exc.field else ""
        return "invalid_input", sanitize_message(f"Invalid input -- {field}{exc.message}"), False
    if isinstance(exc, PydanticValidationError):
        first = exc.errors()[0]
        loc = _pydantic_loc(first)
        return (
            "invalid_input",
            f"Invalid input -- `{loc}`: {_pydantic_reason(first['type'])}",
            False,
        )
    return "internal_error", "An internal error occurred. The request was not completed.", False


def _recovery_action(error_code: str, retryable: bool) -> str:
    if retryable:
        return "retry_backoff"
    if error_code in {
        "invalid_input",
        "not_found",
        "ambiguous_query",
        "untrusted_text_limit_exceeded",
    }:
        return "reformulate_input"
    if error_code == "data_unavailable":
        return "build_database"
    return "switch_tool"


def _field_errors(exc: BaseException) -> list[dict[str, str]] | None:
    if isinstance(exc, InvalidInputError) and exc.field:
        return [{"field": _safe_field(exc.field), "reason": sanitize_message(exc.message)}]
    if isinstance(exc, PydanticValidationError):
        return [
            {"field": _pydantic_loc(e), "reason": _pydantic_reason(e["type"])} for e in exc.errors()
        ]
    return None


def _error_envelope(
    exc: BaseException,
    context: McpErrorContext,
    *,
    request_id: str,
    elapsed_ms: float,
) -> dict[str, Any]:
    error_code, message, retryable = _classify(exc)
    field_name = getattr(exc, "field", None)
    if field_name is None and isinstance(exc, PydanticValidationError):
        errs = exc.errors()
        if errs and errs[0]["loc"]:
            field_name = _pydantic_loc(errs[0])
    if field_name is not None:
        field_name = _safe_field(field_name)
    meta: dict[str, Any] = {"tool": context.tool_name, **_provenance_meta(is_error=True)}
    meta["request_id"] = request_id
    meta["elapsed_ms"] = elapsed_ms
    nexts = recovery_commands(context.tool_name, error_code, context.arguments, field_name)
    if nexts:
        meta["next_commands"] = nexts
    envelope: dict[str, Any] = {
        "success": False,
        "error_code": error_code,
        # Defensive backstop: no forbidden code points reach the caller, whatever path.
        "message": sanitize_message(message),
        "retryable": retryable,
        "recovery_action": _recovery_action(error_code, retryable),
        "_meta": meta,
    }
    field_errors = _field_errors(exc)
    if field_errors is not None:
        envelope["field_errors"] = field_errors
    return envelope


def validation_error_envelope(
    *,
    tool_name: str,
    arguments: dict[str, Any],
    exc: PydanticValidationError,
) -> dict[str, Any]:
    """Structured ``invalid_input`` envelope for a pre-body argument-validation
    failure (caught by the MCP middleware before the tool body runs).

    Mirrors ``_error_envelope`` exactly so an arg-validation failure is
    byte-compatible with a domain ``invalid_input`` raised inside a tool body.
    """
    ctx = McpErrorContext(tool_name=tool_name, arguments=arguments)
    return _error_envelope(exc, ctx, request_id=uuid.uuid4().hex[:12], elapsed_ms=0.0)


async def run_mcp_tool(
    tool_name: str,
    call: Callable[[], Awaitable[dict[str, Any]]],
    *,
    context: McpErrorContext | None = None,
    response_mode: str | None = None,
) -> dict[str, Any]:
    """Execute a tool body, returning the result dict or a structured error dict.

    Adds ``_meta.request_id`` + ``_meta.elapsed_ms`` (trace + server timing) and a
    mode-aware citation to every envelope, success or error.
    """
    ctx = context or McpErrorContext(tool_name=tool_name)
    request_id = uuid.uuid4().hex[:12]
    start = time.perf_counter()
    try:
        result = await call()
        elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
        if isinstance(result, dict):
            result.setdefault("success", True)
            existing_meta: dict[str, Any] = result.get("_meta") or {}
            result["_meta"] = {
                **existing_meta,
                **_provenance_meta(response_mode),
                "request_id": request_id,
                "elapsed_ms": elapsed_ms,
            }
        return result
    except Exception as exc:  # broad catch is the error-boundary contract
        elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
        envelope = _error_envelope(exc, ctx, request_id=request_id, elapsed_ms=elapsed_ms)
        logger.warning(
            "mcp_tool_error tool=%s code=%s exc=%s",
            tool_name,
            envelope["error_code"],
            exc.__class__.__name__,
        )
        return envelope
