"""Gene identifier forms GenCC does not carry.

The GenCC export names a gene by HGNC id and symbol only. An Ensembl gene id or an NCBI
Gene id is therefore never a miss: it is a form this server cannot convert, answered with
the hgnc-link call that does.
"""

from __future__ import annotations

import re
from typing import Any

from gencc_link.exceptions import UnsupportedGeneIdError

_ENSEMBL_RE = re.compile(r"ENSG\d{11}(\.\d+)?", re.IGNORECASE)
_NCBI_RE = re.compile(r"(?:NCBI_?Gene|Entrez(?:Gene)?|GeneID):(\d+)", re.IGNORECASE)


def foreign_gene_converter(raw: str) -> dict[str, Any] | None:
    """The hgnc-link call that converts ``raw`` to a symbol; None for a form GenCC resolves."""
    text = raw.strip()
    if _ENSEMBL_RE.fullmatch(text):
        return {"tool": "hgnc_resolve_symbol", "arguments": {"query": text}}
    if match := _NCBI_RE.fullmatch(text):
        arguments = {"source": "entrez_id", "value": match.group(1)}
        return {"tool": "hgnc_resolve_gene_by_xref", "arguments": arguments}
    return None


def reject_foreign_gene_id(raw: str, field: str) -> None:
    """Raise :class:`UnsupportedGeneIdError` for a gene id form GenCC cannot convert."""
    converter = foreign_gene_converter(raw)
    if converter is not None:
        raise UnsupportedGeneIdError(field, converter)
