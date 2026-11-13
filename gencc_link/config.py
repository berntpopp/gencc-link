"""Configuration management for GenCC-Link.

Settings load from environment variables prefixed ``GENCC_LINK_`` (nested config
via ``__``, e.g. ``GENCC_LINK_DATA__DB_PATH``) and an optional ``.env`` file.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from gencc_link import __version__

# Project root: <repo>/gencc_link/config.py -> <repo>
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_DATA_DIR = _PROJECT_ROOT / "data"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_MUTABLE_TAGS = frozenset({"latest", "main", "master", "head", "stable", "current"})

# The one reviewed data release the init sidecar restores (a published
# `data-gencc-*` release of this repository). Change it only in a reviewed PR,
# together with container-release.json (tests/test_data_release_identity.py).
DATA_RELEASE_TAG = "data-gencc-d6a5392d2700f14d"
DATA_COMPRESSED_SHA256 = "d0c5276469fc51cdcc4cdf18edf554d989c8e27b1cef624a85f22522b1a282eb"
DATA_EXPANDED_SHA256 = "d6a5392d2700f14d51f00d451d6d24db7d7e10859b721aa12a96ccc55198dfcd"


class ImmutableDataRequirement(BaseModel):
    """The exact published GenCC data release that the init sidecar may materialize."""

    model_config = ConfigDict(frozen=True)

    reference_root: Path = Path("/data")
    release_tag: str = DATA_RELEASE_TAG
    bundle_url: AnyHttpUrl = AnyHttpUrl(
        "https://github.com/berntpopp/gencc-link/releases/download/"
        f"{DATA_RELEASE_TAG}/gencc.sqlite.gz"
    )
    compressed_sha256: str = DATA_COMPRESSED_SHA256
    expanded_sha256: str = DATA_EXPANDED_SHA256
    max_compressed_bytes: int = Field(default=128 * 1024 * 1024, gt=0)
    max_expanded_bytes: int = Field(default=1024 * 1024 * 1024, gt=0)

    @model_validator(mode="after")
    def _immutable_pin(self) -> ImmutableDataRequirement:
        if not self.release_tag or self.release_tag.lower() in _MUTABLE_TAGS:
            raise ValueError("immutable data release_tag must not be mutable")
        if not (
            _SHA256_RE.fullmatch(self.compressed_sha256)
            and _SHA256_RE.fullmatch(self.expanded_sha256)
        ):
            raise ValueError("immutable data digests must be lowercase SHA-256")
        if self.bundle_url.scheme != "https" or self.bundle_url.host != "github.com":
            raise ValueError("immutable data bundle_url must be an HTTPS GitHub release asset")
        if not (self.bundle_url.path or "").endswith(
            f"/download/{self.release_tag}/gencc.sqlite.gz"
        ):
            raise ValueError("immutable data bundle_url must name the asset under release_tag")
        return self


class GenCCDataConfigModel(BaseModel):
    """GenCC data source + local store configuration."""

    source_format: Literal["new", "legacy"] = Field(
        default="new",
        description="GenCC export format. 'new' (sgc_id keyed) is recommended.",
    )
    data_dir: Path = Field(
        default=_DEFAULT_DATA_DIR,
        description="Directory holding the built SQLite database and download cache.",
    )
    db_filename: str = Field(
        default="gencc.sqlite",
        description="SQLite database filename within data_dir.",
    )
    download_timeout: int = Field(
        default=120,
        ge=5,
        le=900,
        description="HTTP timeout (seconds) for downloading the GenCC export.",
    )
    max_download_bytes: int = Field(
        default=128 * 1024 * 1024,
        ge=1,
        le=4 * 1024**3,
        description=(
            "Maximum export bytes; measured 24,507,669 bytes on 2026-07-10. "
            "Override GENCC_LINK_DATA__MAX_DOWNLOAD_BYTES as the export grows."
        ),
    )
    max_download_seconds: int = Field(
        default=900,
        ge=30,
        le=7200,
        description=(
            "Total export streaming deadline in seconds; override "
            "GENCC_LINK_DATA__MAX_DOWNLOAD_SECONDS for slow links."
        ),
    )
    user_agent: str = Field(
        default=f"GenCC-Link/{__version__} (+https://github.com/berntpopp/gencc-link)",
        description="User-Agent sent to thegencc.org.",
    )
    auto_bootstrap: bool = Field(
        default=True,
        description="Build the database on first use by downloading the export if absent.",
    )
    refresh_enabled: bool = Field(
        default=True,
        description=(
            "Run an in-process scheduler (unified/http transports only) that "
            "conditionally refreshes the database on an interval. Disable when an "
            "external scheduler (cron sidecar, k8s CronJob) owns refresh."
        ),
    )
    refresh_interval_hours: float = Field(
        default=24.0,
        ge=1.0,
        le=720.0,
        description=(
            "Hours between conditional refresh checks. GenCC updates weekly; a "
            "daily check is quota-safe because unchanged exports return 304."
        ),
    )
    refresh_jitter_seconds: int = Field(
        default=300,
        ge=0,
        le=86400,
        description="Random jitter added to each refresh to avoid thundering herds.",
    )
    build_lock_timeout: int = Field(
        default=600,
        ge=1,
        le=3600,
        description="Seconds to wait for the cross-process build lock before giving up.",
    )
    cache_size: int = Field(
        default=512,
        ge=0,
        le=8192,
        description="Max entries in the in-process query cache (0 disables).",
    )
    cache_ttl: int = Field(
        default=3600,
        ge=0,
        le=86400,
        description="Query cache TTL in seconds.",
    )

    @property
    def db_path(self) -> Path:
        """Absolute path to the SQLite database file."""
        return self.data_dir / self.db_filename

    @field_validator("data_dir")
    @classmethod
    def _expand_data_dir(cls, v: Path) -> Path:
        return Path(v).expanduser()


class ServerSettings(BaseSettings):
    """Top-level server configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        case_sensitive=False,
        extra="ignore",
        env_prefix="GENCC_LINK_",
    )

    # Server
    host: str = Field(default="127.0.0.1", description="Server host")
    port: int = Field(default=8000, ge=1024, le=65535, description="Server port")
    reload: bool = Field(default=False, description="Enable auto-reload in development")

    # Transport
    transport: Literal["unified", "http", "stdio"] = Field(
        default="unified", description="Server transport mode"
    )
    mcp_path: str = Field(default="/mcp", description="MCP endpoint path")
    allowed_hosts: list[str] = Field(
        default=["localhost", "127.0.0.1", "::1"],
        description="Host header values accepted by the MCP request guard",
    )
    allowed_origins: list[str] = Field(
        default=[],
        description="Browser Origin values accepted by the MCP request guard",
    )

    # CORS
    cors_origins: list[str] = Field(
        default=["http://localhost:3000", "http://127.0.0.1:3000"],
        description="Allowed CORS origins",
    )
    cors_allow_credentials: bool = Field(
        default=False,
        description="Allow CORS credentials (forced off; backend is unauthenticated, no cookies)",
    )
    cors_allow_methods: list[str] = Field(default=["GET", "POST", "OPTIONS"])
    cors_allow_headers: list[str] = Field(default=["*"])

    # Logging
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(default="INFO")
    log_format: Literal["json", "console"] = Field(default="console")

    # Data
    data: GenCCDataConfigModel = Field(
        default_factory=GenCCDataConfigModel,
        description="GenCC data source + store configuration",
    )
    immutable_data: ImmutableDataRequirement = Field(
        default_factory=ImmutableDataRequirement,
        description="Exact published data release restored only by the init sidecar.",
    )

    @field_validator("mcp_path")
    @classmethod
    def _validate_mcp_path(cls, v: str) -> str:
        return v if v.startswith("/") else f"/{v}"

    @field_validator("allowed_hosts", "allowed_origins", "cors_origins", mode="before")
    @classmethod
    def _parse_string_list(cls, v: Any) -> list[str]:
        if isinstance(v, str):
            return [item.strip() for item in v.split(",") if item.strip()]
        return list(v) if v else []

    @field_validator("allowed_hosts")
    @classmethod
    def _reject_wildcard_host(cls, v: list[str]) -> list[str]:
        if any(any(marker in host for marker in "*?[]") for host in v):
            raise ValueError("wildcard patterns are not allowed in allowed_hosts")
        return v


# Global settings instance
settings = ServerSettings()


def get_data_config() -> GenCCDataConfigModel:
    """Return the GenCC data configuration from global settings."""
    return settings.data
