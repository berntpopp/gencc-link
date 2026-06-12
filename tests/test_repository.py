"""Tests for the read-only SQLite repository (gencc_link.data.repository)."""

from __future__ import annotations

import pytest

from gencc_link.data.repository import GenCCRepository
from gencc_link.exceptions import DataUnavailableError
from gencc_link.models import (
    BuildMeta,
    DiseaseSummary,
    GeneDiseaseAssertion,
    GeneSummary,
    SubmissionRecord,
    SubmitterAssertion,
    SubmitterSummary,
)


class TestConstruction:
    def test_missing_db_raises(self) -> None:
        with pytest.raises(DataUnavailableError):
            GenCCRepository("/nonexistent-gencc.sqlite")


class TestMeta:
    def test_get_meta(self, repository: GenCCRepository) -> None:
        meta = repository.get_meta()
        assert isinstance(meta, BuildMeta)
        assert meta.row_count == 31
        assert meta.gene_count == 21
        assert meta.disease_count == 23
        assert meta.submitter_count == 3
        assert meta.source_etag == "test-etag"


class TestGenes:
    def test_search_by_symbol(self, repository: GenCCRepository) -> None:
        hits, total = repository.search_genes("SKI", limit=10, offset=0)
        assert total >= 1
        assert isinstance(hits[0], GeneSummary)
        assert any(g.gene_symbol == "SKI" for g in hits)

    def test_search_by_hgnc_curie(self, repository: GenCCRepository) -> None:
        hits, total = repository.search_genes("HGNC:10896", limit=10, offset=0)
        assert total == 1
        assert hits[0].gene_symbol == "SKI"

    def test_search_by_prefix(self, repository: GenCCRepository) -> None:
        hits, total = repository.search_genes("COL", limit=10, offset=0)
        assert total >= 1
        assert all(g.gene_symbol.upper().startswith("COL") for g in hits)

    def test_pathological_fts_does_not_raise(self, repository: GenCCRepository) -> None:
        hits, total = repository.search_genes('a"b* OR', limit=10, offset=0)
        assert isinstance(total, int)
        assert isinstance(hits, list)

    def test_search_pagination(self, repository: GenCCRepository) -> None:
        hits, total = repository.search_genes("HGNC:10896", limit=10, offset=5)
        assert total == 1
        assert hits == []

    def test_resolve_gene_curie(self, repository: GenCCRepository) -> None:
        g = repository.resolve_gene("HGNC:10896")
        assert g is not None
        assert g.gene_symbol == "SKI"

    def test_resolve_gene_symbol_case_insensitive(self, repository: GenCCRepository) -> None:
        g = repository.resolve_gene("ski")
        assert g is not None
        assert g.gene_curie == "HGNC:10896"

    def test_resolve_gene_none(self, repository: GenCCRepository) -> None:
        assert repository.resolve_gene("NOTAGENE") is None


class TestDiseases:
    def test_search_by_title(self, repository: GenCCRepository) -> None:
        hits, total = repository.search_diseases("Fabry", limit=10, offset=0)
        assert total == 1
        assert isinstance(hits[0], DiseaseSummary)
        assert hits[0].disease_curie == "MONDO:0010526"

    def test_search_by_mondo_curie(self, repository: GenCCRepository) -> None:
        _hits, total = repository.search_diseases("MONDO:0010526", limit=10, offset=0)
        assert total == 1

    def test_search_by_omim_curie_mapping(self, repository: GenCCRepository) -> None:
        # OMIM:182212 maps to MONDO:0008426 via submissions.disease_original_curie.
        hits, total = repository.search_diseases("OMIM:182212", limit=10, offset=0)
        assert total == 1
        assert hits[0].disease_curie == "MONDO:0008426"

    def test_resolve_disease_by_curie(self, repository: GenCCRepository) -> None:
        d = repository.resolve_disease("MONDO:0008426")
        assert d is not None
        assert d.disease_curie == "MONDO:0008426"

    def test_resolve_disease_by_omim(self, repository: GenCCRepository) -> None:
        d = repository.resolve_disease("OMIM:182212")
        assert d is not None
        assert d.disease_curie == "MONDO:0008426"

    def test_resolve_disease_by_title(self, repository: GenCCRepository) -> None:
        d = repository.resolve_disease("shprintzen-goldberg syndrome")
        assert d is not None
        assert d.disease_curie == "MONDO:0008426"

    def test_resolve_disease_none(self, repository: GenCCRepository) -> None:
        assert repository.resolve_disease("MONDO:9999999") is None
        assert repository.resolve_disease("no such title") is None
        assert repository.resolve_disease("OMIM:9999999") is None

    def test_pathological_disease_fts(self, repository: GenCCRepository) -> None:
        hits, _total = repository.search_diseases('foo"bar* AND', limit=10, offset=0)
        assert isinstance(hits, list)


