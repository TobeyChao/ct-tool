"""Canonical JSON export for  Table resources.

Rows produced by the canonical reader already have the correct shape
(enum -> string identifier, record -> object, vector -> array,
``vector<Record>`` -> object array); this writer only serializes them under
the table's JSON root key, so the Excel input layout never leaks into JSON.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ct.schema.resources import TableResource


def table_json_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return rows in a JSON-safe form (values are already JSON primitives)."""
    return rows


def serialize_table_json(rows: list[dict[str, Any]], table: TableResource) -> str:
    root_key = table.json_key or f"{table.table}s"
    return json.dumps(
        {root_key: rows},
        ensure_ascii=False,
        indent=2,
    )


def write_canonical_json(
    rows: list[dict[str, Any]],
    table: TableResource,
    out_path: Path,
) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(serialize_table_json(rows, table), encoding="utf-8")
    return out_path
