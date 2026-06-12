"""Live integration test against the real GenCC endpoint (quota-exempt HEAD)."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from gencc_link.config import GenCCDataConfigModel
from gencc_link.exceptions import DownloadError
from gencc_link.ingest.downloader import head

pytestmark = pytest.mark.integration


def test_live_head_returns_etag() -> None:
    """A single quota-exempt HEAD against thegencc.org should report an etag."""
    cfg = GenCCDataConfigModel(
        data_dir=Path(tempfile.mkdtemp(prefix="gencc-live-")),
        db_filename="x.sqlite",
    )
    try:
        result = head(cfg)
    except (DownloadError, OSError) as exc:  # network unavailable in CI
        pytest.skip(f"Live GenCC endpoint unreachable: {exc}")
    # ETag or Last-Modified should be present for a cacheable static export.
    assert result["etag"] is not None or result["last_modified"] is not None
