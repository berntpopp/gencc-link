"""Gene tools: search_genes, get_gene_curations, get_genes_curations."""

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
from gencc_link.mcp.service_adapters import get_gencc_service
from gencc_link.models.enums import ResponseMode

if TYPE_CHECKING:
    from fastmcp import FastMCP

_MODE = Annotated[
    ResponseMode,
    Field(description="Verbosity: minimal | compact | standard | full.", examples=["compact"]),
]
_GENE_SYMBOL = Annotated[
    str,
    Field(
        description="Gene identifier: an approved HGNC symbol (e.g. SKI) or an HGNC CURIE "
        "(e.g. HGNC:10896). Exact match; resolve free text with search_genes first.",
        examples=["SKI", "HGNC:10896"],
    ),
]
_LIMIT = Annotated[
    int, Field(description="Rows per page (1-200; above 200 is clamped).", examples=[20])
]
_OFFSET = Annotated[int, Field(description="Zero-based row offset for paging.", examples=[0])]
_CURSOR = Annotated[
    str | None,
    Field(description="Opaque, release-bound page token from a prior truncated.next_cursor."),
]


def register_gene_tools(mcp: FastMCP) -> None:
    """Register gene-category tools."""

    @mcp.tool(
        name="search_genes",
        title="Search GenCC Genes",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=None,
        tags={"gene", "search"},
        description=(
            "Search the GenCC gene catalog by approved symbol, partial symbol, or "
            "HGNC id. Returns ranked genes with assertion roll-ups (number of "
            "diseases, submitters, strongest classification, conflict flag). Use to "
            "resolve free text before get_gene_curations. Page large result sets via "
            "the release-bound truncated.next_cursor (surfaced as _meta.next_commands[0])."
        ),
    )
    async def search_genes(
        query: Annotated[
            str,
            Field(
                description="Gene symbol, partial symbol, or HGNC id to search for.",
                examples=["BRCA1", "SKI"],
            ),
        ],
        response_mode: _MODE = "compact",
        limit: _LIMIT = 20,
        offset: _OFFSET = 0,
        cursor: _CURSOR = None,
    ) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            payload = get_gencc_service().search_genes(
                query, response_mode=response_mode, limit=limit, offset=offset, cursor=cursor
            )
            curies = [g["gene_curie"] for g in payload.get("genes", [])]
            nexts: list[dict[str, Any]] = []
            trunc = payload.get("truncated") or {}
            if trunc.get("next_cursor"):
                # query is required by the schema; carry it so the affordance is
                # callable (the service restores the real query from the cursor).
                nexts.append(cmd("search_genes", query=query, cursor=trunc["next_cursor"]))
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
        output_schema=None,
        tags={"gene"},
        description=(
            "Return all GenCC gene-disease validity assertions for one gene, "
            "grouped by disease, each with a consensus classification across "
            "submitters and a conflict flag. Identify the gene with gene_symbol "
            "(an approved symbol OR an HGNC CURIE). Widen response_mode for the "
            "per-submitter breakdown. Page via the release-bound "
            "truncated.next_cursor (surfaced as _meta.next_commands[0])."
        ),
    )
    async def get_gene_curations(
        gene_symbol: _GENE_SYMBOL,
        response_mode: _MODE = "compact",
        limit: Annotated[
            int, Field(description="Rows per page (1-200; above 200 is clamped).", examples=[50])
        ] = 50,
        offset: _OFFSET = 0,
        cursor: _CURSOR = None,
    ) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            payload = get_gencc_service().get_gene_curations(
                gene_symbol, response_mode=response_mode, limit=limit, offset=offset, cursor=cursor
            )
            gene_arg = payload.get("gene", {}).get("gene_curie", gene_symbol)
            disease_curies = [d["disease_curie"] for d in payload.get("diseases", [])]
            nexts: list[dict[str, Any]] = []
            trunc = payload.get("truncated") or {}
            if trunc.get("next_cursor"):
                nexts.append(
                    cmd("get_gene_curations", gene_symbol=gene_arg, cursor=trunc["next_cursor"])
                )
            nexts.extend(after_gene_curations(gene_arg, disease_curies))
            payload["_meta"] = {"next_commands": nexts[:5]}
            return payload

        return await run_mcp_tool(
            "get_gene_curations",
            call,
            context=McpErrorContext("get_gene_curations", arguments={"gene_symbol": gene_symbol}),
            response_mode=response_mode,
        )

    @mcp.tool(
        name="get_genes_curations",
        title="Get Curations for Many Genes",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=None,
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
        genes: Annotated[
            list[str],
            Field(
                description="Gene symbols or HGNC ids (max 20).",
                examples=[["BRCA2", "NAA10"]],
            ),
        ],
        response_mode: _MODE = "compact",
        limit_per_gene: Annotated[
            int, Field(description="Max diseases returned per gene (1-200).", examples=[50])
        ] = 50,
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
