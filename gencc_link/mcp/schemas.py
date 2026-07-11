"""JSON Schema (2020-12) output schemas advertised by GenCC-Link tools.

FastMCP already emits ``structuredContent`` for dict-returning tools, but with a
contentless ``{type: object, additionalProperties: true}`` schema. These schemas
give clients a real, conformant field glossary. ``additionalProperties: true`` and
``required: ["success"]`` keep every response_mode tier and error envelope valid
(per the MCP spec, the server MUST make structuredContent conform to outputSchema).
"""

from __future__ import annotations

from typing import Any

_STR = {"type": "string"}
_INT = {"type": "integer"}
_BOOL = {"type": "boolean"}
_OBJ: dict[str, Any] = {"type": "object", "additionalProperties": True}
_OBJ_OR_NULL: dict[str, Any] = {"type": ["object", "null"], "additionalProperties": True}
_OBJ_ARRAY: dict[str, Any] = {"type": "array", "items": _OBJ}
_ARRAY: dict[str, Any] = {"type": "array"}

_NEXT_COMMANDS = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {"tool": _STR, "arguments": _OBJ},
        "required": ["tool", "arguments"],
        "additionalProperties": False,
    },
}

_META = {
    "type": "object",
    "description": "Per-call envelope metadata.",
    "properties": {
        "request_id": _STR,
        "elapsed_ms": {"type": "number"},
        "response_mode": _STR,
        "data_license": _STR,
        "unsafe_for_clinical_use": _BOOL,
        "gencc_release": _STR,
        "recommended_citation": _STR,
        "citation_ref": _STR,
        "citation_short": _STR,
        "next_commands": _NEXT_COMMANDS,
        "tool": _STR,
    },
    "additionalProperties": True,
}

_TRUNCATION = {
    "type": "object",
    "properties": {
        "total": _INT,
        "returned": _INT,
        "next_offset": _INT,
        "next_cursor": _STR,
        "hint": _STR,
    },
    "additionalProperties": True,
}

# Response-Envelope Standard v1.1: externally sourced free text (e.g. a raw
# GenCC submission's ``notes``) is emitted as this typed object, never a bare
# string. ``kind`` is a real schema literal (``const``), matching the pydantic
# ``Literal["untrusted_text"]`` in ``gencc_link.mcp.untrusted_content.UntrustedText``.
_UNTRUSTED_TEXT: dict[str, Any] = {
    "type": "object",
    "properties": {
        "kind": {"const": "untrusted_text"},
        "text": _STR,
        "provenance": {
            "type": "object",
            "properties": {"source": _STR, "record_id": _STR, "retrieved_at": _STR},
            "required": ["source", "record_id", "retrieved_at"],
            "additionalProperties": True,
        },
        "raw_sha256": _STR,
    },
    "required": ["kind", "text", "provenance", "raw_sha256"],
    "additionalProperties": True,
}
_UNTRUSTED_TEXT_OR_NULL: dict[str, Any] = {"anyOf": [_UNTRUSTED_TEXT, {"type": "null"}]}

# One row of get_gene_disease_assertion's response_mode=full raw-extras
# submissions[] array; the only property with a fixed shape is the fenced
# `notes` (v1.1 untrusted_text), everything else stays permissive.
_SUBMISSION_ITEM: dict[str, Any] = {
    "type": "object",
    "properties": {"notes": _UNTRUSTED_TEXT_OR_NULL},
    "additionalProperties": True,
}
_SUBMISSIONS_ARRAY: dict[str, Any] = {"type": "array", "items": _SUBMISSION_ITEM}

# Fields shared by success and error envelopes (all optional but ``success``).
_BASE_PROPS: dict[str, Any] = {
    "success": _BOOL,
    "headline": _STR,
    "_meta": _META,
    "error_code": _STR,
    "message": _STR,
    "retryable": _BOOL,
    "recovery_action": _STR,
    "field_errors": _OBJ_ARRAY,
}


def tool_output_schema(**top_level: dict[str, Any]) -> dict[str, Any]:
    """Build a permissive-but-typed object schema: envelope + tool-specific fields."""
    return {
        "type": "object",
        "properties": {**_BASE_PROPS, **top_level},
        "required": ["success"],
        "additionalProperties": True,
    }


SEARCH_GENES_SCHEMA = tool_output_schema(
    query=_STR, count=_INT, total=_INT, genes=_OBJ_ARRAY, truncated=_TRUNCATION
)
SEARCH_DISEASES_SCHEMA = tool_output_schema(
    query=_STR, count=_INT, total=_INT, diseases=_OBJ_ARRAY, truncated=_TRUNCATION
)
GENE_CURATIONS_SCHEMA = tool_output_schema(
    gene=_OBJ, count=_INT, total=_INT, diseases=_OBJ_ARRAY, truncated=_TRUNCATION
)
DISEASE_CURATIONS_SCHEMA = tool_output_schema(
    disease=_OBJ, count=_INT, total=_INT, genes=_OBJ_ARRAY, truncated=_TRUNCATION
)
GENES_CURATIONS_SCHEMA = tool_output_schema(
    received=_INT,
    requested=_INT,
    count=_INT,
    results=_OBJ_ARRAY,
    duplicates=_ARRAY,
    unresolved=_OBJ_ARRAY,
)
DISEASES_CURATIONS_SCHEMA = GENES_CURATIONS_SCHEMA
ASSERTION_SCHEMA = tool_output_schema(assertion=_OBJ, submissions=_SUBMISSIONS_ARRAY)
FIND_CURATIONS_SCHEMA = tool_output_schema(
    count=_INT, total=_INT, filters=_OBJ, results=_OBJ_ARRAY, truncated=_TRUNCATION
)
RESOLVE_SCHEMA = tool_output_schema(query=_STR, gene=_OBJ_OR_NULL, disease=_OBJ_OR_NULL)
LIST_SUBMITTERS_SCHEMA = tool_output_schema(count=_INT, submitters=_OBJ_ARRAY)
CAPABILITIES_SCHEMA = tool_output_schema(
    server=_STR,
    server_version=_STR,
    tools=_ARRAY,
    classifications=_OBJ_ARRAY,
    response_modes=_OBJ,
    capabilities_version=_STR,
    data=_OBJ,
)
DIAGNOSTICS_SCHEMA = tool_output_schema(
    server_version=_STR, capabilities_version=_STR, data=_OBJ, refresh=_OBJ, quota=_OBJ
)