class TestPairs:
    def test_get_gene_disease_pairs(self, repository: GenCCRepository) -> None:
        pairs = repository.get_gene_disease_pairs("HGNC:10896")
        assert len(pairs) == 1
        a = pairs[0]
        assert isinstance(a, GeneDiseaseAssertion)
        assert a.disease_curie == "MONDO:0008426"
        assert a.submitters
        assert isinstance(a.submitters[0], SubmitterAssertion)

    def test_get_disease_gene_pairs(self, repository: GenCCRepository) -> None:
        pairs = repository.get_disease_gene_pairs("MONDO:0008426")
        assert len(pairs) >= 1
        assert any(p.gene_symbol == "SKI" for p in pairs)
        assert pairs[0].submitters

    def test_get_gene_disease_hit(self, repository: GenCCRepository) -> None:
        a = repository.get_gene_disease("HGNC:4296", "MONDO:0010526")
        assert a is not None
        assert a.has_conflict is True
        assert a.consensus_classification == "Definitive"

    def test_get_gene_disease_none(self, repository: GenCCRepository) -> None:
        assert repository.get_gene_disease("HGNC:10896", "MONDO:0010526") is None


class TestSubmissions:
    def test_get_submissions_pmids_and_notes(self, repository: GenCCRepository) -> None:
        subs = repository.get_submissions("HGNC:10896", "MONDO:0008426")
        assert len(subs) == 3
        assert all(isinstance(s, SubmissionRecord) for s in subs)
        # First (strongest) has parsed pmids.
        assert subs[0].pmids == ["22772368"]
        # Notes mapped from submitted_as_notes.
        assert subs[0].notes == "Curated from multiple unrelated families."
        # Ordered classification_rank DESC.
        ranks = [s.classification_rank for s in subs if s.classification_rank is not None]
        assert ranks == sorted(ranks, reverse=True)


class TestFindAssertions:
    def test_no_filters_returns_all(self, repository: GenCCRepository) -> None:
        _rows, total, _m = repository.find_assertions(limit=200, offset=0)
        assert total >= 1

    def test_has_conflict(self, repository: GenCCRepository) -> None:
        _rows, total, _m = repository.find_assertions(has_conflict=True, limit=50, offset=0)
        assert total == 2

    def test_has_conflict_false(self, repository: GenCCRepository) -> None:
        rows, total, _m = repository.find_assertions(has_conflict=False, limit=200, offset=0)
        assert total >= 1
        assert all(not r.has_conflict for r in rows)

    def test_gene_filter(self, repository: GenCCRepository) -> None:
        rows, total, _m = repository.find_assertions(gene="SKI", limit=50, offset=0)
        assert total == 1
        assert rows[0].gene_symbol == "SKI"

    def test_unknown_gene_filter(self, repository: GenCCRepository) -> None:
        rows, total, _m = repository.find_assertions(gene="NOPE", limit=50, offset=0)
        assert total == 0
        assert rows == []

    def test_disease_filter(self, repository: GenCCRepository) -> None:
        _rows, total, _m = repository.find_assertions(disease="MONDO:0008426", limit=50, offset=0)
        assert total >= 1

    def test_classification_filter(self, repository: GenCCRepository) -> None:
        _rows, total, _m = repository.find_assertions(
            classification=["Definitive"], limit=50, offset=0
        )
        assert total >= 1

    def test_submitter_filter_by_title(self, repository: GenCCRepository) -> None:
        _rows, total, _m = repository.find_assertions(submitter=["ClinGen"], limit=50, offset=0)
        assert total >= 1

    def test_moi_filter(self, repository: GenCCRepository) -> None:
        _rows, total, _m = repository.find_assertions(moi="Autosomal dominant", limit=50, offset=0)
        assert total >= 1

    def test_submission_filter_no_match_returns_empty(self, repository: GenCCRepository) -> None:
        rows, total, matched = repository.find_assertions(
            classification=["No Such Class"], limit=50, offset=0
        )
        assert total == 0
        assert rows == []
        assert matched == {}

    def test_combined_submission_and_conflict_filter(self, repository: GenCCRepository) -> None:
        rows, _total, _m = repository.find_assertions(
            classification=["Definitive"], has_conflict=True, limit=50, offset=0
        )
        # Both GLA conflict rows include a Definitive submission.
        assert all(r.has_conflict for r in rows)

    def test_pagination(self, repository: GenCCRepository) -> None:
        rows, total, _m = repository.find_assertions(has_conflict=True, limit=1, offset=0)
        assert total == 2
        assert len(rows) == 1

    def test_find_assertions_pair_lookup_matches_and_orders(
        self, repository: GenCCRepository
    ) -> None:
        # Refuted Evidence exists for the GLA conflict pair in the fixture.
        page, total, matched = repository.find_assertions(
            classification=["Refuted Evidence"], limit=50, offset=0
        )
        assert total == len(page)
        assert page, "expected at least one Refuted Evidence pair"
        # Every returned pair is present in the matched map (submission-level filter active).
        for a in page:
            assert (a.gene_curie, a.disease_curie) in matched
        # Ordering is by consensus_rank DESC then gene_symbol then disease_title.
        ranks = [a.consensus_rank for a in page if a.consensus_rank is not None]
        assert ranks == sorted(ranks, reverse=True)

    def test_find_assertions_has_conflict_filter_with_submission_filter(
        self, repository: GenCCRepository
    ) -> None:
        # GLA's Refuted pair conflicts; has_conflict=False must exclude it.
        confl, _t1, matched_confl = repository.find_assertions(
            classification=["Refuted Evidence"], has_conflict=True, limit=50, offset=0
        )
        noconfl, _t2, _m2 = repository.find_assertions(
            classification=["Refuted Evidence"], has_conflict=False, limit=50, offset=0
        )
        assert all(a.has_conflict for a in confl)
        assert all(not a.has_conflict for a in noconfl)
        # matched map is pruned to the rows that survived the conflict filter.
        keys = {(a.gene_curie, a.disease_curie) for a in confl}
        assert all(key in keys for key in matched_confl)


