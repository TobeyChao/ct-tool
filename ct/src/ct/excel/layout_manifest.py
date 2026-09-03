"""``cache/template_layouts/<table>.json`` sidecar manifests.

The Excel template keeps only lightweight Custom Document Properties; the
full stable column-path mapping lives here so data migration never guesses
from raw column positions.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ct.excel.layout import Column, Layout

MANIFEST_FORMAT = "template-layout-v4/1"


@dataclass(frozen=True)
class LayoutManifest:
    format: str = MANIFEST_FORMAT
    layout_revision: int = 1
    schema_hash: str = ""
    header_rows: int = 2
    columns: tuple[dict[str, Any], ...] = ()

    @classmethod
    def from_layout(
        cls,
        layout: Layout,
        *,
        previous_revision: int = 0,
    ) -> LayoutManifest:
        return cls(
            layout_revision=previous_revision + 1,
            schema_hash=layout.schema_hash,
            header_rows=layout.header_rows,
            columns=tuple(
                {
                    "index": column.index,
                    "stablePath": column.stable_path,
                    "typeExpr": column.type_text,
                    "annotation": column.annotation,
                    "leaf": column.leaf,
                    "depth": column.depth,
                }
                | ({"groupIndex": column.group_index} if column.group_index is not None else {})
                for column in layout.columns
            ),
        )

    @classmethod
    def parse(cls, data: dict[str, Any]) -> LayoutManifest:
        return cls(
            format=str(data.get("format", "")),
            layout_revision=int(data.get("layout_revision", 0)),
            schema_hash=str(data.get("schema_hash", "")),
            header_rows=int(data.get("header_rows", 2)),
            columns=tuple(
                dict(column) for column in data.get("columns", [])
            ),
        )


def _manifest_path(cache_dir: Path, table: str) -> Path:
    return cache_dir / "template_layouts" / f"{table}.json"


def load_manifest(cache_dir: Path, table: str) -> LayoutManifest | None:
    """Return the manifest, or ``None`` for missing/corrupt/incompatible files."""
    path = _manifest_path(cache_dir, table)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or data.get("format") != MANIFEST_FORMAT:
        return None
    try:
        return LayoutManifest.parse(data)
    except (TypeError, ValueError, KeyError):
        return None


def save_manifest(cache_dir: Path, table: str, manifest: LayoutManifest) -> Path:
    path = _manifest_path(cache_dir, table)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "format": manifest.format,
                "layout_revision": manifest.layout_revision,
                "schema_hash": manifest.schema_hash,
                "header_rows": manifest.header_rows,
                "columns": list(manifest.columns),
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return path
