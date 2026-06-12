"""Tests for the ingest parser and builder (gencc_link.ingest)."""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest

import gencc_link.ingest.builder as builder_mod
from gencc_link.config import GenCCDataConfigModel
from gencc_link.constants import SUBMISSION_COLUMNS
from gencc_link.exceptions import DataUnavailableError, DownloadError
from gencc_link.ingest.builder import (
    _read_meta,
    build_database,
    ensure_database,
    rebuild,
)
from gencc_link.ingest.downloader import DownloadResult
from gencc_link.ingest.parser import iter_submissions, validate_header

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
SAMPLE_TSV = FIXTURES_DIR / "sample.tsv"


class TestValidateHeader:
    def test_valid_header_passes(self) -> None:
        validate_header(list(SUBMISSION_COLUMNS))

    def test_bad_header_raises(self) -> None:
        with pytest.raises(DownloadError):
            validate_header(["sgc_id", "wrong"])

    def test_reordered_header_raises(self) -> None:
        cols = list(SUBMISSION_COLUMNS)
        cols[0], cols[1] = cols[1], cols[0]
        with pytest.raises(DownloadError):
            validate_header(cols)


class TestIterSubmissions:
    def test_yields_31_dicts(self) -> None:
        records = list(iter_submissions(SAMPLE_TSV))
        assert len(records) == 31
        assert all(set(r.keys()) == set(SUBMISSION_COLUMNS) for r in records)

    def test_empty_to_none(self) -> None:
        records = list(iter_submissions(SAMPLE_TSV))
        # Second SKI row (ClinGen) has blank submitted_as fields -> None.
        clingen = next(r for r in records if r["sgc_id"] == "SGC-100002")
        assert clingen["submitted_as_hgnc_id"] is None
        assert clingen["submitted_as_notes"] is None

    def test_empty_file_raises(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".tsv", delete=False) as fh:
            empty_path = Path(fh.name)
        try:
            with pytest.raises(DownloadError):
                list(iter_submissions(empty_path))
        finally:
            empty_path.unlink(missing_ok=True)

    def test_short_and_long_rows_normalized(self) -> None:
        header = "\t".join(SUBMISSION_COLUMNS)
        # A short row (only first 3 columns) and a long row (extra columns).
        short = "SGC-X\t1\tHGNC:1"
        extra = "\t".join(["v"] * (len(SUBMISSION_COLUMNS) + 3))
        with tempfile.NamedTemporaryFile("w", suffix=".tsv", delete=False, newline="") as fh:
            fh.write(header + "\n" + short + "\n" + extra + "\n")
            path = Path(fh.name)
        try:
            records = list(iter_submissions(path))
            assert len(records) == 2
            # Short row padded with None for missing trailing fields.
            assert records[0]["submitted_run_date"] is None
            # Long row truncated to the schema width.
            assert set(records[1].keys()) == set(SUBMISSION_COLUMNS)
        finally:
            path.unlink(missing_ok=True)


class TestBuildDatabase:
    def test_meta_counts(self) -> None:
        cfg = GenCCDataConfigModel(
            data_dir=Path(tempfile.mkdtemp(prefix="gencc-build-")),
            db_filename="b.sqlite",
        )
        meta = build_database(cfg, tsv_path=SAMPLE_TSV, etag="E", last_modified="LM")
        assert meta.row_count == 31
        assert meta.gene_count == 21
        assert meta.disease_count == 23
        assert meta.submitter_count == 3
        assert meta.source_etag == "E"
        assert meta.source_last_modified == "LM"
        assert cfg.db_path.exists()

    def test_conflict_row_in_gene_disease(self) -> None:
        cfg = GenCCDataConfigModel(
            data_dir=Path(tempfile.mkdtemp(prefix="gencc-build-")),
            db_filename="b.sqlite",
        )
        build_database(cfg, tsv_path=SAMPLE_TSV, etag=None, last_modified=None)
        conn = sqlite3.connect(f"file:{cfg.db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT gene_symbol, disease_curie, consensus_classification, "
                "min_classification FROM gene_disease WHERE has_conflict = 1 "
                "ORDER BY gene_symbol"
            ).fetchall()
            symbols = [r["gene_symbol"] for r in rows]
            assert "GLA" in symbols
            assert "LMNA" in symbols
            gla = next(r for r in rows if r["gene_symbol"] == "GLA")
            assert gla["consensus_classification"] == "Definitive"
            assert gla["min_classification"] == "Refuted Evidence"
        finally:
            conn.close()

    def test_rebuild_replaces_tmp(self) -> None:
        # Build twice into the same dir to exercise the tmp-file unlink branch.
        cfg = GenCCDataConfigModel(
            data_dir=Path(tempfile.mkdtemp(prefix="gencc-build-")),
            db_filename="b.sqlite",
        )
        build_database(cfg, tsv_path=SAMPLE_TSV, etag=None, last_modified=None)
        # Pre-create a stale tmp file so the unlink path runs.
        tmp_path = cfg.db_path.with_suffix(".sqlite.tmp")
        tmp_path.write_text("stale")
        meta = build_database(cfg, tsv_path=SAMPLE_TSV, etag=None, last_modified=None)
        assert meta.row_count == 31
        assert not tmp_path.exists()


