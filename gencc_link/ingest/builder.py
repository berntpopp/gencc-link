"""Atomic SQLite database builder for the GenCC submissions export.

The build streams the TSV into a temporary database, computes the aggregated
``gene_disease`` table and derived catalogs, writes provenance into ``meta``,
and then atomically swaps the finished file into place. Callers get back a typed
:class:`~gencc_link.models.records.BuildMeta`.
"""

from __future__ import annotations

import os
import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from gencc_link.constants import SCHEMA_VERSION, SUBMISSION_COLUMNS, classification_rank
from gencc_link.data import load_schema_sql
from gencc_link.exceptions import DataUnavailableError
from gencc_link.ingest.aggregates import (
    build_diseases,
    build_fts,
    build_gene_disease,
    build_genes,
    build_submitters,
)
from gencc_link.ingest.downloader import DownloadResult, download_export
from gencc_link.ingest.parser import iter_submissions
from gencc_link.models.records import BuildMeta

if TYPE_CHECKING:
    from gencc_link.config import GenCCDataConfigModel

#: Insert column order for the ``submissions`` table (31 export columns + rank).
_SUBMISSION_INSERT_COLUMNS = (*SUBMISSION_COLUMNS, "classification_rank")

#: Rows buffered before each ``executemany`` flush during the load.
_INSERT_BATCH = 1000


def build_database(
    config: GenCCDataConfigModel,
    *,
    tsv_path: Path,
    etag: str | None,
    last_modified: str | None,
) -> BuildMeta:
    """Build the GenCC SQLite database from a TSV export, atomically.

    Args:
        config: Active GenCC data configuration.
        tsv_path: Path to the parsed GenCC TSV export.
        etag: ``ETag`` of the source export (provenance), if known.
        last_modified: ``Last-Modified`` of the source export, if known.

    Returns:
        Typed provenance for the freshly built database.
    """
    start = time.perf_counter()
    config.data_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = config.db_path.with_suffix(".sqlite.tmp")
    if tmp_path.exists():
        tmp_path.unlink()

    conn = sqlite3.connect(tmp_path)
    try:
        conn.executescript(load_schema_sql())
        row_count, max_run_date = _load_submissions(conn, tsv_path)
        build_gene_disease(conn)
        gene_count = build_genes(conn)
        disease_count = build_diseases(conn)
        submitter_count = build_submitters(conn)
        build_fts(conn)

        duration = round(time.perf_counter() - start, 3)
        gencc_run_date = max_run_date or last_modified
        meta_values = {
            "schema_version": SCHEMA_VERSION,
            "source_format": config.source_format,
            "source_url": _source_url(config),
            "source_etag": etag,
            "source_last_modified": last_modified,
            "gencc_run_date": gencc_run_date,
            "row_count": row_count,
            "gene_count": gene_count,
            "disease_count": disease_count,
            "submitter_count": submitter_count,
            "build_utc": datetime.now(tz=UTC).isoformat(),
            "build_duration_s": duration,
        }
        _insert_meta(conn, meta_values)
        conn.commit()
    finally:
        conn.close()

    os.replace(tmp_path, config.db_path)
    return BuildMeta.model_validate(meta_values)


def _load_submissions(
    conn: sqlite3.Connection,
    tsv_path: Path,
) -> tuple[int, str | None]:
    """Insert all submissions; return ``(row_count, max_submitted_run_date)``."""
    insert_sql = (
        "INSERT OR REPLACE INTO submissions ("
        + ", ".join(_SUBMISSION_INSERT_COLUMNS)
        + ") VALUES ("
        + ", ".join("?" for _ in _SUBMISSION_INSERT_COLUMNS)
        + ")"
    )
    batch: list[tuple[Any, ...]] = []
    row_count = 0
    max_run_date: str | None = None

    for record in iter_submissions(tsv_path):
        run_date = record.get("submitted_run_date")
        if run_date and (max_run_date is None or run_date > max_run_date):
            max_run_date = run_date
        batch.append(_submission_tuple(record))
        row_count += 1
        if len(batch) >= _INSERT_BATCH:
            conn.executemany(insert_sql, batch)
            batch = []

    if batch:
        conn.executemany(insert_sql, batch)
    return row_count, max_run_date


