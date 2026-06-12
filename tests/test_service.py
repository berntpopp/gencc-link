"""Tests for the GenCCService orchestration layer (via the sample database)."""

from __future__ import annotations

import pytest

from gencc_link.exceptions import AmbiguousQueryError, InvalidInputError, NotFoundError
from gencc_link.models import BuildMeta, DiseaseSummary, GeneSummary
from gencc_link.services.gencc_service import GenCCService


class _BothMatchRepo:
    """Minimal repo stub: the token 'AMBIG' resolves to BOTH a gene and a disease."""

    def resolve_gene(self, identifier: str) -> GeneSummary | None:
        if identifier.upper() == "AMBIG":
            return GeneSummary(
                gene_curie="HGNC:9", gene_symbol="AMBIG",
                n_submissions=1, n_diseases=1, n_submitters=1,
            )
        return None

    def resolve_disease(self, identifier: str) -> DiseaseSummary | None:
        if identifier.upper() == "AMBIG":
            return DiseaseSummary(
                disease_curie="MONDO:9", disease_title="AMBIG",
                n_submissions=1, n_genes=1, n_submitters=1,
            )
        return None


def test_resolve_identifier_auto_ambiguous_raises() -> None:
    svc = GenCCService(_BothMatchRepo(), cache_size=0, cache_ttl=0)  # type: ignore[arg-type]
    with pytest.raises(AmbiguousQueryError) as exc:
        svc.resolve_identifier("AMBIG", kind="auto")
    assert "HGNC:9" in str(exc.value)
    assert "MONDO:9" in str(exc.value)


def test_resolve_identifier_kind_gene_not_ambiguous() -> None:
    svc = GenCCService(_BothMatchRepo(), cache_size=0, cache_ttl=0)  # type: ignore[arg-type]
    out = svc.resolve_identifier("AMBIG", kind="gene")
    assert out["gene"]["gene_symbol"] == "AMBIG"
    assert out["disease"] is None


class TestSearchGenes:
    def test_hits_total_headline(self, service: GenCCService) -> None:
        out = service.search_genes("SKI")
        assert out["count"] >= 1
        assert out["total"] >= 1
        assert "headline" in out
        assert any(g["gene_symbol"] == "SKI" for g in out["genes"])

    def test_truncation_with_small_limit(self, service: GenCCService) -> None:
        # Broad prefix search across genes with limit 1 -> truncated.
        out = service.search_genes("COL1A1", limit=1)
        # Single match exact; ensure no error and structure ok.
        assert out["count"] == 1

    def test_truncation_block_on_paged_search(self, service: GenCCService) -> None:
        # A query matching many genes with a tiny limit shows a truncation block.
        out = service.search_genes("a", limit=1)
        if out["total"] > 1:
            assert "truncated" in out

    def test_empty_query_raises(self, service: GenCCService) -> None:
        with pytest.raises(InvalidInputError):
            service.search_genes("   ")

    def test_bad_response_mode_raises(self, service: GenCCService) -> None:
        with pytest.raises(InvalidInputError):
            service.search_genes("SKI", response_mode="verbose")

    def test_limit_below_one_raises(self, service: GenCCService) -> None:
        with pytest.raises(InvalidInputError):
            service.search_genes("SKI", limit=0)

    def test_negative_offset_raises(self, service: GenCCService) -> None:
        with pytest.raises(InvalidInputError):
            service.search_genes("SKI", offset=-1)


class TestSearchDiseases:
    def test_by_title(self, service: GenCCService) -> None:
        out = service.search_diseases("Fabry")
        assert out["total"] >= 1
        assert any("Fabry" in (d["disease_title"] or "") for d in out["diseases"])
        assert "headline" in out

    def test_by_mondo_curie(self, service: GenCCService) -> None:
        out = service.search_diseases("MONDO:0010526")
        assert out["total"] == 1

    def test_empty_query_raises(self, service: GenCCService) -> None:
        with pytest.raises(InvalidInputError):
            service.search_diseases("")


