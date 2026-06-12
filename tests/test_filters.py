"""Tests for find_curations filter validation (gencc_link.services.filters)."""

from __future__ import annotations

import pytest

from gencc_link.exceptions import InvalidInputError
from gencc_link.services.filters import validate_find_filters

SUBM_TITLES = {"ClinGen", "Ambry Genetics", "Labcorp Genetics (formerly Invitae)"}
SUBM_CURIES = {"GENCC:000102", "GENCC:000101", "GENCC:000106"}
MOI_TITLES = {"Autosomal dominant", "Autosomal recessive", "Y-linked inheritance"}


def _run(**kw: object) -> tuple[list[str] | None, list[str] | None, str | None]:
    base: dict[str, object] = {
        "classification": None,
        "submitter": None,
        "moi": None,
        "valid_submitter_titles": SUBM_TITLES,
        "valid_submitter_curies": SUBM_CURIES,
        "valid_moi_titles": MOI_TITLES,
    }
    base.update(kw)
    return validate_find_filters(**base)  # type: ignore[arg-type]


class TestClassification:
    def test_canonicalises_case(self) -> None:
        c, _, _ = _run(classification=["definitive", "STRONG"])
        assert c == ["Definitive", "Strong"]

    def test_rejects_unknown_with_accepted_values(self) -> None:
        with pytest.raises(InvalidInputError) as e:
            _run(classification=["Pathogenic"])
        assert e.value.field == "classification"
        assert "Pathogenic" in e.value.message
        assert "Definitive" in e.value.message

    def test_collects_multiple_invalid(self) -> None:
        with pytest.raises(InvalidInputError) as e:
            _run(classification=["Pathogenic", "Benign"])
        assert "Pathogenic" in e.value.message and "Benign" in e.value.message


class TestSubmitter:
    def test_canonicalises_title_case(self) -> None:
        _, s, _ = _run(submitter=["clingen"])
        assert s == ["ClinGen"]

    def test_accepts_curie(self) -> None:
        _, s, _ = _run(submitter=["GENCC:000102"])
        assert s == ["GENCC:000102"]

    def test_rejects_unknown_points_to_list_submitters(self) -> None:
        with pytest.raises(InvalidInputError) as e:
            _run(submitter=["NotARealLab"])
        assert e.value.field == "submitter"
        assert "list_submitters" in e.value.message


class TestMoi:
    def test_canonicalises_case(self) -> None:
        _, _, m = _run(moi="autosomal recessive")
        assert m == "Autosomal recessive"

    def test_rejects_short_form_with_did_you_mean(self) -> None:
        with pytest.raises(InvalidInputError) as e:
            _run(moi="Recessive")
        assert e.value.field == "moi"
        assert "Autosomal recessive" in e.value.message

    def test_accepts_quirky_real_title(self) -> None:
        _, _, m = _run(moi="y-linked inheritance")
        assert m == "Y-linked inheritance"


class TestSuggest:
    OPTIONS = ["Autosomal dominant", "Autosomal recessive", "X-linked recessive"]

    def test_case_insensitive_prefers_autosomal_recessive(self) -> None:
        from gencc_link.services.filters import _suggest

        msg = _suggest("Recessive", self.OPTIONS)
        assert "Autosomal recessive" in msg

    def test_offers_multiple_close_matches(self) -> None:
        from gencc_link.services.filters import _suggest

        msg = _suggest("recessive", self.OPTIONS)
        assert "Autosomal recessive" in msg and "X-linked recessive" in msg

    def test_no_match_is_empty(self) -> None:
        from gencc_link.services.filters import _suggest

        assert _suggest("zzzzz", self.OPTIONS) == ""


def test_all_none_passes_through() -> None:
    assert _run() == (None, None, None)


def test_blank_moi_is_ignored() -> None:
    assert _run(moi="   ") == (None, None, None)
