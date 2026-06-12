---
name: mcp-tool-change
description: Use when adding, renaming, or removing an MCP tool in gencc-link. Walks through the tool module, facade registration, the capabilities TOOLS tuple, tests, and the README/connection-guide tables.
---

# MCP tool change

Use this skill when changing the MCP tool surface (additions, renames, removals,
description rewrites). GenCC-Link exposes exactly 10 tools today; the tool list is
part of the public contract.

## Checklist

1. **Pick the tool module.** Tools are grouped by concern under
   `gencc_link/mcp/tools/`:
   - discovery: `discovery.py` (`get_server_capabilities`, `get_gencc_diagnostics`)
   - genes: `genes.py` (`search_genes`, `get_gene_curations`)
   - diseases: `diseases.py` (`search_diseases`, `get_disease_curations`)
   - assertions: `assertions.py` (`get_gene_disease_assertion`, `find_curations`,
     `resolve_identifier`)
   - submitters: `submitters.py` (`list_submitters`)
   Add the tool to the matching `register_*_tools(mcp)` function (create a new
   group only if it genuinely does not fit an existing one).

2. **Register in the facade.** If you added a new `register_*_tools` group, wire
   it into `gencc_link/mcp/facade.py` `create_gencc_mcp()`.

3. **Update the capabilities `TOOLS` tuple.** Edit
   `gencc_link/mcp/capabilities.py` — the `TOOLS` tuple is the canonical
   inventory returned by `get_server_capabilities` and the `gencc://capabilities`
   resource. Order matters; keep it consistent with the README table.

4. **Tune the description and envelope.** Write the tool description for an AI
   client choosing a tool: what it does, when to use it, input/output shape, and
   what it does NOT do. Keep `READ_ONLY_OPEN_WORLD` annotations
   (`gencc_link/mcp/annotations.py`), the `run_mcp_tool` envelope
   (`gencc_link/mcp/envelope.py`), `response_mode` shaping
   (`gencc_link/services/shaping.py`), and `_meta.next_commands`
   (`gencc_link/mcp/next_commands.py`).

5. **Error mapping.** If the tool can raise a new exception, ensure it maps to a
   typed error code (`invalid_input`, `not_found`, `ambiguous_query`,
   `data_unavailable`, `upstream_unavailable`, `rate_limited`, `internal_error`)
   in `gencc_link/exceptions.py` / the envelope classifier.

6. **Tests.** Add or update tests under `tests/` covering the tool's behavior,
   its presence in the capabilities inventory, `response_mode` shaping, and error
   masking. Run `make test` (optionally `-k <tool_name>`).

7. **Docs / tables.** Update the tool tables in `README.md`,
   `docs/MCP_CONNECTION_GUIDE.md`, and `docs/usage.md`. Mention the tool in
   `docs/architecture.md` if it changes the tool grouping.

8. **Preserved names.** Existing tool names are part of the public contract.
   Renaming or removing a tool requires a `CHANGELOG.md` entry and a migration
   note.

9. **CI.** Run `make ci-local`.
