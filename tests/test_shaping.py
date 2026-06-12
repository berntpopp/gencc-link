"""Tests for response shaping (gencc_link.services.shaping)."""

from __future__ import annotations

import pytest

from gencc_link.models import (
    DiseaseSummary,
    GeneDiseaseAssertion,
    GeneSummary,
    SubmissionRecord,
    SubmitterAssertion,
    SubmitterSummary,
)
from gencc_link.services import shaping


def _assertion(
    *, has_conflict: bool = False, min_class: str = "Refuted Evidence"
) -> GeneDiseaseAssertion:
    return GeneDiseaseAssertion(
        gene_curie="HGNC:4296",
        gene_symbol="GLA",
        disease_curie="MONDO:0010526",
        disease_title="Fabry disease",
        n_submissions=2,
        n_submitters=2,
        strongest_classification="Definitive",
        consensus_rank=6,
        min_classification=min_class,
        has_conflict=has_conflict,
        classification_titles=["Definitive", min_class],
        moi_titles=["X-linked"],
        submitter_titles=["Ambry Genetics", "ClinGen"],
        pmids=["111", "222"],
        submitters=[
            SubmitterAssertion(
                submitter_curie="GENCC:000101",
                submitter_title="Ambry Genetics",
                classification_title="Definitive",
                classification_rank=6,
                moi_title="X-linked",
                submitted_as_date="2020-01-01",
                public_report_url="http://example/report",
                assertion_criteria_url="http://example/criteria",
                pmids=["111"],
            ),
            SubmitterAssertion(
                submitter_curie="GENCC:000102",
                submitter_title="ClinGen",
                classification_title=min_class,
                classification_rank=0,
                moi_title="X-linked",
                pmids=["222"],
            ),
        ],
    )


class TestAssertionDict:
    def test_minimal_omits_min_classification(self) -> None:
        out = shaping.assertion_dict(_assertion(), "minimal")
        assert "min_classification" not in out
        assert "classification_titles" not in out
        assert "submitters" not in out
        assert out["strongest_classification"] == "Definitive"
        assert out["has_conflict"] is False

    def test_compact_has_submitter_titles_not_submitters(self) -> None:
        out = shaping.assertion_dict(_assertion(), "compact")
        assert "min_classification" in out
        assert "classification_titles" in out
        assert "submitter_titles" in out
        assert "submitters" not in out

    def test_standard_has_submitters_list(self) -> None:
        out = shaping.assertion_dict(_assertion(), "standard")
        assert "submitters" in out
        assert "submitter_titles" not in out
        first = out["submitters"][0]
        assert first["submitter_title"] == "Ambry Genetics"
        # standard adds date + report URL but not pmids/curie.
        assert "submitted_as_date" in first
        assert "public_report_url" in first
        assert "pmids" not in first
        assert "submitter_curie" not in first
        # top-level pmids only present in full.
        assert "pmids" not in out

    def test_full_has_pmids_and_full_submitter_fields(self) -> None:
        out = shaping.assertion_dict(_assertion(), "full")
        assert "submitters" in out
        assert out["pmids"] == ["111", "222"]
        first = out["submitters"][0]
        assert first["submitter_curie"] == "GENCC:000101"
        assert first["assertion_criteria_url"] == "http://example/criteria"
        assert first["pmids"] == ["111"]


