"""Read-only SQLite repository for the built GenCC database.

Implements :class:`gencc_link.data.base.GenCCRepositoryProtocol` over a
read-only ``sqlite3`` connection. All aggregation is pre-computed by the ingest
builder, so this layer only reads rows and maps them onto the pydantic record
models. FTS5 queries are carefully sanitized to never pass raw user text into
``MATCH`` (which can raise), with a ``LIKE`` fallback for pathological input.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from gencc_link.data.queries import (
    assertion_from_row,
    disease_summary_from_row,
    gene_summary_from_row,
    like_pattern,
    sanitize_fts_query,
    submission_from_row,
)
from gencc_link.exceptions import DataUnavailableError
from gencc_link.models import (
    BuildMeta,
    DiseaseSummary,
    GeneDiseaseAssertion,
    GeneSummary,
    SubmissionRecord,
    SubmitterSummary,
)

_OMIM_PREFIX = "OMIM:"
_MONDO_PREFIX = "MONDO:"
_HGNC_PREFIX = "HGNC:"


class GenCCRepository:
    """Read-only access to the built GenCC SQLite database.

    The connection is opened in read-only mode and kept open for the lifetime of
    the instance. Call :meth:`close` to release it.
    """

    def __init__(self, db_path: Path | str) -> None:
        """Open a read-only connection to the GenCC database.

        Args:
            db_path: Filesystem path to the built SQLite database.

        Raises:
            DataUnavailableError: If the database file does not exist or cannot
                be opened in read-only mode.
        """
        self._path = Path(db_path)
        if not self._path.exists():
            raise DataUnavailableError(
                f"GenCC database not found at {self._path}. Build it first with `make data`."
            )
        try:
            self._conn = sqlite3.connect(
                f"file:{self._path}?mode=ro",
                uri=True,
                check_same_thread=False,
            )
        except sqlite3.Error as exc:  # pragma: no cover - rare OS-level failure
            raise DataUnavailableError(
                f"Cannot open GenCC database at {self._path}: {exc}. Rebuild it with `make data`."
            ) from exc
        self._conn.row_factory = sqlite3.Row

    # -- provenance --------------------------------------------------------------

    def get_meta(self) -> BuildMeta:
        """Return build provenance from the ``meta`` table.

        Raises:
            DataUnavailableError: If the ``meta`` row is missing (the database
                was not built or is corrupt).
        """
        try:
            row = self._conn.execute("SELECT * FROM meta WHERE id = 1").fetchone()
        except sqlite3.Error as exc:
            raise DataUnavailableError(
                f"GenCC database at {self._path} is unreadable: {exc}. Rebuild it with `make data`."
            ) from exc
        if row is None:
            raise DataUnavailableError(
                f"GenCC database at {self._path} has no build metadata. "
                "Rebuild it with `make data`."
            )
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

    # -- genes -------------------------------------------------------------------

    def search_genes(self, query: str, *, limit: int, offset: int) -> tuple[list[GeneSummary], int]:
        """FTS/exact search over the gene catalog.

        Args:
            query: HGNC CURIE (exact) or free text matched against gene symbols.
            limit: Maximum number of rows in the returned page.
            offset: Number of leading rows to skip.

        Returns:
            A ``(page, total_hits)`` tuple; ``total_hits`` is the full match
            count before pagination.
        """
        query = query.strip()
        if query.upper().startswith(_HGNC_PREFIX):
            row = self._conn.execute(
                "SELECT * FROM genes WHERE gene_curie = ? COLLATE NOCASE", (query,)
            ).fetchone()
            curies = [row["gene_curie"]] if row else []
        else:
            curies = self._gene_curies_for_text(query)

        total = len(curies)
        page_curies = curies[offset : offset + limit]
        return [self._gene_summary(c) for c in page_curies], total

    def _gene_curies_for_text(self, query: str) -> list[str]:
        """Return ranked, de-duplicated gene_curies for a free-text query.

        Exact (case-insensitive) symbol matches rank first, followed by FTS
        results in BM25 order. Falls back to ``LIKE`` if FTS5 raises.
        """
        ordered: list[str] = []
        seen: set[str] = set()

        exact_rows = self._conn.execute(
            "SELECT gene_curie FROM genes WHERE gene_symbol = ? COLLATE NOCASE",
            (query,),
        ).fetchall()
        for row in exact_rows:
            curie = row["gene_curie"]
            if curie not in seen:
                seen.add(curie)
                ordered.append(curie)

        for curie in self._gene_fts_curies(query):
            if curie not in seen:
                seen.add(curie)
                ordered.append(curie)
        return ordered

    def _gene_fts_curies(self, query: str) -> list[str]:
        """Run the gene FTS query (with LIKE fallback) and return gene_curies."""
        match = sanitize_fts_query(query)
        if match is not None:
            try:
                rows = self._conn.execute(
                    "SELECT f.gene_curie AS gene_curie FROM genes_fts f "
                    "JOIN genes g ON g.gene_curie = f.gene_curie "
                    "WHERE genes_fts MATCH ? ORDER BY rank",
                    (match,),
                ).fetchall()
                return [row["gene_curie"] for row in rows]
            except sqlite3.Error:
                pass  # Fall through to LIKE on any FTS5 syntax error.
        rows = self._conn.execute(
            "SELECT gene_curie FROM genes "
            "WHERE gene_symbol LIKE ? ESCAPE '\\' ORDER BY gene_symbol",
            (like_pattern(query),),
        ).fetchall()
        return [row["gene_curie"] for row in rows]

    def _gene_summary(self, gene_curie: str) -> GeneSummary:
        """Load a single ``genes`` row and build a :class:`GeneSummary`."""
        row = self._conn.execute(
            "SELECT * FROM genes WHERE gene_curie = ?", (gene_curie,)
        ).fetchone()
        return gene_summary_from_row(row)

    def resolve_gene(self, identifier: str) -> GeneSummary | None:
        """Resolve an exact HGNC CURIE or gene symbol to a gene summary.

        Args:
            identifier: An ``HGNC:nnnn`` CURIE or an exact gene symbol.

        Returns:
            The matching :class:`GeneSummary`, or ``None`` if not found.
        """
        identifier = identifier.strip()
        if identifier.upper().startswith(_HGNC_PREFIX):
            row = self._conn.execute(
                "SELECT * FROM genes WHERE gene_curie = ? COLLATE NOCASE",
                (identifier,),
            ).fetchone()
        else:
            row = self._conn.execute(
                "SELECT * FROM genes WHERE gene_symbol = ? COLLATE NOCASE",
                (identifier,),
            ).fetchone()
        return gene_summary_from_row(row) if row else None

    # -- diseases ----------------------------------------------------------------

    def search_diseases(
        self, query: str, *, limit: int, offset: int
    ) -> tuple[list[DiseaseSummary], int]:
        """FTS/exact search over the disease catalog.

        Args:
            query: A MONDO/OMIM CURIE (exact) or free text matched against
                disease titles.
            limit: Maximum number of rows in the returned page.
            offset: Number of leading rows to skip.

        Returns:
            A ``(page, total_hits)`` tuple.
        """
        query = query.strip()
        upper = query.upper()
        if upper.startswith(_MONDO_PREFIX) or upper.startswith(_OMIM_PREFIX):
            curies = self._disease_curies_for_curie(query)
        else:
            curies = self._disease_fts_curies(query)

        total = len(curies)
        page_curies = curies[offset : offset + limit]
        return [self._disease_summary(c) for c in page_curies], total

    def _disease_curies_for_curie(self, curie: str) -> list[str]:
        """Resolve a disease CURIE to harmonized disease_curies.

        Tries an exact ``diseases.disease_curie`` match first. For OMIM curies
        with no direct hit, maps via ``submissions.disease_original_curie`` to
        the harmonized ``disease_curie``.
        """
        row = self._conn.execute(
            "SELECT disease_curie FROM diseases WHERE disease_curie = ? COLLATE NOCASE",
            (curie,),
        ).fetchone()
        if row:
            return [row["disease_curie"]]
        if curie.upper().startswith(_OMIM_PREFIX):
            rows = self._conn.execute(
                "SELECT DISTINCT disease_curie FROM submissions "
                "WHERE disease_original_curie = ? COLLATE NOCASE",
                (curie,),
            ).fetchall()
            return [r["disease_curie"] for r in rows]
        return []

    def _disease_fts_curies(self, query: str) -> list[str]:
        """Run the disease FTS query (with LIKE fallback); return disease_curies."""
        match = sanitize_fts_query(query)
        if match is not None:
            try:
                rows = self._conn.execute(
                    "SELECT f.disease_curie AS disease_curie FROM diseases_fts f "
                    "JOIN diseases d ON d.disease_curie = f.disease_curie "
                    "WHERE diseases_fts MATCH ? ORDER BY rank",
                    (match,),
                ).fetchall()
                return [row["disease_curie"] for row in rows]
            except sqlite3.Error:
                pass
        rows = self._conn.execute(
            "SELECT disease_curie FROM diseases "
            "WHERE disease_title LIKE ? ESCAPE '\\' ORDER BY disease_title",
            (like_pattern(query),),
        ).fetchall()
        return [row["disease_curie"] for row in rows]

    def _disease_summary(self, disease_curie: str) -> DiseaseSummary:
        """Load a single ``diseases`` row and build a :class:`DiseaseSummary`."""
        row = self._conn.execute(
            "SELECT * FROM diseases WHERE disease_curie = ?", (disease_curie,)
        ).fetchone()
        return disease_summary_from_row(row)

    def resolve_disease(self, identifier: str) -> DiseaseSummary | None:
        """Resolve an exact disease CURIE (MONDO/OMIM) or title to a summary.

        Args:
            identifier: A disease CURIE, an exact disease title, or an OMIM
                curie that maps via the original submission curie.

        Returns:
            The matching :class:`DiseaseSummary`, or ``None`` if not found.
        """
        identifier = identifier.strip()
        upper = identifier.upper()
        if upper.startswith(_MONDO_PREFIX) or upper.startswith(_OMIM_PREFIX):
            curies = self._disease_curies_for_curie(identifier)
            return self._disease_summary(curies[0]) if curies else None
        row = self._conn.execute(
            "SELECT * FROM diseases WHERE disease_title = ? COLLATE NOCASE",
            (identifier,),
        ).fetchone()
        return disease_summary_from_row(row) if row else None

    # -- gene-disease assertions -------------------------------------------------

    def get_gene_disease_pairs(self, gene_curie: str) -> list[GeneDiseaseAssertion]:
        """All aggregated disease assertions for a gene (submitters populated).

        Args:
            gene_curie: The HGNC CURIE of the gene.

        Returns:
            Assertions ordered by consensus strength then disease title.
        """
        rows = self._conn.execute(
            "SELECT * FROM gene_disease WHERE gene_curie = ? "
            "ORDER BY consensus_rank DESC, disease_title",
            (gene_curie,),
        ).fetchall()
        return [assertion_from_row(row) for row in rows]

    def get_disease_gene_pairs(self, disease_curie: str) -> list[GeneDiseaseAssertion]:
        """All aggregated gene assertions for a disease (submitters populated).

        Args:
            disease_curie: The harmonized disease CURIE.

        Returns:
            Assertions ordered by consensus strength then gene symbol.
        """
        rows = self._conn.execute(
            "SELECT * FROM gene_disease WHERE disease_curie = ? "
            "ORDER BY consensus_rank DESC, gene_symbol",
            (disease_curie,),
        ).fetchall()
        return [assertion_from_row(row) for row in rows]

    def get_gene_disease(self, gene_curie: str, disease_curie: str) -> GeneDiseaseAssertion | None:
        """One aggregated gene-disease assertion (submitters populated).

        Args:
            gene_curie: The HGNC CURIE of the gene.
            disease_curie: The harmonized disease CURIE.

        Returns:
            The matching assertion, or ``None`` if the pair has no submissions.
        """
        row = self._conn.execute(
            "SELECT * FROM gene_disease WHERE gene_curie = ? AND disease_curie = ?",
            (gene_curie, disease_curie),
        ).fetchone()
        return assertion_from_row(row) if row else None

    def get_submissions(self, gene_curie: str, disease_curie: str) -> list[SubmissionRecord]:
        """Raw submission rows for a gene-disease pair (for full-detail views).

        Args:
            gene_curie: The HGNC CURIE of the gene.
            disease_curie: The harmonized disease CURIE.

        Returns:
            Submission records ordered strongest classification first.
        """
        rows = self._conn.execute(
            "SELECT * FROM submissions WHERE gene_curie = ? AND disease_curie = ? "
            "ORDER BY classification_rank DESC",
            (gene_curie, disease_curie),
        ).fetchall()
        return [submission_from_row(row) for row in rows]

    def find_assertions(
        self,
        *,
        gene: str | None = None,
        disease: str | None = None,
        classification: list[str] | None = None,
        submitter: list[str] | None = None,
        moi: str | None = None,
        has_conflict: bool | None = None,
        limit: int,
        offset: int,
    ) -> tuple[list[GeneDiseaseAssertion], int, dict[tuple[str, str], list[dict[str, str | None]]]]:
        """Filter aggregated gene-disease assertions.

        When ``classification``/``submitter``/``moi`` filters are present, the
        matching ``(gene_curie, disease_curie)`` pairs are first found in the
        raw ``submissions`` table, then the corresponding ``gene_disease`` rows
        are returned. Otherwise ``gene_disease`` is queried directly.

        Args:
            gene: Gene symbol or HGNC CURIE (resolved to a gene_curie).
            disease: A harmonized disease CURIE.
            classification: Classification titles to include (any-of).
            submitter: Submitter titles or curies to include (any-of).
            moi: Mode-of-inheritance title (case-insensitive exact).
            has_conflict: If set, filter on the conflict flag.
            limit: Maximum number of rows in the returned page.
            offset: Number of leading rows to skip.

        Returns:
            A ``(page, total, matched_by_pair)`` tuple. ``total`` is the distinct
            pair count; ``matched_by_pair`` maps each ``(gene_curie, disease_curie)``
            to the distinct submissions that satisfied a submission-level filter
            (empty when no such filter is active).
        """
        gene_curie: str | None = None
        if gene is not None:
            resolved = self.resolve_gene(gene)
            if resolved is None:
                return [], 0, {}
            gene_curie = resolved.gene_curie

        submission_filtered = bool(classification) or bool(submitter) or bool(moi)
        matched: dict[tuple[str, str], list[dict[str, str | None]]] = {}

        if submission_filtered:
            matched = self._matched_from_submissions(
                gene_curie=gene_curie,
                disease_curie=disease,
                classification=classification,
                submitter=submitter,
                moi=moi,
            )
            if not matched:
                return [], 0, {}
            rows = self._gene_disease_rows_for_pairs(set(matched), has_conflict=has_conflict)
            # Drop matched entries for pairs filtered out by has_conflict.
            kept = {(r["gene_curie"], r["disease_curie"]) for r in rows}
            matched = {k: v for k, v in matched.items() if k in kept}
        else:
            rows = self._gene_disease_rows_direct(
                gene_curie=gene_curie,
                disease_curie=disease,
                has_conflict=has_conflict,
            )

        total = len(rows)
        page = rows[offset : offset + limit]
        return [assertion_from_row(row) for row in page], total, matched

    def _matched_from_submissions(
        self,
        *,
        gene_curie: str | None,
        disease_curie: str | None,
        classification: list[str] | None,
        submitter: list[str] | None,
        moi: str | None,
    ) -> dict[tuple[str, str], list[dict[str, str | None]]]:
        """Map (gene_curie, disease_curie) -> distinct submissions matching the filters."""
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
        sql = (
            "SELECT gene_curie, disease_curie, submitter_title, classification_title, "
            f"moi_title FROM submissions{where}"
        )
        out: dict[tuple[str, str], list[dict[str, str | None]]] = {}
        seen: set[tuple[str, str, str | None, str | None, str | None]] = set()
        for row in self._conn.execute(sql, params).fetchall():
            key = (row["gene_curie"], row["disease_curie"])
            dedupe = (
                row["gene_curie"],
                row["disease_curie"],
                row["submitter_title"],
                row["classification_title"],
                row["moi_title"],
            )
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

    def distinct_moi(self) -> list[tuple[str, str | None]]:
        """Return distinct ``(moi_title, moi_curie)`` present in the submissions table."""
        rows = self._conn.execute(
            "SELECT moi_title, MAX(moi_curie) AS curie FROM submissions "
            "WHERE moi_title IS NOT NULL AND moi_title != '' "
            "GROUP BY moi_title ORDER BY moi_title"
        ).fetchall()
        return [(row["moi_title"], row["curie"]) for row in rows]

    def _gene_disease_rows_for_pairs(
        self, pairs: set[tuple[str, str]], *, has_conflict: bool | None
    ) -> list[sqlite3.Row]:
        """Fetch and sort ``gene_disease`` rows for an explicit set of pairs."""
        rows = self._conn.execute(
            "SELECT * FROM gene_disease ORDER BY consensus_rank DESC, gene_symbol, disease_title"
        ).fetchall()
        out: list[sqlite3.Row] = []
        for row in rows:
            if (row["gene_curie"], row["disease_curie"]) not in pairs:
                continue
            if has_conflict is not None and bool(row["has_conflict"]) != has_conflict:
                continue
            out.append(row)
        return out

    def _gene_disease_rows_direct(
        self,
        *,
        gene_curie: str | None,
        disease_curie: str | None,
        has_conflict: bool | None,
    ) -> list[sqlite3.Row]:
        """Query ``gene_disease`` directly for gene/disease/conflict filters."""
        clauses: list[str] = []
        params: list[object] = []
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
        sql = (
            f"SELECT * FROM gene_disease{where} "
            "ORDER BY consensus_rank DESC, gene_symbol, disease_title"
        )
        return self._conn.execute(sql, params).fetchall()

    # -- submitters --------------------------------------------------------------

    def list_submitters(self) -> list[SubmitterSummary]:
        """Return all submitting organizations with contribution counts.

        Returns:
            Submitters ordered by submission volume (descending).
        """
        rows = self._conn.execute("SELECT * FROM submitters ORDER BY n_submissions DESC").fetchall()
        return [
            SubmitterSummary(
                submitter_curie=row["submitter_curie"],
                submitter_title=row["submitter_title"],
                n_submissions=row["n_submissions"],
                n_genes=row["n_genes"],
                n_diseases=row["n_diseases"],
            )
            for row in rows
        ]

    # -- lifecycle ---------------------------------------------------------------

    def close(self) -> None:
        """Release the underlying database connection."""
        self._conn.close()
