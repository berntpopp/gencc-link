"""Unit tests for the gene_symbol/hgnc_id argument coalescer."""

from __future__ import annotations

import pytest

from gencc_link.exceptions import InvalidInputError
from gencc_link.mcp.tools._args import coalesce_gene


def test_coalesce_prefers_either_single_value() -> None:
    assert coalesce_gene("SKI", None, required=True) == "SKI"
    assert coalesce_gene(None, "HGNC:10896", required=True) == "HGNC:10896"


def test_coalesce_rejects_both() -> None:
    with pytest.raises(InvalidInputError) as exc:
        coalesce_gene("SKI", "HGNC:10896", required=True)
    assert exc.value.field == "hgnc_id"


def test_coalesce_required_missing_raises() -> None:
    with pytest.raises(InvalidInputError) as exc:
        coalesce_gene(None, None, required=True)
    assert exc.value.field == "gene_symbol"


def test_coalesce_optional_missing_is_none() -> None:
    assert coalesce_gene(None, None, required=False) is None
