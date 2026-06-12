"""Gene tools: search_genes and get_gene_curations."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any

from pydantic import Field

from gencc_link.mcp.annotations import READ_ONLY_OPEN_WORLD
from gencc_link.mcp.envelope import McpErrorContext, run_mcp_tool
from gencc_link.mcp.next_commands import (
    after_gene_curations,
    after_genes_curations,
    after_search_genes,
    cmd,
)
from gencc_link.mcp.schemas import (
    GENE_CURATIONS_SCHEMA,
    GENES_CURATIONS_SCHEMA,
    SEARCH_GENES_SCHEMA,
)
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
        output_schema=SEARCH_GENES_SCHEMA,
        tags={"gene", "search"},
        description=(
            "Search the GenCC gene catalog by approved symbol, partial symbol, or "
            "HGNC id. Returns ranked genes with assertion roll-ups (number of "
            "diseases, submitters, strongest classification, conflict flag). Use to "
            "resolve free text before get_gene_curations."
        ),
    )
    async def search_genes(
        query: str = "",
        response_mode: _MODE = "compact",
        limit: int = 20,
        offset: int = 0,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            payload = get_gencc_service().search_genes(
                query, response_mode=response_mode, limit=limit, offset=offset, cursor=cursor
            )
            curies = [g["gene_curie"] for g in payload.get("genes", [])]
            nexts: list[dict[str, Any]] = []
            trunc = payload.get("truncated") or {}
            if trunc.get("next_cursor"):
                # Page-forward first so an agent sweeping next_commands[0] walks
                # the full result set (refresh-safe).
                nexts.append(cmd("search_genes", cursor=trunc["next_cursor"]))
            nexts.extend(after_search_genes(curies, payload.get("query", query)))
            payload["_meta"] = {"next_commands": nexts[:5]}
            return payload

        return await run_mcp_tool(
            "search_genes",
            call,
            context=McpErrorContext("search_genes", arguments={"query": query}),
            response_mode=response_mode,
        )

    @mcp.tool(
        name="get_gene_curations",
        title="Get Gene Curations",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=GENE_CURATIONS_SCHEMA,
        tags={"gene"},
        description=(
            "Return all GenCC gene-disease validity assertions for one gene "
            "(by symbol or HGNC id), grouped by disease, each with a consensus "
            "classification across submitters and a conflict flag. Widen "
            "response_mode for the per-submitter breakdown."
        ),
    )
    async def get_gene_curations(
        gene: str = "",
        response_mode: _MODE = "compact",
        limit: int = 50,
        offset: int = 0,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            payload = get_gencc_service().get_gene_curations(
                gene, response_mode=response_mode, limit=limit, offset=offset, cursor=cursor
            )
            gene_arg = payload.get("gene", {}).get("gene_curie", gene)
            disease_curies = [d["disease_curie"] for d in payload.get("diseases", [])]
            nexts: list[dict[str, Any]] = []
            trunc = payload.get("truncated") or {}
            if trunc.get("next_cursor"):
                nexts.append(cmd("get_gene_curations", gene=gene_arg, cursor=trunc["next_cursor"]))
            nexts.extend(after_gene_curations(gene_arg, disease_curies))
            payload["_meta"] = {"next_commands": nexts[:5]}
            return payload

        return await run_mcp_tool(
            "get_gene_curations",
            call,
            context=McpErrorContext("get_gene_curations", arguments={"gene": gene}),
            response_mode=response_mode,
        )

    @mcp.tool(
        name="get_genes_curations",
        title="Get Curations for Many Genes",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=GENES_CURATIONS_SCHEMA,
        tags={"gene", "batch"},
        description=(
            "Batch form of get_gene_curations: pass a list of gene symbols or HGNC "
            "ids (max 20) and get each gene's disease assertions in one call. "
            "Unresolvable inputs come back in `unresolved` and the call still "
            "succeeds. Each result block mirrors get_gene_curations (gene summary + "
            "consensus diseases). Use limit_per_gene to cap diseases per gene and "
            "response_mode to widen detail."
        ),
    )
    async def get_genes_curations(
        genes: list[str],
        response_mode: _MODE = "compact",
        limit_per_gene: int = 50,
    ) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            payload = get_gencc_service().get_genes_curations(
                genes, response_mode=response_mode, limit_per_gene=limit_per_gene
            )
            payload["_meta"] = {"next_commands": after_genes_curations(payload)}
            return payload

        return await run_mcp_tool(
            "get_genes_curations",
            call,
            context=McpErrorContext("get_genes_curations", arguments={"genes": genes}),
            response_mode=response_mode,
        )
