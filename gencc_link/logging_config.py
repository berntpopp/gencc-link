"""Structured logging for GenCC-Link.

All logs go to stderr so the stdio MCP transport (which uses stdout for JSON-RPC
framing) is never corrupted.
"""

from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING, Any

import structlog

from . import __version__
from .config import settings

if TYPE_CHECKING:
    from structlog.typing import FilteringBoundLogger


def _add_static_fields(_logger: Any, _name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    event_dict.setdefault("service", "gencc-link")
    event_dict.setdefault("version", __version__)
    return event_dict


# FastMCP logs the COMPLETE pydantic argument-validation error -- the rejected,
# caller-controlled input (incl. hostile control/zero-width/bidi/NUL code points)
# via ``cause.errors(include_url=False)`` -- and the caller-requested tool name at
# ``fastmcp/server/server.py`` BEFORE our InputValidationMiddleware can sanitize
# the caller-facing frame. That caller input reaches the stderr handler through the
# record's ``msg``/``args`` (and any ``exc_info``/``exc_text`` traceback). Scrub it.
_FASTMCP_SERVER_LOGGER = "fastmcp.server.server"


class _FastMCPLogScrubber(logging.Filter):
    """Replace every ``fastmcp.server.server`` record with fixed, input-free
    metadata and clear ``args``/``exc_info``/``exc_text``.

    Keeps caller-controlled input out of every log sink (M3 no-PII invariant),
    whatever FastMCP's exact log wording. The structured, sanitized failure still
    reaches the caller via the middleware ``invalid_input`` envelope, and the
    ``gencc_link.*`` application logs carry the operational signal.
    """

    _FIXED = "fastmcp tool-call error (detail suppressed to keep caller input out of logs)"

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = self._FIXED
        record.args = ()
        record.exc_info = None
        record.exc_text = None
        return True


def _install_fastmcp_log_scrubber() -> None:
    """Attach the scrubber to the ``fastmcp.server.server`` logger (idempotent)."""
    logger = logging.getLogger(_FASTMCP_SERVER_LOGGER)
    if not any(isinstance(f, _FastMCPLogScrubber) for f in logger.filters):
        logger.addFilter(_FastMCPLogScrubber())


def configure_stdlib_logging() -> None:
    """Configure root stdlib logging to emit on stderr."""
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, settings.log_level))
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
    handler.setLevel(getattr(logging, settings.log_level))
    root_logger.addHandler(handler)

    is_debug = settings.log_level == "DEBUG"
    for name, level in {
        "httpx": "WARNING",
        "httpcore": "WARNING",
        "uvicorn.access": "INFO" if is_debug else "WARNING",
        "uvicorn.error": "INFO",
        "fastmcp": "INFO" if is_debug else "WARNING",
        "mcp": "INFO" if is_debug else "WARNING",
    }.items():
        logging.getLogger(name).setLevel(getattr(logging, level))

    # Keep caller-controlled argument-validation detail out of FastMCP's own logs.
    _install_fastmcp_log_scrubber()


def configure_structlog() -> None:
    """Configure structlog processors and renderer."""
    shared_processors: list[Any] = [
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        _add_static_fields,
    ]
    if settings.log_format == "json":
        processors = [*shared_processors, structlog.processors.JSONRenderer()]
    else:
        colors = settings.log_level == "DEBUG"
        processors = [*shared_processors, structlog.dev.ConsoleRenderer(colors=colors)]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def configure_logging() -> FilteringBoundLogger:
    """Configure stdlib + structlog logging and return a bound logger."""
    configure_stdlib_logging()
    configure_structlog()
    return structlog.get_logger("gencc_link")  # type: ignore[no-any-return]
