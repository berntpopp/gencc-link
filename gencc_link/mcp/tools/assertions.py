"""Assertion tools: get_gene_disease_assertion, find_curations, resolve_identifier."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any

from pydantic import Field

from gencc_link.mcp.annotations import READ_ONLY_OPEN_WORLD
from gencc_link.mcp.envelope import McpErrorContext, run_mcp_tool
from gencc_link.mcp.next_commands import after_assertion, cmd
from gencc_link.mcp.service_adapters import get_gencc_service
from gencc_link.models.enums import ResponseMode

if TYPE_CHECKING:
    from fastmcp import FastMCP

_MODE = Annotated[
    ResponseMode,
    Field(description="Verbosity: minimal | compact | standard | full."),
]


def register_assertion_tools(mcp: FastMCP) -> None:
    """Register assertion-detail, find, and resolve tools."""

    @mcp.tool(
        name="get_gene_disease_assertion",
        title="Get Gene-Disease Assertion",
        annotations=READ_ONLY_OPEN_WORLD,
        tags={"assertion"},
        description=(
            "Deep dive on one gene-disease pair: every submitter's classification, "
            "mode of inheritance, evidence report URL, criteria URL, PMIDs, and "
            "dates, plus the consensus classification and conflict analysis. Pass "
            "response_mode=full for raw submission rows including notes."
        ),
    )
    async def get_gene_disease_assertion(
        gene: str,
        disease: str,
        response_mode: _MODE = "standard",
    ) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            payload = get_gencc_service().get_gene_disease_assertion(
                gene, disease, response_mode=response_mode
            )
            assertion = payload.get("assertion", {})
            payload["_meta"] = {
                "next_commands": after_assertion(
                    assertion.get("gene_curie", gene), assertion.get("disease_curie", disease)
                )
            }
            return payload

        return await run_mcp_tool(
            "get_gene_disease_assertion",
            call,
            context=McpErrorContext(
                "get_gene_disease_assertion", arguments={"gene": gene, "disease": disease}
            ),
            response_mode=response_mode,
        )

    @mcp.tool(
        name="find_curations",
        title="Find GenCC Curations",
        annotations=READ_ONLY_OPEN_WORLD,
        tags={"assertion", "search"},
        description=(
            "Filter aggregated gene-disease assertions by classification(s), "
            "submitter(s), mode of inheritance, gene, disease, or conflict status, "
            "with limit/offset paging. Example: classification=['Definitive'], "
            "moi='Autosomal dominant', submitter=['ClinGen']. At least one filter "
            "is required."
        ),
    )
    async def find_curations(
        gene: str | None = None,
        disease: str | None = None,
        classification: list[str] | None = None,
        submitter: list[str] | None = None,
        moi: str | None = None,
        has_conflict: bool | None = None,
        response_mode: _MODE = "compact",
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            payload = get_gencc_service().find_curations(
                gene=gene,
                disease=disease,
                classification=classification,
                submitter=submitter,
                moi=moi,
                has_conflict=has_conflict,
                response_mode=response_mode,
                limit=limit,
                offset=offset,
            )
            nexts: list[dict[str, Any]] = []
            results = payload.get("results", [])
            if results:
                top = results[0]
                nexts.append(
                    cmd(
                        "get_gene_disease_assertion",
                        gene=top["gene_curie"],
                        disease=top["disease_curie"],
                    )
                )
            payload["_meta"] = {"next_commands": nexts}
            return payload

        return await run_mcp_tool(
            "find_curations",
            call,
            context=McpErrorContext("find_curations", arguments={}),
            response_mode=response_mode,
        )

    @mcp.tool(
        name="resolve_identifier",
        title="Resolve Identifier",
        annotations=READ_ONLY_OPEN_WORLD,
        tags={"discovery"},
        description=(
            "Resolve free text to a canonical GenCC gene (HGNC) and/or disease "
            "(MONDO) identifier by exact symbol/id/title match. Use kind='gene' or "
            "kind='disease' to disambiguate; default 'auto' tries both."
        ),
    )
    async def resolve_identifier(query: str, kind: str = "auto") -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            payload = get_gencc_service().resolve_identifier(query, kind=kind)
            nexts: list[dict[str, Any]] = []
            if payload.get("gene"):
                nexts.append(cmd("get_gene_curations", gene=payload["gene"]["gene_curie"]))
            if payload.get("disease"):
                nexts.append(
                    cmd("get_disease_curations", disease=payload["disease"]["disease_curie"])
                )
            payload["_meta"] = {"next_commands": nexts}
            return payload

        return await run_mcp_tool(
            "resolve_identifier",
            call,
            context=McpErrorContext("resolve_identifier", arguments={"query": query}),
        )
