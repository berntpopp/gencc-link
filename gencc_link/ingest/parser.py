"""Streaming parser for the GenCC submissions TSV export.

The GenCC new-format export is plain tab-separated values with a header row that
must match :data:`gencc_link.constants.SUBMISSION_COLUMNS` exactly. Rows are
yielded lazily so the ~54k-row export never needs to be fully materialized.
"""

from __future__ import annotations

import csv
from collections.abc import Iterator
from pathlib import Path

from gencc_link.constants import SUBMISSION_COLUMNS
from gencc_link.exceptions import DownloadError


def validate_header(header: list[str]) -> None:
    """Validate a TSV header against the expected GenCC column contract.

    Args:
        header: The header fields parsed from the first TSV row.

    Raises:
        DownloadError: When the header does not match
            :data:`SUBMISSION_COLUMNS` exactly (order included).
    """
    if tuple(header) != SUBMISSION_COLUMNS:
        raise DownloadError(
            "GenCC export header does not match the expected schema. "
            f"Expected {len(SUBMISSION_COLUMNS)} columns "
            f"{SUBMISSION_COLUMNS!r}, got {len(header)} columns {tuple(header)!r}."
        )


def iter_submissions(path: Path) -> Iterator[dict[str, str | None]]:
    """Stream submission rows from a GenCC TSV export.

    The header is validated against :data:`SUBMISSION_COLUMNS`. Each data row is
    yielded as a dict keyed by the column names; empty strings become ``None``,
    and rows missing trailing fields are padded with ``None``.

    Args:
        path: Path to the TSV export file.

    Yields:
        One dict per data row, keyed by :data:`SUBMISSION_COLUMNS`.

    Raises:
        DownloadError: When the header is missing or does not match the schema.
    """
    n_columns = len(SUBMISSION_COLUMNS)
    with path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle, delimiter="\t")
        try:
            header = next(reader)
        except StopIteration as exc:
            raise DownloadError("GenCC export is empty (no header row).") from exc
        validate_header(header)
        for row in reader:
            if not row:
                continue
            # Tolerate rows with missing trailing fields by padding; drop extras.
            if len(row) < n_columns:
                row = row + [""] * (n_columns - len(row))
            elif len(row) > n_columns:
                row = row[:n_columns]
            yield {
                column: (value if value != "" else None)
                for column, value in zip(SUBMISSION_COLUMNS, row, strict=True)
            }
