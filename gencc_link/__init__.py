"""GenCC-Link: MCP/API server for Gene Curation Coalition gene-disease validity data."""

from importlib.metadata import PackageNotFoundError, version

try:
    # Single source of truth: the version declared in pyproject.toml. Keeps
    # __version__ (used by /health and structured logs) in lockstep with the
    # capabilities/diagnostics server_version (also read from package metadata).
    __version__ = version("gencc-link")
except PackageNotFoundError:  # running from a source tree that isn't installed
    __version__ = "0.0.0"

__author__ = "GenCC-Link Development Team"
