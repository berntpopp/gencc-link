"""Shared MCP-tool argument helpers."""

from __future__ import annotations

from typing import Literal, overload

from gencc_link.exceptions import InvalidInputError


@overload
def coalesce_gene(
    gene_symbol: str | None, hgnc_id: str | None, *, required: Literal[True]
) -> str: ...


@overload
def coalesce_gene(
    gene_symbol: str | None, hgnc_id: str | None, *, required: Literal[False]
) -> str | None: ...


def coalesce_gene(gene_symbol: str | None, hgnc_id: str | None, *, required: bool) -> str | None:
    """Collapse the canonical ``gene_symbol`` / ``hgnc_id`` pair into one input.

    GenCC resolves a gene from either an approved symbol or an HGNC CURIE, so the
    two fleet-canonical arguments are mutually exclusive aliases for the single
    polymorphic service ``gene`` parameter. Returns the supplied value (forwarded
    to the service) or ``None`` when neither is given and the caller permits an
    absent gene filter. With ``required=True`` the return is narrowed to ``str``
    (a missing value raises before returning).

    Raises ``InvalidInputError`` (-> ``invalid_input`` envelope) when both are
    supplied, or when neither is supplied and ``required`` is True. Call this from
    inside the tool's ``run_mcp_tool`` body so the raise is enveloped.
    """
    if gene_symbol is not None and hgnc_id is not None:
        raise InvalidInputError(
            "Pass only one of `gene_symbol` / `hgnc_id`, not both.", field="hgnc_id"
        )
    value = gene_symbol if gene_symbol is not None else hgnc_id
    if value is None and required:
        raise InvalidInputError(
            "Provide `gene_symbol` (approved symbol) or `hgnc_id` (HGNC CURIE).",
            field="gene_symbol",
        )
    return value
