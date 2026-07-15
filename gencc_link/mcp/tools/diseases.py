"""Disease tools: search_diseases, get_disease_curations, get_diseases_curations."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any

from pydantic import Field

from gencc_link.mcp.annotations import READ_ONLY_OPEN_WORLD
from gencc_link.mcp.envelope import McpErrorContext, run_mcp_tool
from gencc_link.mcp.next_commands import (
    after_disease_curations,
    after_diseases_curations,
    after_search_diseases,
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
_DISEASE = Annotated[
    str,
    Field(
        description="Disease identifier: a MONDO CURIE (MONDO:0009061), an OMIM CURIE "
        "(OMIM:163950), or an exact harmonized disease title.",
        examples=["MONDO:0009061", "Noonan syndrome"],
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


def register_disease_tools(mcp: FastMCP) -> None:
    """Register disease-category tools."""

    @mcp.tool(
        name="search_diseases",
        title="Search GenCC Diseases",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=None,
        tags={"disease", "search"},
        description=(
            "Search the GenCC disease catalog by harmonized title (natural-language "
            "ok, porter-stemmed), MONDO id, or OMIM id. Returns ranked diseases with "
            "gene/submitter counts. Use to resolve free text before "
            "get_disease_curations. Page large result sets via the release-bound "
            "truncated.next_cursor (surfaced as _meta.next_commands[0])."
        ),
    )
    async def search_diseases(
        query: Annotated[
            str,
            Field(
                description="Disease title (natural language ok), MONDO id, or OMIM id.",
                examples=["Noonan syndrome", "MONDO:0009061"],
            ),
        ],
        response_mode: _MODE = "compact",
        limit: _LIMIT = 20,
        offset: _OFFSET = 0,
        cursor: _CURSOR = None,
    ) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            payload = get_gencc_service().search_diseases(
                query, response_mode=response_mode, limit=limit, offset=offset, cursor=cursor
            )
            curies = [d["disease_curie"] for d in payload.get("diseases", [])]
            nexts: list[dict[str, Any]] = []
            trunc = payload.get("truncated") or {}
            if trunc.get("next_cursor"):
                # query is required by the schema; carry it so the affordance is
                # callable (the service restores the real query from the cursor).
                nexts.append(cmd("search_diseases", query=query, cursor=trunc["next_cursor"]))
            nexts.extend(after_search_diseases(curies, payload.get("query", query)))
            payload["_meta"] = {"next_commands": nexts[:5]}
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
        output_schema=None,
        tags={"disease"},
        description=(
            "Return all genes asserted for one disease (by MONDO/OMIM id or title), "
            "each with a consensus classification across submitters and a conflict "
            "flag. Widen response_mode for the per-submitter breakdown. Page via the "
            "release-bound truncated.next_cursor (surfaced as _meta.next_commands[0])."
        ),
    )
    async def get_disease_curations(
        disease: _DISEASE,
        response_mode: _MODE = "compact",
        limit: Annotated[
            int, Field(description="Rows per page (1-200; above 200 is clamped).", examples=[50])
        ] = 50,
        offset: _OFFSET = 0,
        cursor: _CURSOR = None,
    ) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            payload = get_gencc_service().get_disease_curations(
                disease, response_mode=response_mode, limit=limit, offset=offset, cursor=cursor
            )
            disease_arg = payload.get("disease", {}).get("disease_curie", disease)
            gene_curies = [g["gene_curie"] for g in payload.get("genes", [])]
            nexts: list[dict[str, Any]] = []
            trunc = payload.get("truncated") or {}
            if trunc.get("next_cursor"):
                nexts.append(
                    cmd("get_disease_curations", disease=disease_arg, cursor=trunc["next_cursor"])
                )
            nexts.extend(after_disease_curations(disease_arg, gene_curies))
            payload["_meta"] = {"next_commands": nexts[:5]}
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
        output_schema=None,
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
        diseases: Annotated[
            list[str],
            Field(
                description="Disease ids or titles (max 20).",
                examples=[["MONDO:0009061", "Marfan syndrome"]],
            ),
        ],
        response_mode: _MODE = "compact",
        limit_per_disease: Annotated[
            int, Field(description="Max genes returned per disease (1-200).", examples=[50])
        ] = 50,
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
