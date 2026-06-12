"""Typed exceptions for GenCC-Link.

The MCP envelope (`gencc_link.mcp.envelope`) maps these onto stable error codes,
so the hierarchy here mirrors the error taxonomy advertised in capabilities.
"""

from __future__ import annotations


class GenCCError(Exception):
    """Base exception for all GenCC-Link errors."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message

    def __str__(self) -> str:
        return self.message


class InvalidInputError(GenCCError):
    """Raised when caller input fails validation."""

    def __init__(self, message: str, field: str | None = None) -> None:
        super().__init__(message)
        self.field = field


class NotFoundError(GenCCError):
    """Raised when a requested gene, disease, or assertion does not exist."""


class AmbiguousQueryError(GenCCError):
    """Raised when a free-text query resolves to multiple candidates."""

    def __init__(self, message: str, candidates: list[str] | None = None) -> None:
        super().__init__(message)
        self.candidates = candidates or []


class DataUnavailableError(GenCCError):
    """Raised when the local GenCC database is missing or not yet built."""


class DownloadError(GenCCError):
    """Raised when the GenCC export cannot be fetched from the upstream site."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class QuotaExceededError(DownloadError):
    """Raised when the GenCC per-IP daily download quota is exhausted."""


class ConfigurationError(GenCCError):
    """Raised for invalid server configuration."""
