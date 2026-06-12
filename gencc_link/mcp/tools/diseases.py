"""Disease tools: search_diseases and get_disease_curations."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any

from pydantic import Field

from gencc_link.mcp.annotations import READ_ONLY_OPEN_WORLD
from gencc_link.mcp.envelope import McpErrorContext, run_mcp_tool
from gencc_link.mcp.next_commands import after_disease_curations, after_search_diseases
from gencc_link.mcp.service_adapters import get_gencc_service
from gencc_link.models.enums import ResponseMode

if TYPE_CHECKING:
    from fastmcp import FastMCP

_MODE = Annotated[
    ResponseMode,
    Field(description="Verbosity: minimal | compact | standard | full (default compact)."),
]


def register_disease_tools(mcp: FastMCP) -> None:
    """Register disease-category tools."""

    @mcp.tool(
        name="search_diseases",
        title="Search GenCC Diseases",
        annotations=READ_ONLY_OPEN_WORLD,
        tags={"disease", "search"},
        description=(
            "Search the GenCC disease catalog by harmonized title (natural-language "
            "ok, porter-stemmed), MONDO id, or OMIM id. Returns ranked diseases with "
            "gene/submitter counts. Use to resolve free text before "
            "get_disease_curations."
        ),
    )
    async def search_diseases(
        query: str,
        response_mode: _MODE = "compact",
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            payload = get_gencc_service().search_diseases(
                query, response_mode=response_mode, limit=limit, offset=offset
            )
            curies = [d["disease_curie"] for d in payload.get("diseases", [])]
            payload["_meta"] = {"next_commands": after_search_diseases(curies)}
            return payload

        return await run_mcp_tool(
            "search_diseases", call, context=McpErrorContext("search_diseases")
        )

    @mcp.tool(
        name="get_disease_curations",
        title="Get Disease Curations",
        annotations=READ_ONLY_OPEN_WORLD,
        tags={"disease"},
        description=(
            "Return all genes asserted for one disease (by MONDO/OMIM id or title), "
            "each with a consensus classification across submitters and a conflict "
            "flag. Widen response_mode for the per-submitter breakdown."
        ),
    )
    async def get_disease_curations(
        disease: str,
        response_mode: _MODE = "compact",
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            payload = get_gencc_service().get_disease_curations(
                disease, response_mode=response_mode, limit=limit, offset=offset
            )
            disease_arg = payload.get("disease", {}).get("disease_curie", disease)
            gene_curies = [g["gene_curie"] for g in payload.get("genes", [])]
            payload["_meta"] = {
                "next_commands": after_disease_curations(disease_arg, gene_curies)
            }
            return payload

        return await run_mcp_tool(
            "get_disease_curations", call, context=McpErrorContext("get_disease_curations")
        )
