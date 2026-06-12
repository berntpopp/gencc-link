"""Submission-filtered query helpers for ``find_curations``.

Extracted from :mod:`gencc_link.data.repository` so the read path stays within
the per-module line budget. Every function takes an open ``sqlite3`` connection;
aggregation is already pre-computed by the ingest builder, so these only build
WHERE clauses and read rows.

The flow keeps cost bounded by *page size* rather than the size of the match
set: resolve the matching ``(gene_curie, disease_curie)`` pairs in ``submissions``
(``matching_pairs``), fetch one ordered ``gene_disease`` page by primary key with
``LIMIT`` pushed into SQL (``gene_disease_page``), then build the ``matched``
detail only for that page (``matched_for_pairs``).
"""

from __future__ import annotations

import sqlite3


def submission_where(
    *,
    gene_curie: str | None,
    disease_curie: str | None,
    classification: list[str] | None,
    submitter: list[str] | None,
    moi: str | None,
) -> tuple[str, list[object]]:
    """Build the ``submissions`` WHERE clause (leading `` WHERE ``) and its params."""
    clauses: list[str] = []
    params: list[object] = []
    if gene_curie is not None:
        clauses.append("gene_curie = ?")
        params.append(gene_curie)
    if disease_curie is not None:
        clauses.append("disease_curie = ?")
        params.append(disease_curie)
    if classification:
        placeholders = ",".join("?" for _ in classification)
        clauses.append(f"classification_title IN ({placeholders})")
        params.extend(classification)
    if submitter:
        placeholders = ",".join("?" for _ in submitter)
        clauses.append(
            f"(submitter_title IN ({placeholders}) OR submitter_curie IN ({placeholders}))"
        )
        params.extend(submitter)
        params.extend(submitter)
    if moi:
        clauses.append("moi_title = ? COLLATE NOCASE")
        params.append(moi)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params


def matching_pairs(
    conn: sqlite3.Connection,
    *,
    gene_curie: str | None,
    disease_curie: str | None,
    classification: list[str] | None,
    submitter: list[str] | None,
    moi: str | None,
) -> list[tuple[str, str]]:
    """Distinct ``(gene_curie, disease_curie)`` pairs matching the submission filters."""
    where, params = submission_where(
        gene_curie=gene_curie,
        disease_curie=disease_curie,
        classification=classification,
        submitter=submitter,
        moi=moi,
    )
    sql = f"SELECT DISTINCT gene_curie, disease_curie FROM submissions{where}"
    return [(row["gene_curie"], row["disease_curie"]) for row in conn.execute(sql, params)]


def matched_for_pairs(
    conn: sqlite3.Connection,
    pairs: set[tuple[str, str]],
    *,
    classification: list[str] | None,
    submitter: list[str] | None,
    moi: str | None,
) -> dict[tuple[str, str], list[dict[str, str | None]]]:
    """Distinct triggering submissions for each of ``pairs`` (the returned page)."""
    if not pairs:
        return {}
    where, params = submission_where(
        gene_curie=None,
        disease_curie=None,
        classification=classification,
        submitter=submitter,
        moi=moi,
    )
    values = ",".join("(?,?)" for _ in pairs)
    pair_clause = f"(gene_curie, disease_curie) IN (VALUES {values})"
    where = f"{where} AND {pair_clause}" if where else f" WHERE {pair_clause}"
    params = [*params, *[value for pair in pairs for value in pair]]
    sql = (
        "SELECT gene_curie, disease_curie, submitter_title, classification_title, "
        f"moi_title FROM submissions{where}"
    )
    out: dict[tuple[str, str], list[dict[str, str | None]]] = {}
    seen: set[tuple[str, str, str | None, str | None, str | None]] = set()
    for row in conn.execute(sql, params):
        key = (row["gene_curie"], row["disease_curie"])
        dedupe = (*key, row["submitter_title"], row["classification_title"], row["moi_title"])
        if dedupe in seen:
            continue
        seen.add(dedupe)
        out.setdefault(key, []).append(
            {
                "submitter_title": row["submitter_title"],
                "classification_title": row["classification_title"],
                "moi_title": row["moi_title"],
            }
        )
    return out


def gene_disease_page(
    conn: sqlite3.Connection,
    *,
    pairs: set[tuple[str, str]] | None,
    gene_curie: str | None,
    disease_curie: str | None,
    has_conflict: bool | None,
    limit: int,
    offset: int,
) -> tuple[list[sqlite3.Row], int]:
    """Return one ordered ``gene_disease`` page plus the total match count.

    ``pairs`` (when given) restricts rows to an explicit pair set via the
    primary-key index; ``gene_curie``/``disease_curie``/``has_conflict`` apply
    directly. ``ORDER BY``/``LIMIT``/``OFFSET`` are pushed into SQL so only the
    page is materialised regardless of how many rows match.
    """
    clauses: list[str] = []
    params: list[object] = []
    if pairs is not None:
        if not pairs:
            return [], 0
        values = ",".join("(?,?)" for _ in pairs)
        clauses.append(f"(gene_curie, disease_curie) IN (VALUES {values})")
        params.extend(value for pair in pairs for value in pair)
    if gene_curie is not None:
        clauses.append("gene_curie = ?")
        params.append(gene_curie)
    if disease_curie is not None:
        clauses.append("disease_curie = ?")
        params.append(disease_curie)
    if has_conflict is not None:
        clauses.append("has_conflict = ?")
        params.append(1 if has_conflict else 0)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    total = int(conn.execute(f"SELECT COUNT(*) FROM gene_disease{where}", params).fetchone()[0])
    page = conn.execute(
        f"SELECT * FROM gene_disease{where} "
        "ORDER BY consensus_rank DESC, gene_symbol, disease_title LIMIT ? OFFSET ?",
        [*params, limit, offset],
    ).fetchall()
    return page, total
