"""Disease tools: search_diseases and get_disease_curations."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any

from pydantic import Field

from gencc_link.mcp.annotations import READ_ONLY_OPEN_WORLD
from gencc_link.mcp.envelope import McpErrorContext, run_mcp_tool
from gencc_link.mcp.next_commands import (
    after_disease_curations,
    after_diseases_curations,
    after_search_diseases,
)
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
            payload["_meta"] = {"next_commands": after_search_diseases(curies, query)}
            return payload

        return await run_mcp_tool(
            "search_diseases",
            call,
            context=McpErrorContext("search_diseases", arguments={"query": query}),
            response_mode=response_mode,
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
            payload["_meta"] = {"next_commands": after_disease_curations(disease_arg, gene_curies)}
            return payload

        return await run_mcp_tool(
            "get_disease_curations",
            call,
            context=McpErrorContext("get_disease_curations", arguments={"disease": disease}),
            response_mode=response_mode,
        )

    @mcp.tool(
        name="get_diseases_curations",
        title="Get Curations for Many Diseases",
        annotations=READ_ONLY_OPEN_WORLD,
        tags={"disease", "batch"},
        description=(
            "Batch form of get_disease_curations: pass a list of disease ids or "
            "titles (max 20) and get each disease's gene assertions in one call. "
            "Unresolvable inputs come back in `unresolved` and the call still "
            "succeeds. Each result block mirrors get_disease_curations (disease "
            "summary + consensus genes). Use limit_per_disease to cap genes per "
            "disease and response_mode to widen detail."
        ),
    )
    async def get_diseases_curations(
        diseases: list[str],
        response_mode: _MODE = "compact",
        limit_per_disease: int = 50,
    ) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            payload = get_gencc_service().get_diseases_curations(
                diseases, response_mode=response_mode, limit_per_disease=limit_per_disease
            )
            payload["_meta"] = {"next_commands": after_diseases_curations(payload)}
            return payload

        return await run_mcp_tool(
            "get_diseases_curations",
            call,
            context=McpErrorContext("get_diseases_curations", arguments={"diseases": diseases}),
            response_mode=response_mode,
        )
