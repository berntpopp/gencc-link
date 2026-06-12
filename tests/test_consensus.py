"""Tests for consensus/conflict aggregation (gencc_link.services.consensus)."""

from __future__ import annotations

from gencc_link.constants import UNKNOWN_CLASSIFICATION_RANK, classification_rank
from gencc_link.services.consensus import (
    Aggregate,
    aggregate_gene_disease,
    parse_pmids,
)


def _row(
    classification: str | None,
    submitter_curie: str,
    *,
    submitter_title: str | None = None,
    moi: str | None = "Autosomal dominant",
    pmids: str | None = None,
) -> dict:
    return {
        "classification_title": classification,
        "submitter_curie": submitter_curie,
        "submitter_title": submitter_title or submitter_curie,
        "moi_title": moi,
        "submitted_as_date": "2020-01-01",
        "submitted_as_public_report_url": "http://example/report",
        "submitted_as_assertion_criteria_url": "http://example/criteria",
        "submitted_as_pmids": pmids,
    }


class TestParsePmids:
    def test_pmid_prefix_with_space(self) -> None:
        assert parse_pmids("PMID: 12345") == ["12345"]

    def test_semicolon_separated(self) -> None:
        assert parse_pmids("12345;67890") == ["12345", "67890"]

    def test_none(self) -> None:
        assert parse_pmids(None) == []

    def test_empty_string(self) -> None:
        assert parse_pmids("") == []

    def test_mixed_and_deduped(self) -> None:
        assert parse_pmids("PMID:12345; 12345, 67890") == ["12345", "67890"]

    def test_non_digit_dropped(self) -> None:
        assert parse_pmids("not-a-pmid; 999") == ["999"]


class TestClassificationRank:
    def test_known(self) -> None:
        assert classification_rank("Definitive") == 6

    def test_none(self) -> None:
        assert classification_rank(None) == UNKNOWN_CLASSIFICATION_RANK

    def test_unknown(self) -> None:
        assert classification_rank("Made Up") == UNKNOWN_CLASSIFICATION_RANK


class TestAggregateGeneDisease:
    def test_empty_list(self) -> None:
        agg = aggregate_gene_disease([])
        assert isinstance(agg, Aggregate)
        assert agg.n_submissions == 0
        assert agg.n_submitters == 0
        assert agg.consensus_classification is None
        assert agg.consensus_rank is None
        assert agg.min_rank is None
        assert agg.has_conflict is False

    def test_agreement_no_conflict(self) -> None:
        rows = [
            _row("Definitive", "GENCC:1", pmids="PMID: 111"),
            _row("Strong", "GENCC:2", pmids="222"),
        ]
        agg = aggregate_gene_disease(rows)
        assert agg.n_submissions == 2
        assert agg.n_submitters == 2
        assert agg.has_conflict is False
        # consensus_rank = max, min_rank = min
        assert agg.consensus_rank == classification_rank("Definitive")
        assert agg.min_rank == classification_rank("Strong")
        assert agg.consensus_classification == "Definitive"
        assert agg.min_classification == "Strong"

    def test_conflict_supporting_and_against(self) -> None:
        rows = [
            _row("Definitive", "GENCC:1"),
            _row("Refuted Evidence", "GENCC:2"),
        ]
        agg = aggregate_gene_disease(rows)
        assert agg.has_conflict is True
        assert agg.consensus_classification == "Definitive"
        assert agg.min_classification == "Refuted Evidence"

    def test_animal_model_only_no_conflict(self) -> None:
        rows = [
            _row("Animal Model Only", "GENCC:1"),
            _row("Animal Model Only", "GENCC:2"),
        ]
        agg = aggregate_gene_disease(rows)
        assert agg.has_conflict is False
        # Animal Model Only has a sentinel-but-still-real rank (-1 > UNKNOWN),
        # so it does participate in the consensus selection.
        assert agg.consensus_classification == "Animal Model Only"

    def test_submitters_ordered_strongest_first(self) -> None:
        rows = [
            _row("Limited", "GENCC:weak"),
            _row("Definitive", "GENCC:strong"),
            _row("Moderate", "GENCC:mid"),
        ]
        agg = aggregate_gene_disease(rows)
        titles = [s["classification_title"] for s in agg.submitters]
        assert titles == ["Definitive", "Moderate", "Limited"]

    def test_pmids_deduped_across_submitters(self) -> None:
        rows = [
            _row("Definitive", "GENCC:1", pmids="PMID: 100; 200"),
            _row("Strong", "GENCC:2", pmids="200;300"),
        ]
        agg = aggregate_gene_disease(rows)
        assert agg.pmids == ["100", "200", "300"]

    def test_distinct_submitter_count(self) -> None:
        # Same submitter twice -> counted once.
        rows = [
            _row("Definitive", "GENCC:1"),
            _row("Strong", "GENCC:1"),
        ]
        agg = aggregate_gene_disease(rows)
        assert agg.n_submissions == 2
        assert agg.n_submitters == 1

    def test_dedupe_lists(self) -> None:
        rows = [
            _row("Definitive", "GENCC:1", moi="Autosomal dominant"),
            _row("Definitive", "GENCC:2", moi="Autosomal dominant"),
        ]
        agg = aggregate_gene_disease(rows)
        assert agg.classification_titles == ["Definitive"]
        assert agg.moi_titles == ["Autosomal dominant"]

    def test_unknown_classification_excluded_from_ranks(self) -> None:
        rows = [
            _row(None, "GENCC:1"),
            _row("Definitive", "GENCC:2"),
        ]
        agg = aggregate_gene_disease(rows)
        # The None classification contributes no rank; Definitive wins.
        assert agg.consensus_classification == "Definitive"
        assert agg.min_classification == "Definitive"
