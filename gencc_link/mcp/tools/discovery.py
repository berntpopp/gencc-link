"""Discovery tools: server capabilities and data diagnostics."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from gencc_link.mcp.annotations import READ_ONLY_OPEN_WORLD
from gencc_link.mcp.capabilities import build_capabilities
from gencc_link.mcp.envelope import McpErrorContext, run_mcp_tool
from gencc_link.mcp.service_adapters import get_gencc_service
from gencc_link.mcp.untrusted_content import sanitize_message

if TYPE_CHECKING:
    from fastmcp import FastMCP


def register_discovery_tools(mcp: FastMCP) -> None:
    """Register get_server_capabilities and get_gencc_diagnostics."""

    @mcp.tool(
        name="get_server_capabilities",
        title="Get Server Capabilities",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=None,
        tags={"discovery"},
        description=(
            "Return the GenCC-Link tool inventory, classification vocabulary and "
            "ranks, response modes, recommended workflows, error codes, resources, "
            "and live data freshness. Compare `capabilities_version` to skip "
            "re-fetching when unchanged."
        ),
    )
    async def get_server_capabilities() -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            return build_capabilities()

        return await run_mcp_tool(
            "get_server_capabilities", call, context=McpErrorContext("get_server_capabilities")
        )

    @mcp.tool(
        name="get_gencc_diagnostics",
        title="Get GenCC Diagnostics",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=None,
        tags={"discovery"},
        description=(
            "Report build provenance and data freshness: GenCC run date, source "
            "ETag/last-modified, row/gene/disease/submitter counts, schema version, "
            "and when the local database was built. Also echoes server_version and "
            "capabilities_version so a warm client can poll this small payload for "
            "drift instead of re-fetching the full capabilities document."
        ),
    )
    async def get_gencc_diagnostics() -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            from gencc_link.config import get_data_config
            from gencc_link.mcp.capabilities import capabilities_version, server_version
            from gencc_link.services.refresh import get_active_scheduler

            meta = get_gencc_service().get_meta()
            cfg = get_data_config()
            scheduler = get_active_scheduler()
            refresh: dict[str, Any] = {
                "enabled": cfg.refresh_enabled,
                "interval_hours": cfg.refresh_interval_hours,
                "scheduler_running": scheduler is not None,
            }
            if scheduler is not None:
                status = scheduler.status
                # Defense in depth: last_error is severed to a fixed classification
                # at storage, but any string surfaced here is code-point sanitized so
                # no forbidden control/zero-width/bidi/NUL char can reach the caller.
                last_error = status.get("last_error")
                if isinstance(last_error, str):
                    status["last_error"] = sanitize_message(last_error)
                refresh["status"] = status
            quota: dict[str, Any] | None
            try:
                from gencc_link.ingest.downloader import download_quota_status

                quota = download_quota_status(cfg)
            except Exception:  # quota is observability-only; never break diagnostics
                quota = None
            result: dict[str, Any] = {
                "headline": (
                    f"GenCC data: {meta.row_count} submissions, {meta.gene_count} genes, "
                    f"{meta.disease_count} diseases from {meta.submitter_count} submitters; "
                    f"run date {meta.gencc_run_date or 'unknown'}."
                ),
                "server_version": server_version(),
                "capabilities_version": capabilities_version(),
                "data": meta.model_dump(),
                "refresh": refresh,
            }
            if quota is not None:
                result["quota"] = quota
            return result

        return await run_mcp_tool(
            "get_gencc_diagnostics", call, context=McpErrorContext("get_gencc_diagnostics")
        )