class TestSummaryDicts:
    def _gene(self) -> GeneSummary:
        return GeneSummary(
            gene_curie="HGNC:10896",
            gene_symbol="SKI",
            n_submissions=3,
            n_diseases=1,
            n_submitters=3,
            max_classification="Definitive",
            has_conflict=False,
        )

    def _disease(self) -> DiseaseSummary:
        return DiseaseSummary(
            disease_curie="MONDO:0008426",
            disease_title="Shprintzen-Goldberg syndrome",
            n_submissions=3,
            n_genes=1,
            n_submitters=3,
            max_classification="Definitive",
        )

    def test_gene_minimal_keeps_submitters_omits_submissions(self) -> None:
        out = shaping.gene_summary_dict(self._gene(), "minimal")
        assert "n_submissions" not in out
        assert out["n_submitters"] == 3
        assert out["gene_symbol"] == "SKI"

    def test_gene_compact_has_counts(self) -> None:
        out = shaping.gene_summary_dict(self._gene(), "compact")
        assert out["n_submissions"] == 3
        assert out["n_submitters"] == 3

    def test_disease_minimal_keeps_submitters_omits_submissions(self) -> None:
        out = shaping.disease_summary_dict(self._disease(), "minimal")
        assert "n_submissions" not in out
        assert out["n_submitters"] == 3
        assert out["disease_title"] == "Shprintzen-Goldberg syndrome"

    def test_disease_standard_has_counts(self) -> None:
        out = shaping.disease_summary_dict(self._disease(), "standard")
        assert out["n_submissions"] == 3
        assert out["n_submitters"] == 3

    def test_submitter_dict(self) -> None:
        s = SubmitterSummary(
            submitter_curie="GENCC:000101",
            submitter_title="Ambry Genetics",
            n_submissions=11,
            n_genes=10,
            n_diseases=11,
        )
        out = shaping.submitter_dict(s)
        assert out == {
            "submitter_curie": "GENCC:000101",
            "submitter_title": "Ambry Genetics",
            "n_submissions": 11,
            "n_genes": 10,
            "n_diseases": 11,
        }

    def test_submission_dict(self) -> None:
        rec = SubmissionRecord(
            sgc_id="SGC-100001",
            version_number=1,
            gene_curie="HGNC:10896",
            gene_symbol="SKI",
            disease_curie="MONDO:0008426",
            disease_title="Shprintzen-Goldberg syndrome",
            disease_original_curie="OMIM:182212",
            disease_original_title="Shprintzen-Goldberg syndrome",
            classification_title="Definitive",
            classification_rank=6,
            moi_title="Autosomal dominant",
            submitter_curie="GENCC:000101",
            submitter_title="Ambry Genetics",
            submitted_as_date="2019-04-01",
            public_report_url="http://example/report",
            assertion_criteria_url="http://example/criteria",
            notes="Some notes.",
            pmids=["22772368"],
            submitted_run_date="2024-11-01",
        )
        out = shaping.submission_dict(rec)
        assert out["sgc_id"] == "SGC-100001"
        assert out["notes"] == "Some notes."
        assert out["pmids"] == ["22772368"]
        assert out["disease_original_curie"] == "OMIM:182212"


class TestSubmitterDictDictInput:
    def test_accepts_dict_like(self) -> None:
        out = shaping._submitter_dict(
            {
                "submitter_title": "ClinGen",
                "classification_title": "Definitive",
                "moi_title": "AD",
            },
            "compact",
        )
        assert out["submitter_title"] == "ClinGen"
        assert "submitted_as_date" not in out


class TestHeadlines:
    def test_gene_headline_includes_conflict(self) -> None:
        g = GeneSummary(
            gene_curie="HGNC:1",
            gene_symbol="G",
            n_submissions=1,
            n_diseases=1,
            n_submitters=1,
            max_classification=None,
            has_conflict=True,
        )
        head = shaping.gene_headline(g)
        assert "conflicting" in head
        assert "no classification" in head

    def test_disease_headline(self) -> None:
        d = DiseaseSummary(
            disease_curie="MONDO:1",
            disease_title=None,
            n_submissions=1,
            n_genes=2,
            n_submitters=1,
            max_classification=None,
        )
        head = shaping.disease_headline(d)
        # Falls back to curie when title is None.
        assert "MONDO:1" in head
        assert "no classification" in head

    def test_assertion_headline_conflict_and_range(self) -> None:
        head = shaping.assertion_headline(_assertion(has_conflict=True))
        assert "CONFLICT" in head
        assert "range Definitive..Refuted Evidence" in head

    def test_assertion_headline_no_conflict_no_range(self) -> None:
        # min == consensus -> no range, no CONFLICT.
        a = _assertion(has_conflict=False, min_class="Definitive")
        head = shaping.assertion_headline(a)
        assert "CONFLICT" not in head
        assert "range" not in head


class TestTruncationBlock:
    def test_none_when_fully_covered(self) -> None:
        assert shaping.truncation_block(total=5, limit=10, offset=0) is None
        assert shaping.truncation_block(total=10, limit=5, offset=5) is None

    def test_dict_when_more_remain(self) -> None:
        block = shaping.truncation_block(total=10, limit=5, offset=0)
        assert block is not None
        assert block["total"] == 10
        assert block["returned"] == 5
        assert block["next_offset"] == 5
        assert "hint" in block

    @pytest.mark.parametrize(
        ("total", "limit", "offset"),
        [(100, 20, 0), (100, 20, 40)],
    )
    def test_paging_offsets(self, total: int, limit: int, offset: int) -> None:
        block = shaping.truncation_block(total, limit, offset)
        assert block is not None
        assert block["next_offset"] == offset + limit

    def test_no_cursor_without_context(self) -> None:
        block = shaping.truncation_block(100, 50, 0)
        assert block is not None
        assert "next_cursor" not in block

    def test_mints_next_cursor_with_context(self) -> None:
        from gencc_link.services.cursor import decode_cursor

        block = shaping.truncation_block(
            100,
            50,
            0,
            cursor_context={"release": "2026-06-07", "filters": {"has_conflict": True}},
        )
        assert block is not None
        decoded = decode_cursor(block["next_cursor"])
        assert decoded["o"] == 50
        assert decoded["r"] == "2026-06-07"
        assert decoded["flt"]["has_conflict"] is True


