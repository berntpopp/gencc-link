"""Tests for the data CLI (gencc_link.ingest.cli)."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from typer.testing import CliRunner

import gencc_link.ingest.cli as cli_mod
from gencc_link.config import GenCCDataConfigModel
from gencc_link.exceptions import DownloadError, QuotaExceededError
from gencc_link.ingest.builder import build_database
from gencc_link.ingest.downloader import DownloadResult

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
SAMPLE_TSV = FIXTURES_DIR / "sample.tsv"

runner = CliRunner()


@pytest.fixture
def temp_config(monkeypatch) -> GenCCDataConfigModel:
    cfg = GenCCDataConfigModel(
        data_dir=Path(tempfile.mkdtemp(prefix="gencc-cli-")),
        db_filename="cli.sqlite",
    )
    monkeypatch.setattr(cli_mod, "get_data_config", lambda: cfg)
    return cfg


class TestInfo:
    def test_info_missing_db(self, temp_config: GenCCDataConfigModel) -> None:
        result = runner.invoke(cli_mod.app, ["info"])
        assert result.exit_code == 1
        assert "No GenCC database" in result.stdout

    def test_info_existing_db(self, temp_config: GenCCDataConfigModel) -> None:
        build_database(temp_config, tsv_path=SAMPLE_TSV, etag="E", last_modified="LM")
        result = runner.invoke(cli_mod.app, ["info"])
        assert result.exit_code == 0
        assert "submissions    : 31" in result.stdout
        assert "source_etag    : E" in result.stdout


class TestBuild:
    def test_build_success(self, temp_config: GenCCDataConfigModel, monkeypatch) -> None:
        # Pre-place a TSV at the export path and mock download to return it.
        export_path = temp_config.data_dir / "export.tsv"
        temp_config.data_dir.mkdir(parents=True, exist_ok=True)
        export_path.write_text(SAMPLE_TSV.read_text())

        def fake_download(config, *, force=False):
            return DownloadResult(
                path=export_path, etag="E", last_modified="LM", not_modified=False
            )

        monkeypatch.setattr(cli_mod, "download_export", fake_download)
        result = runner.invoke(cli_mod.app, ["build"])
        assert result.exit_code == 0
        assert "Built GenCC database:" in result.stdout
        assert temp_config.db_path.exists()

    def test_build_quota_error(self, temp_config: GenCCDataConfigModel, monkeypatch) -> None:
        def fake_download(config, *, force=False):
            raise QuotaExceededError("quota")

        monkeypatch.setattr(cli_mod, "download_export", fake_download)
        result = runner.invoke(cli_mod.app, ["build"])
        assert result.exit_code == 1
        assert "ERROR" in result.stdout

    def test_build_download_error(self, temp_config: GenCCDataConfigModel, monkeypatch) -> None:
        def fake_download(config, *, force=False):
            raise DownloadError("net")

        monkeypatch.setattr(cli_mod, "download_export", fake_download)
        result = runner.invoke(cli_mod.app, ["build"])
        assert result.exit_code == 1
        assert "download failed" in result.stdout

    def test_build_no_path(self, temp_config: GenCCDataConfigModel, monkeypatch) -> None:
        def fake_download(config, *, force=False):
            return DownloadResult(path=None)

        monkeypatch.setattr(cli_mod, "download_export", fake_download)
        result = runner.invoke(cli_mod.app, ["build"])
        assert result.exit_code == 1
        assert "no export file" in result.stdout


class TestRefresh:
    def test_refresh_success(self, temp_config: GenCCDataConfigModel, monkeypatch) -> None:
        meta = build_database(temp_config, tsv_path=SAMPLE_TSV, etag="E", last_modified="LM")

        def fake_rebuild(config, *, force):
            return meta

        monkeypatch.setattr(cli_mod, "rebuild", fake_rebuild)
        result = runner.invoke(cli_mod.app, ["refresh"])
        assert result.exit_code == 0
        assert "refreshed" in result.stdout

    def test_refresh_quota_error(self, temp_config: GenCCDataConfigModel, monkeypatch) -> None:
        def fake_rebuild(config, *, force):
            raise QuotaExceededError("quota")

        monkeypatch.setattr(cli_mod, "rebuild", fake_rebuild)
        result = runner.invoke(cli_mod.app, ["refresh"])
        assert result.exit_code == 1

    def test_refresh_download_error(self, temp_config: GenCCDataConfigModel, monkeypatch) -> None:
        def fake_rebuild(config, *, force):
            raise DownloadError("net")

        monkeypatch.setattr(cli_mod, "rebuild", fake_rebuild)
        result = runner.invoke(cli_mod.app, ["refresh"])
        assert result.exit_code == 1
        assert "download failed" in result.stdout


def test_main_callable() -> None:
    # main() just invokes the typer app; calling with --help exits cleanly.
    result = runner.invoke(cli_mod.app, ["--help"])
    assert result.exit_code == 0