def _config() -> GenCCDataConfigModel:
    return GenCCDataConfigModel(
        data_dir=Path(tempfile.mkdtemp(prefix="gencc-builder-")),
        db_filename="b.sqlite",
    )


class TestReadMeta:
    def test_read_meta(self) -> None:
        cfg = _config()
        build_database(cfg, tsv_path=SAMPLE_TSV, etag="E", last_modified="LM")
        meta = _read_meta(cfg.db_path)
        assert meta.row_count == 31
        assert meta.source_etag == "E"

    def test_read_meta_no_row_raises(self) -> None:
        cfg = _config()
        cfg.data_dir.mkdir(parents=True, exist_ok=True)
        # Empty database with no meta table/row.
        conn = sqlite3.connect(cfg.db_path)
        conn.execute("CREATE TABLE meta (id INTEGER)")
        conn.commit()
        conn.close()
        with pytest.raises(DataUnavailableError):
            _read_meta(cfg.db_path)


class TestEnsureDatabase:
    def test_existing_returns_path(self) -> None:
        cfg = _config()
        build_database(cfg, tsv_path=SAMPLE_TSV, etag=None, last_modified=None)
        assert ensure_database(cfg) == cfg.db_path

    def test_missing_no_bootstrap_raises(self) -> None:
        cfg = GenCCDataConfigModel(
            data_dir=Path(tempfile.mkdtemp(prefix="gencc-nb-")),
            db_filename="b.sqlite",
            auto_bootstrap=False,
        )
        with pytest.raises(DataUnavailableError):
            ensure_database(cfg)

    def test_bootstrap_builds(self, monkeypatch) -> None:
        cfg = _config()
        cfg.data_dir.mkdir(parents=True, exist_ok=True)
        export_path = cfg.data_dir / "export.tsv"
        export_path.write_text(SAMPLE_TSV.read_text())

        def fake_download(config, *, force=False):
            return DownloadResult(path=export_path, etag="E", last_modified="LM")

        monkeypatch.setattr(builder_mod, "download_export", fake_download)
        path = ensure_database(cfg)
        assert path == cfg.db_path
        assert cfg.db_path.exists()


class TestRebuild:
    def test_rebuild_builds(self, monkeypatch) -> None:
        cfg = _config()
        cfg.data_dir.mkdir(parents=True, exist_ok=True)
        export_path = cfg.data_dir / "export.tsv"
        export_path.write_text(SAMPLE_TSV.read_text())

        def fake_download(config, *, force=False):
            return DownloadResult(path=export_path, etag="E", last_modified="LM")

        monkeypatch.setattr(builder_mod, "download_export", fake_download)
        meta = rebuild(cfg, force=True)
        assert meta.row_count == 31

    def test_rebuild_not_modified_returns_existing(self, monkeypatch) -> None:
        cfg = _config()
        build_database(cfg, tsv_path=SAMPLE_TSV, etag="E0", last_modified="LM0")

        def fake_download(config, *, force=False):
            return DownloadResult(path=None, not_modified=True)

        monkeypatch.setattr(builder_mod, "download_export", fake_download)
        meta = rebuild(cfg, force=False)
        # Unchanged -> existing provenance reused.
        assert meta.source_etag == "E0"

    def test_build_from_result_no_path_raises(self, monkeypatch) -> None:
        cfg = _config()

        def fake_download(config, *, force=False):
            return DownloadResult(path=None, not_modified=False)

        monkeypatch.setattr(builder_mod, "download_export", fake_download)
        with pytest.raises(DataUnavailableError):
            rebuild(cfg, force=True)