class TestGetGeneCurations:
    def test_ski(self, service: GenCCService) -> None:
        out = service.get_gene_curations("SKI")
        assert out["gene"]["gene_symbol"] == "SKI"
        assert out["total"] == 1
        assert out["diseases"][0]["disease_curie"] == "MONDO:0008426"
        assert "headline" in out

    def test_truncation(self, service: GenCCService) -> None:
        out = service.get_gene_curations("COL1A1", limit=1)
        assert out["count"] == 1
        # COL1A1 has 3 diseases -> truncated.
        assert "truncated" in out

    def test_not_found(self, service: GenCCService) -> None:
        with pytest.raises(NotFoundError):
            service.get_gene_curations("NOTAGENE")

    def test_empty_gene_raises(self, service: GenCCService) -> None:
        with pytest.raises(InvalidInputError):
            service.get_gene_curations("")


class TestGetDiseaseCurations:
    def test_by_curie(self, service: GenCCService) -> None:
        out = service.get_disease_curations("MONDO:0008426")
        assert out["disease"]["disease_curie"] == "MONDO:0008426"
        assert out["total"] >= 1
        assert any(g["gene_symbol"] == "SKI" for g in out["genes"])

    def test_not_found(self, service: GenCCService) -> None:
        with pytest.raises(NotFoundError):
            service.get_disease_curations("MONDO:9999999")

    def test_empty_raises(self, service: GenCCService) -> None:
        with pytest.raises(InvalidInputError):
            service.get_disease_curations("  ")


class TestGetGeneDiseaseAssertion:
    def test_gla_conflict(self, service: GenCCService) -> None:
        out = service.get_gene_disease_assertion("GLA", "MONDO:0010526")
        assert out["assertion"]["has_conflict"] is True
        assert out["assertion"]["strongest_classification"] == "Definitive"
        assert "CONFLICT" in out["headline"]

    def test_full_mode_adds_submissions(self, service: GenCCService) -> None:
        out = service.get_gene_disease_assertion("GLA", "MONDO:0010526", response_mode="full")
        assert "submissions" in out
        assert len(out["submissions"]) >= 1
        assert "submitters" in out["assertion"]

    def test_minimal_mode_upgrades_to_standard(self, service: GenCCService) -> None:
        # minimal -> shaping uses "standard" so submitters appear.
        out = service.get_gene_disease_assertion("SKI", "MONDO:0008426", response_mode="minimal")
        assert "submitters" in out["assertion"]
        assert "submissions" not in out

    def test_gene_not_found(self, service: GenCCService) -> None:
        with pytest.raises(NotFoundError):
            service.get_gene_disease_assertion("NOPE", "MONDO:0010526")

    def test_disease_not_found(self, service: GenCCService) -> None:
        with pytest.raises(NotFoundError):
            service.get_gene_disease_assertion("GLA", "MONDO:9999999")

    def test_no_link(self, service: GenCCService) -> None:
        # Both exist but are not linked.
        with pytest.raises(NotFoundError):
            service.get_gene_disease_assertion("SKI", "MONDO:0010526")

    def test_empty_gene_raises(self, service: GenCCService) -> None:
        with pytest.raises(InvalidInputError):
            service.get_gene_disease_assertion("", "MONDO:0010526")

    def test_empty_disease_raises(self, service: GenCCService) -> None:
        with pytest.raises(InvalidInputError):
            service.get_gene_disease_assertion("GLA", "")


