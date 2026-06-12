"""Command-line interface for building and refreshing the GenCC database.

Exposed as the ``gencc-link-data`` console script. Provides ``build`` (force a
download + rebuild), ``refresh`` (conditional rebuild), and ``info`` (print
provenance of the existing database).
"""

from __future__ import annotations

import sqlite3

import typer

from gencc_link.config import get_data_config
from gencc_link.exceptions import DownloadError, QuotaExceededError
from gencc_link.ingest.builder import build_database, rebuild
from gencc_link.ingest.downloader import download_export
from gencc_link.models.records import BuildMeta

app = typer.Typer(
    add_completion=False,
    help="Build and refresh the local GenCC SQLite database.",
)


def _print_summary(meta: BuildMeta, *, header: str) -> None:
    """Print a compact provenance summary for a build."""
    print(header)
    print(f"  schema_version : {meta.schema_version}")
    print(f"  source_format  : {meta.source_format}")
    print(f"  source_url     : {meta.source_url}")
    print(f"  gencc_run_date : {meta.gencc_run_date}")
    print(f"  submissions    : {meta.row_count}")
    print(f"  genes          : {meta.gene_count}")
    print(f"  diseases       : {meta.disease_count}")
    print(f"  submitters     : {meta.submitter_count}")
    print(f"  built_utc      : {meta.build_utc}")
    if meta.build_duration_s is not None:
        print(f"  build_seconds  : {meta.build_duration_s}")


@app.command()
def build() -> None:
    """Force a download and full rebuild of the database."""
    config = get_data_config()
    try:
        result = download_export(config, force=True)
    except QuotaExceededError as exc:
        print(f"ERROR: {exc}")
        raise typer.Exit(code=1) from exc
    except DownloadError as exc:
        print(f"ERROR: download failed: {exc}")
        raise typer.Exit(code=1) from exc
    if result.path is None:
        print("ERROR: download produced no export file.")
        raise typer.Exit(code=1)
    meta = build_database(
        config,
        tsv_path=result.path,
        etag=result.etag,
        last_modified=result.last_modified,
    )
    _print_summary(meta, header="Built GenCC database:")


@app.command()
def refresh() -> None:
    """Conditionally refresh the database; rebuild only if the export changed."""
    config = get_data_config()
    existed = config.db_path.exists()
    try:
        meta = rebuild(config, force=False)
    except QuotaExceededError as exc:
        print(f"ERROR: {exc}")
        raise typer.Exit(code=1) from exc
    except DownloadError as exc:
        print(f"ERROR: download failed: {exc}")
        raise typer.Exit(code=1) from exc
    # rebuild() returns existing meta unchanged when the source was not modified.
    if existed and meta.build_utc is not None:
        # A fresh build sets build_utc to "now"; reuse heuristic via run output.
        pass
    _print_summary(meta, header="GenCC database refreshed:")


@app.command()
def info() -> None:
    """Print provenance of the existing database, or a hint to build it."""
    config = get_data_config()
    if not config.db_path.exists():
        print(f"No GenCC database at {config.db_path}.")
        print("Run `gencc-link-data build` to download and build it.")
        raise typer.Exit(code=1)
    conn = sqlite3.connect(f"file:{config.db_path}?mode=ro", uri=True)
    try:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM meta WHERE id = 1").fetchone()
    finally:
        conn.close()
    if row is None:
        print("Database exists but has no provenance (meta) row.")
        print("Run `gencc-link-data build` to rebuild it.")
        raise typer.Exit(code=1)
    meta = BuildMeta(
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
    _print_summary(meta, header=f"GenCC database at {config.db_path}:")
    print(f"  source_etag    : {meta.source_etag}")
    print(f"  last_modified  : {meta.source_last_modified}")


def main() -> None:
    """Console-script entry point for ``gencc-link-data``."""
    app()


if __name__ == "__main__":
    main()
