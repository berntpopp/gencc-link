"""Reproducible data-release build + packaging (router #63 option A)."""

from __future__ import annotations

import gzip
import hashlib
import json
import sqlite3
from pathlib import Path

from gencc_link.config import GenCCDataConfigModel
from gencc_link.ingest.builder import build_database
from gencc_link.ingest.release import package_release

SAMPLE_TSV = Path(__file__).resolve().parent / "fixtures" / "sample.tsv"
ROOT = Path(__file__).resolve().parents[1]


def _build(tmp: Path) -> Path:
    cfg = GenCCDataConfigModel(data_dir=tmp, db_filename="gencc.sqlite")
    build_database(
        cfg,
        tsv_path=SAMPLE_TSV,
        etag='"e"',
        last_modified="Sun, 13 Sep 2026 06:01:23 GMT",
        build_utc="2026-09-13T06:01:23+00:00",
    )
    return cfg.db_path


def test_pinned_build_is_byte_reproducible_and_not_wal(tmp_path: Path) -> None:
    first = _build(tmp_path / "a")
    second = _build(tmp_path / "b")

    assert first.read_bytes() == second.read_bytes()
    connection = sqlite3.connect(f"file:{first}?mode=ro", uri=True)
    try:
        assert connection.execute("PRAGMA journal_mode").fetchone() == ("delete",)
        assert connection.execute("SELECT build_utc, build_duration_s FROM meta").fetchone() == (
            "2026-09-13T06:01:23+00:00",
            None,
        )
    finally:
        connection.close()


def test_package_writes_verifiable_content_addressed_assets(tmp_path: Path) -> None:
    database = _build(tmp_path / "build")
    output = tmp_path / "release"

    manifest = package_release(
        database,
        source_tsv=SAMPLE_TSV,
        authorization=ROOT / "release" / "data-authorization.json",
        output=output,
        revision="0" * 40,
    )

    expanded = hashlib.sha256(database.read_bytes()).hexdigest()
    assert manifest["release_tag"] == f"data-gencc-{expanded[:16]}"
    assert sorted(p.name for p in output.iterdir()) == [
        "SHA256SUMS",
        "data-authorization.json",
        "gencc.sqlite.gz",
        "manifest.json",
    ]
    bundle = output / "gencc.sqlite.gz"
    assert gzip.decompress(bundle.read_bytes()) == database.read_bytes()
    assert manifest["compressed_sha256"] == hashlib.sha256(bundle.read_bytes()).hexdigest()
    assert manifest["expanded_sha256"] == expanded
    assert manifest["source"]["sha256"] == hashlib.sha256(SAMPLE_TSV.read_bytes()).hexdigest()
    assert manifest["source"]["last_modified"] == "Sun, 13 Sep 2026 06:01:23 GMT"
    assert manifest["transformation"]["revision"] == "0" * 40
    assert manifest["license"]["spdx"] == "CC0-1.0"
    assert json.loads((output / "manifest.json").read_text()) == manifest
    sums = (output / "SHA256SUMS").read_text().splitlines()
    assert len(sums) == 3
    for line in sums:
        digest, name = line.split("  ")
        assert hashlib.sha256((output / name).read_bytes()).hexdigest() == digest
    # Packaging the same bytes again yields the same compressed identity.
    again = package_release(
        database,
        source_tsv=SAMPLE_TSV,
        authorization=ROOT / "release" / "data-authorization.json",
        output=tmp_path / "release2",
        revision="0" * 40,
    )
    assert again["compressed_sha256"] == manifest["compressed_sha256"]


def test_cli_reproducible_build_then_package(tmp_path: Path, monkeypatch) -> None:
    from typer.testing import CliRunner

    import gencc_link.ingest.cli as cli_mod
    from gencc_link.ingest.downloader import DownloadResult

    cfg = GenCCDataConfigModel(data_dir=tmp_path / "data", db_filename="gencc.sqlite")
    cfg.data_dir.mkdir()
    export = cfg.data_dir / "gencc-submissions.tsv"
    export.write_bytes(SAMPLE_TSV.read_bytes())
    monkeypatch.setattr(cli_mod, "get_data_config", lambda: cfg)
    monkeypatch.setattr(
        cli_mod,
        "download_export",
        lambda config, *, force=False: DownloadResult(
            path=export, etag="E", last_modified="Sun, 13 Sep 2026 06:01:23 GMT", not_modified=False
        ),
    )
    runner = CliRunner()

    assert runner.invoke(cli_mod.app, ["build", "--reproducible"]).exit_code == 0
    result = runner.invoke(
        cli_mod.app, ["package", "--output", str(tmp_path / "out"), "--revision", "a" * 40]
    )

    assert result.exit_code == 0, result.stdout
    manifest = json.loads(result.stdout)
    assert manifest["transformation"]["build_utc"] == "2026-09-13T06:01:23+00:00"
    assert manifest["source"]["sha256"] == hashlib.sha256(SAMPLE_TSV.read_bytes()).hexdigest()


def test_cli_reproducible_build_requires_last_modified(tmp_path: Path, monkeypatch) -> None:
    from typer.testing import CliRunner

    import gencc_link.ingest.cli as cli_mod
    from gencc_link.ingest.downloader import DownloadResult

    cfg = GenCCDataConfigModel(data_dir=tmp_path, db_filename="gencc.sqlite")
    monkeypatch.setattr(cli_mod, "get_data_config", lambda: cfg)
    monkeypatch.setattr(
        cli_mod,
        "download_export",
        lambda config, *, force=False: DownloadResult(
            path=SAMPLE_TSV, etag=None, last_modified=None, not_modified=False
        ),
    )

    result = CliRunner().invoke(cli_mod.app, ["build", "--reproducible"])

    assert result.exit_code == 1
    assert not cfg.db_path.exists()