class TestOmitParentId:
    def test_omit_gene_compact_drops_gene_keeps_disease(self) -> None:
        out = shaping.assertion_dict(_assertion(), "compact", omit_gene=True)
        assert "gene_curie" not in out and "gene_symbol" not in out
        assert out["disease_curie"]

    def test_omit_disease_compact_drops_disease_keeps_gene(self) -> None:
        out = shaping.assertion_dict(_assertion(), "compact", omit_disease=True)
        assert "disease_curie" not in out and "disease_title" not in out
        assert out["gene_curie"]

    def test_omit_gene_minimal(self) -> None:
        out = shaping.assertion_dict(_assertion(), "minimal", omit_gene=True)
        assert "gene_curie" not in out
        assert out["strongest_classification"]

    def test_omit_ignored_in_standard(self) -> None:
        out = shaping.assertion_dict(_assertion(), "standard", omit_gene=True)
        assert out["gene_curie"] == "HGNC:4296"


class TestSearchHeadlines:
    def _gene(self, symbol: str) -> GeneSummary:
        return GeneSummary(
            gene_curie=f"HGNC:{symbol}",
            gene_symbol=symbol,
            n_submissions=1,
            n_diseases=1,
            n_submitters=1,
            max_classification="Definitive",
        )

    def _disease(self, curie: str, title: str | None) -> DiseaseSummary:
        return DiseaseSummary(
            disease_curie=curie,
            disease_title=title,
            n_submissions=1,
            n_genes=1,
            n_submitters=1,
            max_classification="Definitive",
        )

    def test_single_total_one_uses_rich_headline(self) -> None:
        head = shaping.genes_search_headline("SKI", [self._gene("SKI")], total=1)
        assert head == shaping.gene_headline(self._gene("SKI"))

    def test_two_hits_names_all(self) -> None:
        hits = [self._gene("COL1A1"), self._gene("COL2A1")]
        head = shaping.genes_search_headline("COL", hits, total=2)
        assert "2 genes match 'COL'" in head
        assert "COL1A1" in head and "COL2A1" in head

    def test_sliced_shows_of_total(self) -> None:
        hits = [
            self._disease("MONDO:1", "Marfan syndrome"),
            self._disease("MONDO:2", "Stickler syndrome"),
            self._disease("MONDO:3", "long QT syndrome 1"),
        ]
        head = shaping.diseases_search_headline("syndrome", hits, total=1920)
        assert "3 of 1920 diseases match 'syndrome'" in head
        assert "Marfan syndrome" in head

    def test_caps_names_at_five(self) -> None:
        hits = [self._gene(f"G{i}") for i in range(7)]
        head = shaping.genes_search_headline("G", hits, total=7)
        assert "+2 more" in head
        assert head.count(",") >= 4  # 5 names listed

    def test_disease_falls_back_to_curie(self) -> None:
        hits = [self._disease("MONDO:1", None), self._disease("MONDO:2", None)]
        head = shaping.diseases_search_headline("x", hits, total=2)
        assert "MONDO:1" in head and "MONDO:2" in head


class TestDateNormalization:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("2017-08-29 00:00:00", "2017-08-29"),
            ("2024-08-29T00:00:00.000000Z", "2024-08-29"),
            ("2018-03-30 13:31:56", "2018-03-30"),
            ("2019-04-01", "2019-04-01"),
            (None, None),
            ("not a date", None),
            ("2020-13-01", None),
        ],
    )
    def test_normalize_submitted_date(self, raw: str | None, expected: str | None) -> None:
        assert shaping.normalize_submitted_date(raw) == expected

    def test_submitter_dict_standard_adds_iso(self) -> None:
        out = shaping._submitter_dict(
            {
                "submitter_title": "Ambry Genetics",
                "classification_title": "Definitive",
                "moi_title": "AD",
                "submitted_as_date": "2017-08-29 00:00:00",
                "public_report_url": None,
            },
            "standard",
        )
        assert out["submitted_as_date"] == "2017-08-29 00:00:00"
        assert out["submitted_as_date_iso"] == "2017-08-29"