class TestFindMatched:
    def test_distinct_moi_includes_fixture_values(self, repository: GenCCRepository) -> None:
        titles = {t for t, _ in repository.distinct_moi()}
        assert {"Autosomal dominant", "Autosomal recessive", "X-linked"} <= titles

    def test_find_assertions_returns_matched_map(self, repository: GenCCRepository) -> None:
        page, total, matched = repository.find_assertions(
            classification=["Refuted Evidence"], limit=50, offset=0
        )
        assert total == len(page) and page
        for a in page:
            key = (a.gene_curie, a.disease_curie)
            assert key in matched
            assert any(m["classification_title"] == "Refuted Evidence" for m in matched[key])

    def test_find_assertions_no_submission_filter_empty_matched(
        self, repository: GenCCRepository
    ) -> None:
        page, total, matched = repository.find_assertions(has_conflict=True, limit=50, offset=0)
        assert matched == {}
        assert total == len(page)

    def test_submission_filter_covering_indexes(self, repository: GenCCRepository) -> None:
        index_sql = {
            row[0]: row[1] or ""
            for row in repository._conn.execute(
                "SELECT name, sql FROM sqlite_master WHERE type='index' AND name LIKE 'idx_sub_%'"
            )
        }
        # New covering indexes for submitter-title and case-insensitive moi filters.
        assert "idx_sub_submitter_title" in index_sql
        assert "idx_sub_moi_nocase" in index_sql
        # Each covers the projected (gene_curie, disease_curie) pair so the DISTINCT
        # pair scan in find.matching_pairs is index-only.
        assert "gene_curie" in index_sql["idx_sub_submitter_title"]
        assert "disease_curie" in index_sql["idx_sub_moi_nocase"]
        assert "gene_curie" in index_sql["idx_sub_classification"]


class TestSubmitters:
    def test_list_submitters_ordering(self, repository: GenCCRepository) -> None:
        subs = repository.list_submitters()
        assert len(subs) == 3
        assert all(isinstance(s, SubmitterSummary) for s in subs)
        counts = [s.n_submissions for s in subs]
        assert counts == sorted(counts, reverse=True)
        assert subs[-1].submitter_title == "Orphanet"


def test_close_is_idempotent(built_db_path) -> None:
    repo = GenCCRepository(built_db_path)
    repo.close()
