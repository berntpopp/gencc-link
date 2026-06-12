# CLAUDE.md

@AGENTS.md

Claude Code entrypoint:

- Use `AGENTS.md` for shared instructions.
- Run `make ci-local` before final handoff.
- Repo-local skills in `.claude/skills/` apply to matching tasks:
  - `mcp-tool-change` - adding or renaming MCP tools
  - `data-schema-change` - changing the SQLite schema or ingest pipeline
  - `ci-failure-triage` - reproducing and root-causing CI failures
  - `release-readiness` - pre-release checklist
