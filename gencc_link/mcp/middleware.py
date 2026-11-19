"""FastMCP middleware that converts pre-body argument-validation failures into
the structured ``invalid_input`` envelope.

FastMCP validates tool arguments (Pydantic ``TypeAdapter``) inside
``FunctionTool.run`` *before* the tool body runs, so an invalid ``response_mode``
or an unknown argument name raises ``pydantic.ValidationError`` where the body's
``run_mcp_tool`` boundary can never catch it. This middleware wraps the call,
catches that error, and returns a normal ``ToolResult`` whose structured content
is the same ``invalid_input`` envelope a domain error would produce -- so *every*
error the client sees is chainable, never a raw Pydantic/JSON-RPC dump.
"""

from __future__ import annotations

import logging
from typing import Any

from fastmcp.exceptions import ValidationError as FastMCPValidationError
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools import ToolResult
from pydantic import ValidationError as PydanticValidationError

from gencc_link.mcp.envelope import validation_error_envelope

logger = logging.getLogger(__name__)


class InputValidationMiddleware(Middleware):
    """Re-wrap argument-validation errors as a structured ``invalid_input`` envelope."""

    async def on_call_tool(
        self,
        context: MiddlewareContext[Any],
        call_next: CallNext[Any, ToolResult],
    ) -> ToolResult:
        try:
            result = await call_next(context)
        except FastMCPValidationError as exc:
            cause = exc.__cause__
            if not isinstance(cause, PydanticValidationError):
                raise
            return self._validation_result(context, cause)
        except PydanticValidationError as exc:
            return self._validation_result(context, exc)
        return self._mark_error(result)

    @staticmethod
    def _mark_error(result: ToolResult) -> ToolResult:
        """Set MCP ``isError`` on every structured error envelope.

        The tool body returns a plain ``success: false`` dict (so the structured
        envelope survives, which a raise would discard). This is the single wire
        chokepoint that flips the protocol ``isError`` flag on -- Response-Envelope
        v1: "isError: true is REQUIRED so clients surface the error to the model for
        self-correction." A client branching on isError now sees the failure.
        """
        sc = result.structured_content
        if (
            not result.is_error
            and isinstance(sc, dict)
            and (sc.get("success") is False or sc.get("error_code"))
        ):
            return ToolResult(content=result.content, structured_content=sc, is_error=True)
        return result

    @staticmethod
    def _validation_result(
        context: MiddlewareContext[Any], exc: PydanticValidationError
    ) -> ToolResult:
        """Convert a validated argument failure into the public error envelope."""
        envelope = validation_error_envelope(
            tool_name=context.message.name,
            arguments=dict(context.message.arguments or {}),
            exc=exc,
        )
        # Field NAMES and the pydantic error type only, never the value (issue #130):
        # field names come from the envelope's redacted field_errors (unknown keys ->
        # "argument"); FastMCP's own record is scrubbed in logging_config.
        logger.warning(
            "mcp_arg_error tool=%s fields=%s types=%s",
            envelope["_meta"]["tool"],
            ",".join(e["field"] for e in envelope.get("field_errors", [])),
            ",".join(sorted({e["type"] for e in exc.errors()})),
        )
        # isError:true is REQUIRED (Response-Envelope v1): a pre-body argument
        # validation failure is still an error the client must branch on.
        return ToolResult(structured_content=envelope, is_error=True)
