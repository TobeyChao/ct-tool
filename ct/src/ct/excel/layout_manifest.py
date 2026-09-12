"""``excel/layout_manifests/<table>.json`` sidecar manifests.

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

MANIFEST_FORMAT = "template-layout/2"


@dataclass(frozen=True)
class LayoutManifest:
    format: str = MANIFEST_FORMAT
    layout_revision: int = 1
    schema_hash: str = ""
    header_rows: int = 2
    columns: tuple[dict[str, Any], ...] = ()
    nodes: tuple[dict[str, Any], ...] = ()
    # ---- 定宽布局（uniform）----
    # 导出期决定：字段填充率 >= 阈值的表开定宽，所有行共享同一 vtable，
    # 于是 slot→offset 是表级常量，生成器可直接发射字面量偏移（无偏移表间接层）。
    uniform: bool = False
    fill_rate: float = 0.0
    # slot -> 行内字节偏移（仅 uniform=True 时有意义）
    slot_offsets: tuple[tuple[int, int], ...] = ()

    @classmethod
    def from_layout(
        cls,
        layout: Layout,
        *,
        previous_revision: int = 0,
        layout_info: dict[str, Any] | None = None,
    ) -> LayoutManifest:
        info = layout_info or {}
        return cls(
            layout_revision=previous_revision + 1,
            uniform=bool(info.get("uniform", False)),
            fill_rate=float(info.get("fill_rate", 0.0)),
            slot_offsets=tuple(
                sorted((int(k), int(v)) for k, v in (info.get("slot_offsets") or {}).items())
            ),
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
            nodes=tuple(
                {
                    "stablePath": node.stable_path,
                    "displayName": node.display_name,
                    "annotation": node.annotation,
                    "comment": node.comment,
                    "kind": node.kind,
                    "depth": node.depth,
                    "children": list(node.children),
                    "slotIndex": node.slot_index,
                    "leafStart": node.leaf_start,
                    "leafEnd": node.leaf_end,
                }
                for node in layout.nodes
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
            nodes=tuple(dict(node) for node in data.get("nodes", [])),
            uniform=bool(data.get("uniform", False)),
            fill_rate=float(data.get("fill_rate", 0.0)),
            slot_offsets=tuple(
                (int(pair[0]), int(pair[1]))
                for pair in data.get("slot_offsets", [])
                if isinstance(pair, (list, tuple)) and len(pair) == 2
            ),
        )

    @property
    def slot_offset_map(self) -> dict[int, int]:
        """slot -> 行内偏移（uniform 表专用）。"""
        return dict(self.slot_offsets)


def _manifest_path(manifest_dir: Path, table: str) -> Path:
    return manifest_dir / f"{table}.json"


def load_manifest(
    manifest_dir: Path, table: str, *, data: bytes | None = None
) -> LayoutManifest | None:
    """Return the manifest, or ``None`` for missing/corrupt/incompatible files.

    ``data`` 给定时从**捕获到的字节**解析，不再读盘。
    """
    path = _manifest_path(manifest_dir, table)
    if data is None:
        if not path.exists():
            return None
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError:
            return None
    else:
        raw = data.decode("utf-8", errors="replace")
    try:
        data_obj = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data_obj, dict) or data_obj.get("format") != MANIFEST_FORMAT:
        return None
    try:
        return LayoutManifest.parse(data_obj)
    except (TypeError, ValueError, KeyError):
        return None


def manifest_payload(manifest: LayoutManifest) -> str:
    """序列化 manifest（发布阶段据此收集 payload，不再直接落盘）。"""
    return (
        json.dumps(
            {
                "format": manifest.format,
                "layout_revision": manifest.layout_revision,
                "schema_hash": manifest.schema_hash,
                "header_rows": manifest.header_rows,
                "columns": list(manifest.columns),
                "nodes": list(manifest.nodes),
                "uniform": manifest.uniform,
                "fill_rate": round(manifest.fill_rate, 6),
                "slot_offsets": [list(pair) for pair in manifest.slot_offsets],
            },
            ensure_ascii=False,
            sort_keys=True,
            indent=4,
        )
        + "\n"
    )


def save_manifest(manifest_dir: Path, table: str, manifest: LayoutManifest) -> Path:
    path = _manifest_path(manifest_dir, table)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(manifest_payload(manifest), encoding="utf-8")
    return path
