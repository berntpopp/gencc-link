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
    def test_download_rejects_redirect_without_following(self, tmp_path: Path) -> None:
        cfg = GenCCDataConfigModel(data_dir=tmp_path, max_download_bytes=1024)
        target_url = "https://evil.example/export.tsv"
        target = respx.get(target_url).mock(return_value=httpx.Response(200))
        respx.get(EXPORT_URL).mock(
            return_value=httpx.Response(302, headers={"Location": target_url})
        )

        with pytest.raises(DownloadError, match="302"):
            download_export(cfg)

        assert target.called is False

    @respx.mock
    def test_chunked_overflow_preserves_existing_export(self, tmp_path: Path) -> None:
        cfg = GenCCDataConfigModel(data_dir=tmp_path, max_download_bytes=8)
        destination = tmp_path / EXPORT_FILENAME
        destination.write_text("old", encoding="utf-8")
        respx.get(EXPORT_URL).mock(
            return_value=httpx.Response(
                200,
                headers={"Content-Length": "1"},
                content=b"123456789",
            )
        )

        with pytest.raises(DownloadError, match="exceeded 8 bytes"):
            download_export(cfg)

        assert destination.read_text(encoding="utf-8") == "old"
        assert list(tmp_path.glob("*.download.tmp")) == []
        assert not (tmp_path / CACHE_FILENAME).exists()

    @respx.mock
    def test_content_length_limit_preserves_existing_export(self, tmp_path: Path) -> None:
        cfg = GenCCDataConfigModel(data_dir=tmp_path, max_download_bytes=8)
        destination = tmp_path / EXPORT_FILENAME
        destination.write_text("old", encoding="utf-8")
        respx.get(EXPORT_URL).mock(
            return_value=httpx.Response(200, headers={"Content-Length": "9"})
        )

        with pytest.raises(DownloadError, match="Content-Length 9 exceeds 8 bytes"):
            download_export(cfg)

        assert destination.read_text(encoding="utf-8") == "old"
        assert list(tmp_path.glob("*.download.tmp")) == []

    @respx.mock
    def test_total_download_deadline_preserves_existing_export(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import gencc_link.ingest.downloader as downloader

        cfg = GenCCDataConfigModel(
            data_dir=tmp_path,
            max_download_bytes=1024,
            max_download_seconds=30,
        )
        destination = tmp_path / EXPORT_FILENAME
        destination.write_text("old", encoding="utf-8")
        respx.get(EXPORT_URL).mock(return_value=httpx.Response(200, content=b"new"))
        ticks = iter([0.0, 31.0])
        monkeypatch.setattr(downloader.time, "monotonic", lambda: next(ticks))

        with pytest.raises(DownloadError, match="exceeded 30 seconds"):
            download_export(cfg)

        assert destination.read_text(encoding="utf-8") == "old"
        assert list(tmp_path.glob("*.download.tmp")) == []

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
    def test_head_rejects_redirect_without_following(self) -> None:
        cfg = _config()
        target_url = "https://evil.example/export.tsv"
        target = respx.head(target_url).mock(return_value=httpx.Response(200))
        respx.head(EXPORT_URL).mock(
            return_value=httpx.Response(302, headers={"Location": target_url})
        )

        with pytest.raises(DownloadError, match="302"):
            head(cfg)

        assert target.called is False

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
