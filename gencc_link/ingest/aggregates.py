"""Derived-table construction for the GenCC SQLite build.

These helpers run after the raw ``submissions`` rows are loaded. They group
submissions into aggregated ``gene_disease`` rows (delegating the analytical
consensus/conflict logic to :mod:`gencc_link.services.consensus`) and roll those
up into the derived ``genes``, ``diseases``, and ``submitters`` catalogs.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from gencc_link.services.consensus import aggregate_gene_disease

#: Columns selected from ``submissions`` to feed the aggregator, in row order.
_AGG_SELECT_COLUMNS = (
    "gene_curie",
    "gene_symbol",
    "disease_curie",
    "disease_title",
    "classification_title",
    "moi_title",
    "submitter_curie",
    "submitter_title",
    "submitted_as_date",
    "submitted_as_public_report_url",
    "submitted_as_assertion_criteria_url",
    "submitted_as_pmids",
)


def build_gene_disease(conn: sqlite3.Connection) -> None:
    """Populate the aggregated ``gene_disease`` table from ``submissions``.

    Submissions are grouped by ``(gene_curie, disease_curie)``; each group is
    collapsed via :func:`aggregate_gene_disease` into a consensus row with
    JSON-encoded list columns and a per-submitter breakdown.

    Args:
        conn: Open connection to the in-progress build database.
    """
    select_sql = (
        "SELECT " + ", ".join(_AGG_SELECT_COLUMNS) + " FROM submissions "
        "ORDER BY gene_curie, disease_curie"
    )
    cursor = conn.execute(select_sql)

    insert_sql = (
        "INSERT INTO gene_disease ("
        "gene_curie, gene_symbol, disease_curie, disease_title, "
        "n_submissions, n_submitters, consensus_classification, consensus_rank, "
        "min_classification, min_rank, has_conflict, "
        "classification_titles_json, moi_titles_json, submitter_titles_json, "
        "pmids_json, submitters_json"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
    )

    batch: list[tuple[Any, ...]] = []
    current_key: tuple[str | None, str | None] | None = None
    group: list[dict[str, Any]] = []

    for row in cursor:
        record = dict(zip(_AGG_SELECT_COLUMNS, row, strict=True))
        key = (record["gene_curie"], record["disease_curie"])
        if current_key is not None and key != current_key:
            batch.append(_gene_disease_row(current_key, group))
            group = []
            if len(batch) >= 500:
                conn.executemany(insert_sql, batch)
                batch = []
        current_key = key
        group.append(record)

    if group and current_key is not None:
        batch.append(_gene_disease_row(current_key, group))
    if batch:
        conn.executemany(insert_sql, batch)


def _gene_disease_row(
    key: tuple[str | None, str | None],
    group: list[dict[str, Any]],
) -> tuple[Any, ...]:
    """Build one ``gene_disease`` insert tuple from a submission group."""
    agg = aggregate_gene_disease(group)
    first = group[0]
    gene_curie, disease_curie = key
    return (
        gene_curie,
        first.get("gene_symbol"),
        disease_curie,
        first.get("disease_title"),
        agg.n_submissions,
        agg.n_submitters,
        agg.consensus_classification,
        agg.consensus_rank,
        agg.min_classification,
        agg.min_rank,
        1 if agg.has_conflict else 0,
        json.dumps(agg.classification_titles),
        json.dumps(agg.moi_titles),
        json.dumps(agg.submitter_titles),
        json.dumps(agg.pmids),
        json.dumps(agg.submitters),
    )


def build_genes(conn: sqlite3.Connection) -> int:
    """Populate the derived ``genes`` catalog. Returns the gene count."""
    conn.execute(
        """
        INSERT INTO genes (
            gene_curie, gene_symbol, n_submissions, n_diseases,
            n_submitters, max_classification, max_classification_rank, has_conflict
        )
        SELECT
            s.gene_curie,
            MAX(s.gene_symbol) AS gene_symbol,
            COUNT(*) AS n_submissions,
            COUNT(DISTINCT s.disease_curie) AS n_diseases,
            COUNT(DISTINCT s.submitter_curie) AS n_submitters,
            NULL AS max_classification,
            gd.max_rank,
            gd.has_conflict
        FROM submissions AS s
        JOIN (
            SELECT
                gene_curie,
                MAX(consensus_rank) AS max_rank,
                MAX(has_conflict) AS has_conflict
            FROM gene_disease
            GROUP BY gene_curie
        ) AS gd ON gd.gene_curie = s.gene_curie
        GROUP BY s.gene_curie
        """
    )
    # Resolve the textual max_classification for each gene's strongest rank.
    _backfill_max_classification(conn, table="genes", id_column="gene_curie")
    return _count(conn, "genes")


def build_diseases(conn: sqlite3.Connection) -> int:
    """Populate the derived ``diseases`` catalog. Returns the disease count."""
    conn.execute(
        """
        INSERT INTO diseases (
            disease_curie, disease_title, n_submissions, n_genes,
            n_submitters, max_classification, max_classification_rank
        )
        SELECT
            s.disease_curie,
            MAX(s.disease_title) AS disease_title,
            COUNT(*) AS n_submissions,
            COUNT(DISTINCT s.gene_curie) AS n_genes,
            COUNT(DISTINCT s.submitter_curie) AS n_submitters,
            NULL,
            gd.max_rank
        FROM submissions AS s
        JOIN (
            SELECT disease_curie, MAX(consensus_rank) AS max_rank
            FROM gene_disease
            GROUP BY disease_curie
        ) AS gd ON gd.disease_curie = s.disease_curie
        GROUP BY s.disease_curie
        """
    )
    _backfill_max_classification(conn, table="diseases", id_column="disease_curie")
    return _count(conn, "diseases")


def build_submitters(conn: sqlite3.Connection) -> int:
    """Populate the derived ``submitters`` catalog. Returns the submitter count."""
    conn.execute(
        """
        INSERT INTO submitters (
            submitter_curie, submitter_title, n_submissions, n_genes, n_diseases
        )
        SELECT
            submitter_curie,
            MAX(submitter_title) AS submitter_title,
            COUNT(*) AS n_submissions,
            COUNT(DISTINCT gene_curie) AS n_genes,
            COUNT(DISTINCT disease_curie) AS n_diseases
        FROM submissions
        WHERE submitter_curie IS NOT NULL
        GROUP BY submitter_curie
        """
    )
    return _count(conn, "submitters")


def build_fts(conn: sqlite3.Connection) -> None:
    """Populate the FTS5 search tables from the derived catalogs."""
    conn.execute(
        "INSERT INTO genes_fts (gene_curie, gene_symbol) SELECT gene_curie, gene_symbol FROM genes"
    )
    conn.execute(
        "INSERT INTO diseases_fts (disease_curie, disease_title) "
        "SELECT disease_curie, disease_title FROM diseases "
        "WHERE disease_title IS NOT NULL"
    )


def _backfill_max_classification(
    conn: sqlite3.Connection,
    *,
    table: str,
    id_column: str,
) -> None:
    """Set ``max_classification`` text from the strongest ``gene_disease`` row.

    The numeric ``max_classification_rank`` is already populated; this resolves
    the corresponding human-readable title from the aggregated table.
    """
    conn.execute(
        f"""
        UPDATE {table} AS t
        SET max_classification = (
            SELECT gd.consensus_classification
            FROM gene_disease AS gd
            WHERE gd.{id_column} = t.{id_column}
              AND gd.consensus_rank = t.max_classification_rank
            LIMIT 1
        )
        WHERE t.max_classification_rank IS NOT NULL
        """
    )


def _count(conn: sqlite3.Connection, table: str) -> int:
    """Return the row count of ``table``."""
    row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
    return int(row[0]) if row else 0