class TestFindCurations:
    def test_has_conflict(self, service: GenCCService) -> None:
        out = service.find_curations(has_conflict=True)
        assert out["total"] == 2
        symbols = {r["gene_symbol"] for r in out["results"]}
        assert symbols == {"GLA", "LMNA"}

    def test_classification_filter(self, service: GenCCService) -> None:
        out = service.find_curations(classification=["Definitive"])
        assert out["total"] >= 1
        assert "filters" in out

    def test_submitter_filter(self, service: GenCCService) -> None:
        out = service.find_curations(submitter=["ClinGen"])
        assert out["total"] >= 1

    def test_moi_filter(self, service: GenCCService) -> None:
        out = service.find_curations(moi="Autosomal dominant")
        assert out["total"] >= 1

    def test_gene_filter(self, service: GenCCService) -> None:
        out = service.find_curations(gene="SKI")
        assert out["total"] == 1

    def test_requires_a_filter(self, service: GenCCService) -> None:
        with pytest.raises(InvalidInputError):
            service.find_curations()

    def test_ids_only_returns_just_pairs(self, service: GenCCService) -> None:
        full = service.find_curations(classification=["Definitive"])
        ids = service.find_curations(classification=["Definitive"], ids_only=True)
        assert ids["total"] == full["total"]
        assert ids["results"], "expected matches"
        for row in ids["results"]:
            assert set(row.keys()) == {"gene_curie", "disease_curie"}

    def test_unknown_gene_filter_empty(self, service: GenCCService) -> None:
        out = service.find_curations(gene="NOTAGENE")
        assert out["total"] == 0
        assert out["results"] == []


class TestListSubmitters:
    def test_count_and_order(self, service: GenCCService) -> None:
        out = service.list_submitters()
        assert out["count"] == 3
        titles = [s["submitter_title"] for s in out["submitters"]]
        # Ordered by submission volume desc; Ambry/ClinGen (11) before Orphanet (9).
        assert titles[-1] == "Orphanet"
        assert set(titles) == {"Ambry Genetics", "ClinGen", "Orphanet"}


class TestResolveIdentifier:
    def test_gene(self, service: GenCCService) -> None:
        out = service.resolve_identifier("SKI", kind="gene")
        assert out["gene"]["gene_symbol"] == "SKI"
        assert out["disease"] is None

    def test_disease(self, service: GenCCService) -> None:
        out = service.resolve_identifier("MONDO:0008426", kind="disease")
        assert out["disease"]["disease_curie"] == "MONDO:0008426"
        assert out["gene"] is None

    def test_auto_gene(self, service: GenCCService) -> None:
        out = service.resolve_identifier("GLA")
        assert out["gene"] is not None

    def test_not_found(self, service: GenCCService) -> None:
        with pytest.raises(NotFoundError):
            service.resolve_identifier("totally-unknown-xyz")

    def test_empty_raises(self, service: GenCCService) -> None:
        with pytest.raises(InvalidInputError):
            service.resolve_identifier("")

    def test_bad_kind_raises(self, service: GenCCService) -> None:
        with pytest.raises(InvalidInputError):
            service.resolve_identifier("SKI", kind="protein")


class TestMeta:
    def test_get_meta(self, service: GenCCService) -> None:
        meta = service.get_meta()
        assert isinstance(meta, BuildMeta)
        assert meta.row_count == 31


class TestCache:
    def test_repeated_search_returns_same_object(self, service: GenCCService) -> None:
        first = service.search_genes("SKI")
        second = service.search_genes("SKI")
        assert first is second

    def test_disease_cache(self, service: GenCCService) -> None:
        first = service.search_diseases("Fabry")
        second = service.search_diseases("Fabry")
        assert first is second

    def test_cache_disabled(self, repository) -> None:
        svc = GenCCService(repository, cache_size=0, cache_ttl=3600)
        first = svc.search_genes("SKI")
        second = svc.search_genes("SKI")
        # With cache disabled, distinct objects each call.
        assert first is not second
        assert first == second


