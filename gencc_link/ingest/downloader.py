"""Conditional, quota-aware download of the GenCC submissions export.

GenCC serves a per-IP daily download quota; ``304 Not Modified`` responses and
``HEAD`` requests are exempt. We therefore cache the last seen ``ETag`` and
``Last-Modified`` for the export URL and issue conditional ``GET`` requests so a
re-download only consumes quota when the upstream data actually changed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import httpx

from gencc_link.constants import DOWNLOAD_URLS
from gencc_link.exceptions import DownloadError, QuotaExceededError

if TYPE_CHECKING:
    from gencc_link.config import GenCCDataConfigModel

#: Local filename of the downloaded TSV export within ``config.data_dir``.
EXPORT_FILENAME = "gencc-submissions.tsv"

#: Local filename of the JSON cache holding the last ``etag``/``last_modified``.
CACHE_FILENAME = "download_cache.json"

#: Bytes streamed per chunk while writing the export to disk.
_CHUNK_SIZE = 1 << 16


@dataclass
class DownloadResult:
    """Outcome of a conditional download attempt.

    Attributes:
        path: Path to the local TSV export, or ``None`` when unavailable.
        etag: Strong/weak ``ETag`` reported by the server, if any.
        last_modified: ``Last-Modified`` header reported by the server, if any.
        not_modified: ``True`` when the server returned ``304 Not Modified``.
        content_length: ``Content-Length`` of the body, if reported.
    """

    path: Path | None = None
    etag: str | None = None
    last_modified: str | None = None
    not_modified: bool = False
    content_length: int | None = None


def _export_url(config: GenCCDataConfigModel) -> str:
    """Return the TSV export URL for the configured source format."""
    return DOWNLOAD_URLS[config.source_format]["tsv"]


def _cache_path(config: GenCCDataConfigModel) -> Path:
    """Return the path to the download cache JSON file."""
    return config.data_dir / CACHE_FILENAME


def _export_path(config: GenCCDataConfigModel) -> Path:
    """Return the path to the local TSV export file."""
    return config.data_dir / EXPORT_FILENAME


def _read_cache(config: GenCCDataConfigModel) -> dict[str, str | None]:
    """Read the cached etag/last_modified for the export URL.

    Returns an empty mapping when no cache exists or it is unreadable. The cache
    is keyed by URL so switching ``source_format`` invalidates stale validators.
    """
    cache_path = _cache_path(config)
    if not cache_path.exists():
        return {}
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    entry = data.get(_export_url(config))
    if not isinstance(entry, dict):
        return {}
    return {
        "etag": entry.get("etag"),
        "last_modified": entry.get("last_modified"),
    }


def _write_cache(
    config: GenCCDataConfigModel,
    *,
    etag: str | None,
    last_modified: str | None,
) -> None:
    """Persist the latest etag/last_modified validators for the export URL."""
    cache_path = _cache_path(config)
    data: dict[str, object] = {}
    if cache_path.exists():
        try:
            loaded = json.loads(cache_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
        except (json.JSONDecodeError, OSError):
            data = {}
    data[_export_url(config)] = {"etag": etag, "last_modified": last_modified}
    cache_path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _headers(config: GenCCDataConfigModel) -> dict[str, str]:
    """Return base request headers (always advertises the configured agent)."""
    return {"User-Agent": config.user_agent}


def _int_or_none(value: str | None) -> int | None:
    """Best-effort parse of a header string into an int."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def head(config: GenCCDataConfigModel) -> dict[str, str | None]:
    """Issue a quota-exempt ``HEAD`` request for the export.

    Args:
        config: Active GenCC data configuration.

    Returns:
        A mapping with ``etag``, ``last_modified``, and ``content_length`` keys.

    Raises:
        DownloadError: On any HTTP error or transport failure.
    """
    url = _export_url(config)
    try:
        with httpx.Client(
            follow_redirects=True,
            timeout=config.download_timeout,
        ) as client:
            response = client.head(url, headers=_headers(config))
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise DownloadError(
            f"HEAD {url} failed: {exc.response.status_code}",
            status_code=exc.response.status_code,
        ) from exc
    except httpx.HTTPError as exc:
        raise DownloadError(f"HEAD {url} failed: {exc}") from exc
    return {
        "etag": response.headers.get("ETag"),
        "last_modified": response.headers.get("Last-Modified"),
        "content_length": response.headers.get("Content-Length"),
    }


def download_export(
    config: GenCCDataConfigModel,
    *,
    force: bool = False,
) -> DownloadResult:
    """Conditionally download the GenCC TSV export.

    Unless ``force`` is set, a conditional ``GET`` is sent using any cached
    ``ETag``/``Last-Modified`` validators. A ``304`` response avoids consuming
    download quota and reuses the existing local export.

    Args:
        config: Active GenCC data configuration.
        force: When ``True``, ignore cached validators and always re-download.

    Returns:
        A :class:`DownloadResult` describing the outcome.

    Raises:
        QuotaExceededError: When the server returns ``429``.
        DownloadError: On any other HTTP error or transport failure.
    """
    config.data_dir.mkdir(parents=True, exist_ok=True)
    url = _export_url(config)
    export_path = _export_path(config)

    request_headers = _headers(config)
    if not force:
        cached = _read_cache(config)
        if cached.get("etag"):
            request_headers["If-None-Match"] = str(cached["etag"])
        if cached.get("last_modified"):
            request_headers["If-Modified-Since"] = str(cached["last_modified"])

    try:
        with (
            httpx.Client(
                follow_redirects=True,
                timeout=config.download_timeout,
            ) as client,
            client.stream("GET", url, headers=request_headers) as response,
        ):
            if response.status_code == httpx.codes.NOT_MODIFIED:
                return DownloadResult(
                    path=export_path if export_path.exists() else None,
                    etag=request_headers.get("If-None-Match"),
                    last_modified=request_headers.get("If-Modified-Since"),
                    not_modified=True,
                )
            if response.status_code == httpx.codes.TOO_MANY_REQUESTS:
                raise QuotaExceededError(
                    "GenCC daily download quota exceeded (HTTP 429).",
                    status_code=response.status_code,
                )
            response.raise_for_status()
            etag = response.headers.get("ETag")
            last_modified = response.headers.get("Last-Modified")
            content_length = _int_or_none(response.headers.get("Content-Length"))
            _stream_to_file(response, export_path)
    except (QuotaExceededError, DownloadError):
        raise
    except httpx.HTTPStatusError as exc:
        raise DownloadError(
            f"GET {url} failed: {exc.response.status_code}",
            status_code=exc.response.status_code,
        ) from exc
    except httpx.HTTPError as exc:
        raise DownloadError(f"GET {url} failed: {exc}") from exc

    _write_cache(config, etag=etag, last_modified=last_modified)
    return DownloadResult(
        path=export_path,
        etag=etag,
        last_modified=last_modified,
        not_modified=False,
        content_length=content_length,
    )


def _stream_to_file(response: httpx.Response, path: Path) -> None:
    """Stream a response body to ``path`` in binary chunks."""
    with path.open("wb") as handle:
        for chunk in response.iter_bytes(_CHUNK_SIZE):
            handle.write(chunk)