def _submission_tuple(record: dict[str, str | None]) -> tuple[Any, ...]:
    """Build a ``submissions`` insert tuple from a parsed TSV record."""
    values: list[Any] = [record.get(column) for column in SUBMISSION_COLUMNS]
    # version_number -> INTEGER (best-effort; None on failure).
    version_idx = SUBMISSION_COLUMNS.index("version_number")
    values[version_idx] = _to_int(record.get("version_number"))
    values.append(classification_rank(record.get("classification_title")))
    return tuple(values)


def _to_int(value: str | None) -> int | None:
    """Best-effort conversion of a string to ``int`` (``None`` on failure)."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _insert_meta(conn: sqlite3.Connection, values: dict[str, Any]) -> None:
    """Insert the single provenance row (``id = 1``)."""
    columns = list(values.keys())
    placeholders = ", ".join("?" for _ in columns)
    conn.execute(
        f"INSERT INTO meta (id, {', '.join(columns)}) VALUES (1, {placeholders})",
        tuple(values[col] for col in columns),
    )


def _source_url(config: GenCCDataConfigModel) -> str:
    """Return the TSV export URL recorded in provenance."""
    from gencc_link.constants import DOWNLOAD_URLS

    return DOWNLOAD_URLS[config.source_format]["tsv"]


def _read_meta(db_path: Path) -> BuildMeta:
    """Read the provenance row from an existing database into a ``BuildMeta``."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM meta WHERE id = 1").fetchone()
    finally:
        conn.close()
    if row is None:
        raise DataUnavailableError("GenCC database has no provenance (meta) row.")
    return BuildMeta(
        schema_version=row["schema_version"],
        source_format=row["source_format"],
        source_url=row["source_url"],
        source_etag=row["source_etag"],
        source_last_modified=row["source_last_modified"],
        gencc_run_date=row["gencc_run_date"],
        row_count=row["row_count"],
        gene_count=row["gene_count"],
        disease_count=row["disease_count"],
        submitter_count=row["submitter_count"],
        build_utc=row["build_utc"],
        build_duration_s=row["build_duration_s"],
    )


def _build_from_result(
    config: GenCCDataConfigModel,
    result: DownloadResult,
) -> BuildMeta:
    """Build the database from a successful download result."""
    if result.path is None:
        raise DataUnavailableError("Download reported no local export file to build from.")
    return build_database(
        config,
        tsv_path=result.path,
        etag=result.etag,
        last_modified=result.last_modified,
    )


def ensure_database(config: GenCCDataConfigModel) -> Path:
    """Return the database path, building it on first use if configured.

    Args:
        config: Active GenCC data configuration.

    Returns:
        Path to the built SQLite database.

    Raises:
        DataUnavailableError: When the database is missing and auto-bootstrap is
            disabled.
    """
    if config.db_path.exists():
        return config.db_path
    if not config.auto_bootstrap:
        raise DataUnavailableError("GenCC database not built. Run `make data`.")
    result = download_export(config)
    _build_from_result(config, result)
    return config.db_path


def rebuild(config: GenCCDataConfigModel, *, force: bool) -> BuildMeta:
    """Download (conditionally) and rebuild the database.

    When the download reports ``not_modified`` and a database already exists, the
    existing provenance is returned without rebuilding.

    Args:
        config: Active GenCC data configuration.
        force: When ``True``, bypass conditional caching and force a download.

    Returns:
        Provenance for the resulting (rebuilt or existing) database.
    """
    result = download_export(config, force=force)
    if result.not_modified and config.db_path.exists():
        return _read_meta(config.db_path)
    return _build_from_result(config, result)
