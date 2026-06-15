"""Assertion tools: get_gene_disease_assertion, find_curations, resolve_identifier."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any

from pydantic import Field

from gencc_link.exceptions import InvalidInputError
from gencc_link.mcp.annotations import READ_ONLY_OPEN_WORLD
from gencc_link.mcp.envelope import McpErrorContext, run_mcp_tool
from gencc_link.mcp.next_commands import after_assertion, cmd
from gencc_link.mcp.schemas import ASSERTION_SCHEMA, FIND_CURATIONS_SCHEMA, RESOLVE_SCHEMA
from gencc_link.mcp.service_adapters import get_gencc_service
from gencc_link.mcp.tools._args import coalesce_gene
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
        output_schema=ASSERTION_SCHEMA,
        tags={"assertion"},
        description=(
            "Deep dive on one gene-disease pair: every submitter's classification, "
            "mode of inheritance, evidence report URL, criteria URL, PMIDs, and "
            "dates, plus the consensus classification and conflict analysis. "
            "Identify the gene with EITHER gene_symbol (e.g. GLA) OR hgnc_id (HGNC "
            "CURIE) -- pass exactly one -- and the disease via MONDO/OMIM CURIE or "
            "title. response_mode=full adds, alongside the harmonized submitters[], "
            "a raw-extras submissions[] array (sgc_id, notes, original disease ids, "
            "version) -- not the fields already in submitters[], and with no "
            "pair-level union pmids; correlate a row to a submitter via submitter_title."
        ),
    )
    async def get_gene_disease_assertion(
        disease: str,
        gene_symbol: str | None = None,
        hgnc_id: str | None = None,
        response_mode: _MODE = "standard",
    ) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            gene = coalesce_gene(gene_symbol, hgnc_id, required=True)
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
                "get_gene_disease_assertion",
                arguments={
                    "gene_symbol": gene_symbol,
                    "hgnc_id": hgnc_id,
                    "disease": disease,
                },
            ),
            response_mode=response_mode,
        )

    @mcp.tool(
        name="find_curations",
        title="Find GenCC Curations",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=FIND_CURATIONS_SCHEMA,
        tags={"assertion", "search"},
        description=(
            "Filter aggregated gene-disease assertions by classification(s), "
            "submitter(s), mode of inheritance, gene (gene_symbol or hgnc_id), "
            "disease, or conflict status, with limit/offset paging. Example: "
            "classification=['Definitive'], "
            "moi='Autosomal dominant', submitter=['ClinGen']. At least one filter "
            "is required. classification/submitter/moi match at the submission "
            "level (any submitter), not the consensus -- each row's `matched` "
            "field names the triggering submission. Filter values are validated "
            "(case-insensitive); out-of-vocabulary values return invalid_input "
            "with the accepted set (see get_server_capabilities / list_submitters). "
            "Pass ids_only=true to return only {gene_curie, disease_curie} pairs for "
            "cheap paging, then fetch detail for the pairs you want. "
            "Large sweeps: follow truncated.next_cursor (an opaque, release-bound "
            "page token) via _meta.next_commands to page the full set; a cursor "
            "minted under a prior data release is rejected so a weekly refresh "
            "can't silently skip or duplicate rows."
        ),
    )
    async def find_curations(
        gene_symbol: str | None = None,
        hgnc_id: str | None = None,
        disease: str | None = None,
        classification: list[str] | None = None,
        submitter: list[str] | None = None,
        moi: str | None = None,
        has_conflict: bool | None = None,
        response_mode: _MODE = "compact",
        ids_only: bool = False,
        limit: int = 50,
        offset: int = 0,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            gene = coalesce_gene(gene_symbol, hgnc_id, required=False)
            payload = get_gencc_service().find_curations(
                gene=gene,
                disease=disease,
                classification=classification,
                submitter=submitter,
                moi=moi,
                has_conflict=has_conflict,
                response_mode=response_mode,
                ids_only=ids_only,
                limit=limit,
                offset=offset,
                cursor=cursor,
            )
            nexts: list[dict[str, Any]] = []
            trunc = payload.get("truncated") or {}
            if trunc.get("next_cursor"):
                # Page-forward first so an agent following next_commands[0]
                # sweeps the full result set autonomously (refresh-safe).
                nexts.append(cmd("find_curations", cursor=trunc["next_cursor"]))
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
        output_schema=RESOLVE_SCHEMA,
        tags={"discovery"},
        description=(
            "Resolve free text to a canonical GenCC gene (HGNC) and/or disease "
            "(MONDO) identifier by exact symbol/id/title match. Use kind='gene' or "
            "kind='disease' to disambiguate; default 'auto' tries both and returns "
            "ambiguous_query if the text matches both a gene and a disease. "
            "`identifier` is an alias for `query`; pass only one (supplying both with "
            "different values returns invalid_input)."
        ),
    )
    async def resolve_identifier(
        query: str | None = None,
        kind: str = "auto",
        identifier: str | None = None,
    ) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            if query is not None and identifier is not None and query.strip() != identifier.strip():
                raise InvalidInputError(
                    "Pass only one of `query`/`identifier` (they are aliases); "
                    f"got query={query!r} and identifier={identifier!r}.",
                    field="query",
                )
            q = query if query is not None else identifier
            if q is None:
                raise InvalidInputError("query must not be empty.", field="query")
            payload = get_gencc_service().resolve_identifier(q, kind=kind)
            nexts: list[dict[str, Any]] = []
            if payload.get("gene"):
                nexts.append(cmd("get_gene_curations", hgnc_id=payload["gene"]["gene_curie"]))
            if payload.get("disease"):
                nexts.append(
                    cmd("get_disease_curations", disease=payload["disease"]["disease_curie"])
                )
            payload["_meta"] = {"next_commands": nexts}
            return payload

        return await run_mcp_tool(
            "resolve_identifier",
            call,
            context=McpErrorContext(
                "resolve_identifier", arguments={"query": query or identifier or ""}
            ),
        )
