"""Tests for the conditional GenCC downloader (gencc_link.ingest.downloader)."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import httpx
import pytest
import respx

from gencc_link.config import GenCCDataConfigModel
from gencc_link.constants import DOWNLOAD_URLS
from gencc_link.exceptions import DownloadError, QuotaExceededError
from gencc_link.ingest.downloader import (
    CACHE_FILENAME,
    EXPORT_FILENAME,
    DownloadResult,
    download_export,
    head,
)

EXPORT_URL = DOWNLOAD_URLS["new"]["tsv"]
TSV_BODY = "sgc_id\tgene_symbol\nSGC-1\tSKI\n"


def _config() -> GenCCDataConfigModel:
    return GenCCDataConfigModel(
        data_dir=Path(tempfile.mkdtemp(prefix="gencc-dl-")),
        db_filename="x.sqlite",
    )


class TestDownloadExport:
    @respx.mock
    def test_200_writes_file_and_returns_result(self) -> None:
        cfg = _config()
        respx.get(EXPORT_URL).mock(
            return_value=httpx.Response(
                200,
                text=TSV_BODY,
                headers={
                    "ETag": '"abc123"',
                    "Last-Modified": "Wed, 01 Jan 2025 00:00:00 GMT",
                    "Content-Length": str(len(TSV_BODY)),
                },
            )
        )
        result = download_export(cfg)
        assert isinstance(result, DownloadResult)
        assert result.not_modified is False
        assert result.etag == '"abc123"'
        assert result.last_modified == "Wed, 01 Jan 2025 00:00:00 GMT"
        assert result.path is not None
        assert result.path.exists()
        assert (cfg.data_dir / EXPORT_FILENAME).read_text() == TSV_BODY
        # Cache file written with the validators.
        cache = json.loads((cfg.data_dir / CACHE_FILENAME).read_text())
        assert cache[EXPORT_URL]["etag"] == '"abc123"'

    @respx.mock
    def test_304_not_modified(self) -> None:
        cfg = _config()
        # Seed cache so conditional headers are sent.
        (cfg.data_dir).mkdir(parents=True, exist_ok=True)
        (cfg.data_dir / CACHE_FILENAME).write_text(
            json.dumps({EXPORT_URL: {"etag": '"seed"', "last_modified": "LM"}})
        )
        respx.get(EXPORT_URL).mock(return_value=httpx.Response(304))
        result = download_export(cfg)
        assert result.not_modified is True
        assert result.etag == '"seed"'

    @respx.mock
    def test_429_raises_quota(self) -> None:
        cfg = _config()
        respx.get(EXPORT_URL).mock(return_value=httpx.Response(429))
        with pytest.raises(QuotaExceededError):
            download_export(cfg)

    @respx.mock
    def test_500_raises_download_error(self) -> None:
        cfg = _config()
        respx.get(EXPORT_URL).mock(return_value=httpx.Response(500))
        with pytest.raises(DownloadError):
            download_export(cfg)

    @respx.mock
    def test_transport_error_raises_download_error(self) -> None:
        cfg = _config()
        respx.get(EXPORT_URL).mock(side_effect=httpx.ConnectError("boom"))
        with pytest.raises(DownloadError):
            download_export(cfg)

    @respx.mock
    def test_force_skips_conditional_headers(self) -> None:
        cfg = _config()
        (cfg.data_dir).mkdir(parents=True, exist_ok=True)
        (cfg.data_dir / CACHE_FILENAME).write_text(
            json.dumps({EXPORT_URL: {"etag": '"seed"', "last_modified": "LM"}})
        )
        route = respx.get(EXPORT_URL).mock(
            return_value=httpx.Response(200, text=TSV_BODY, headers={"ETag": '"new"'})
        )
        result = download_export(cfg, force=True)
        assert result.etag == '"new"'
        sent = route.calls.last.request
        assert "If-None-Match" not in sent.headers


class TestHead:
    @respx.mock
    def test_head_returns_headers(self) -> None:
        cfg = _config()
        respx.head(EXPORT_URL).mock(
            return_value=httpx.Response(
                200,
                headers={
                    "ETag": '"head-etag"',
                    "Last-Modified": "Wed, 01 Jan 2025 00:00:00 GMT",
                    "Content-Length": "12345",
                },
            )
        )
        out = head(cfg)
        assert out["etag"] == '"head-etag"'
        assert out["last_modified"] == "Wed, 01 Jan 2025 00:00:00 GMT"
        assert out["content_length"] == "12345"

    @respx.mock
    def test_head_http_error_raises(self) -> None:
        cfg = _config()
        respx.head(EXPORT_URL).mock(return_value=httpx.Response(503))
        with pytest.raises(DownloadError):
            head(cfg)

    @respx.mock
    def test_head_transport_error_raises(self) -> None:
        cfg = _config()
        respx.head(EXPORT_URL).mock(side_effect=httpx.ConnectError("down"))
        with pytest.raises(DownloadError):
            head(cfg)


class TestQuotaCounter:
    def test_status_zero_when_no_cache(self) -> None:
        from gencc_link.ingest.downloader import download_quota_status

        cfg = _config()
        st = download_quota_status(cfg)
        assert st["used_today"] == 0
        assert st["daily_quota"] == 20
        assert st["remaining"] == 20

    @respx.mock
    def test_increment_on_real_download(self) -> None:
        from gencc_link.ingest.downloader import download_export, download_quota_status

        cfg = _config()
        respx.get(EXPORT_URL).mock(
            return_value=httpx.Response(200, text=TSV_BODY, headers={"ETag": '"a"'})
        )
        download_export(cfg)
        st = download_quota_status(cfg)
        assert st["used_today"] == 1
        assert st["remaining"] == 19

    @respx.mock
    def test_two_downloads_increment_twice(self) -> None:
        from gencc_link.ingest.downloader import download_export, download_quota_status

        cfg = _config()
        respx.get(EXPORT_URL).mock(
            return_value=httpx.Response(200, text=TSV_BODY, headers={"ETag": '"a"'})
        )
        download_export(cfg, force=True)
        download_export(cfg, force=True)
        assert download_quota_status(cfg)["used_today"] == 2

    @respx.mock
    def test_304_does_not_increment(self) -> None:
        from gencc_link.ingest.downloader import download_export, download_quota_status

        cfg = _config()
        cfg.data_dir.mkdir(parents=True, exist_ok=True)
        (cfg.data_dir / CACHE_FILENAME).write_text(
            json.dumps({EXPORT_URL: {"etag": '"seed"', "last_modified": "LM"}})
        )
        respx.get(EXPORT_URL).mock(return_value=httpx.Response(304))
        download_export(cfg)
        assert download_quota_status(cfg)["used_today"] == 0

    @respx.mock
    def test_counter_preserves_validators(self) -> None:
        from gencc_link.ingest.downloader import download_export

        cfg = _config()
        respx.get(EXPORT_URL).mock(
            return_value=httpx.Response(200, text=TSV_BODY, headers={"ETag": '"keep"'})
        )
        download_export(cfg)
        cache = json.loads((cfg.data_dir / CACHE_FILENAME).read_text())
        assert cache[EXPORT_URL]["etag"] == '"keep"'
        assert cache["downloads"]["count"] == 1
