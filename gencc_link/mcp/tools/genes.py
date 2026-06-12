"""Gene tools: search_genes and get_gene_curations."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any

from pydantic import Field

from gencc_link.mcp.annotations import READ_ONLY_OPEN_WORLD
from gencc_link.mcp.envelope import McpErrorContext, run_mcp_tool
from gencc_link.mcp.next_commands import after_gene_curations, after_search_genes
from gencc_link.mcp.service_adapters import get_gencc_service
from gencc_link.models.enums import ResponseMode

if TYPE_CHECKING:
    from fastmcp import FastMCP

_MODE = Annotated[
    ResponseMode,
    Field(description="Verbosity: minimal | compact | standard | full (default compact)."),
]


def register_gene_tools(mcp: FastMCP) -> None:
    """Register gene-category tools."""

    @mcp.tool(
        name="search_genes",
        title="Search GenCC Genes",
        annotations=READ_ONLY_OPEN_WORLD,
        tags={"gene", "search"},
        description=(
            "Search the GenCC gene catalog by approved symbol, partial symbol, or "
            "HGNC id. Returns ranked genes with assertion roll-ups (number of "
            "diseases, submitters, strongest classification, conflict flag). Use to "
            "resolve free text before get_gene_curations."
        ),
    )
    async def search_genes(
        query: str,
        response_mode: _MODE = "compact",
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            payload = get_gencc_service().search_genes(
                query, response_mode=response_mode, limit=limit, offset=offset
            )
            curies = [g["gene_curie"] for g in payload.get("genes", [])]
            payload["_meta"] = {"next_commands": after_search_genes(curies)}
            return payload

        return await run_mcp_tool("search_genes", call, context=McpErrorContext("search_genes"))

    @mcp.tool(
        name="get_gene_curations",
        title="Get Gene Curations",
        annotations=READ_ONLY_OPEN_WORLD,
        tags={"gene"},
        description=(
            "Return all GenCC gene-disease validity assertions for one gene "
            "(by symbol or HGNC id), grouped by disease, each with a consensus "
            "classification across submitters and a conflict flag. Widen "
            "response_mode for the per-submitter breakdown."
        ),
    )
    async def get_gene_curations(
        gene: str,
        response_mode: _MODE = "compact",
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            payload = get_gencc_service().get_gene_curations(
                gene, response_mode=response_mode, limit=limit, offset=offset
            )
            gene_arg = payload.get("gene", {}).get("gene_curie", gene)
            disease_curies = [d["disease_curie"] for d in payload.get("diseases", [])]
            payload["_meta"] = {"next_commands": after_gene_curations(gene_arg, disease_curies)}
            return payload

        return await run_mcp_tool(
            "get_gene_curations", call, context=McpErrorContext("get_gene_curations")
        )