class TestFindValidation:
    def test_invalid_classification_raises(self, service: GenCCService) -> None:
        with pytest.raises(InvalidInputError) as e:
            service.find_curations(classification=["Pathogenic"])
        assert e.value.field == "classification"

    def test_invalid_submitter_raises(self, service: GenCCService) -> None:
        with pytest.raises(InvalidInputError) as e:
            service.find_curations(submitter=["NotARealLab"])
        assert e.value.field == "submitter"

    def test_invalid_moi_raises(self, service: GenCCService) -> None:
        with pytest.raises(InvalidInputError) as e:
            service.find_curations(moi="Recessive")
        assert e.value.field == "moi"

    def test_case_insensitive_classification_returns_data(self, service: GenCCService) -> None:
        lower = service.find_curations(classification=["definitive"])
        canon = service.find_curations(classification=["Definitive"])
        assert lower["total"] == canon["total"] and lower["total"] > 0

    def test_case_insensitive_submitter_returns_data(self, service: GenCCService) -> None:
        out = service.find_curations(submitter=["clingen"])
        assert out["total"] >= 1

    def test_matched_present_in_compact(self, service: GenCCService) -> None:
        out = service.find_curations(classification=["Refuted Evidence"], response_mode="compact")
        assert out["results"]
        assert all("matched" in r for r in out["results"])
        first = out["results"][0]["matched"]
        assert any(m["classification_title"] == "Refuted Evidence" for m in first)

    def test_matched_absent_in_minimal(self, service: GenCCService) -> None:
        out = service.find_curations(classification=["Refuted Evidence"], response_mode="minimal")
        assert all("matched" not in r for r in out["results"])

    def test_no_matched_without_submission_filter(self, service: GenCCService) -> None:
        out = service.find_curations(has_conflict=True)
        assert all("matched" not in r for r in out["results"])

    def test_canonical_filters_echoed(self, service: GenCCService) -> None:
        out = service.find_curations(classification=["definitive"])
        assert out["filters"]["classification"] == ["Definitive"]


class TestRowTrim:
    def test_gene_curations_drops_gene_id_in_compact(self, service: GenCCService) -> None:
        out = service.get_gene_curations("SKI", response_mode="compact")
        assert out["gene"]["gene_curie"]
        assert all("gene_curie" not in d for d in out["diseases"])

    def test_gene_curations_keeps_gene_id_in_standard(self, service: GenCCService) -> None:
        out = service.get_gene_curations("SKI", response_mode="standard")
        assert all("gene_curie" in d for d in out["diseases"])

    def test_disease_curations_drops_disease_id_in_compact(self, service: GenCCService) -> None:
        out = service.get_disease_curations("MONDO:0008426", response_mode="compact")
        assert out["disease"]["disease_curie"]
        assert all("disease_curie" not in g for g in out["genes"])


class TestBatchCurations:
    def test_genes_curations_two_hits(self, service: GenCCService) -> None:
        out = service.get_genes_curations(["SKI", "GLA"])
        assert out["requested"] == 2
        assert out["count"] == 2
        symbols = {b["gene"]["gene_symbol"] for b in out["results"]}
        assert {"SKI", "GLA"} <= symbols
        assert "unresolved" not in out

    def test_genes_curations_dedupes_preserving_order(self, service: GenCCService) -> None:
        out = service.get_genes_curations(["SKI", "ski", "SKI"])
        assert out["requested"] == 1
        assert out["count"] == 1

    def test_genes_curations_partial_unresolved(self, service: GenCCService) -> None:
        out = service.get_genes_curations(["SKI", "NOTAGENE"])
        assert out["count"] == 1
        assert out["unresolved"] == [{"input": "NOTAGENE", "reason": "not_found"}]

    def test_genes_curations_all_unresolved_still_succeeds(self, service: GenCCService) -> None:
        out = service.get_genes_curations(["NOPE1", "NOPE2"])
        assert out["count"] == 0
        assert len(out["unresolved"]) == 2

    def test_genes_curations_empty_raises(self, service: GenCCService) -> None:
        with pytest.raises(InvalidInputError):
            service.get_genes_curations([])

    def test_genes_curations_over_cap_raises(self, service: GenCCService) -> None:
        with pytest.raises(InvalidInputError):
            service.get_genes_curations([f"G{i}" for i in range(21)])

    def test_genes_curations_limit_per_gene(self, service: GenCCService) -> None:
        out = service.get_genes_curations(["SKI"], limit_per_gene=1)
        assert out["results"][0]["count"] <= 1

    def test_diseases_curations_two_hits(self, service: GenCCService) -> None:
        out = service.get_diseases_curations(["MONDO:0008426", "MONDO:0010526"])
        assert out["requested"] == 2
        assert out["count"] >= 1
        assert all("genes" in b for b in out["results"])
