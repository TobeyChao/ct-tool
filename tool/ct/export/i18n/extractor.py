from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ct.cli_helpers.i18n_json import dump_source_file
from ct.schema.models import TableSchema


def extract_source_for_table(
    rows: list[dict[str, Any]],
    schema: TableSchema,
) -> dict[str, str]:
    """从解析后的行数据中提取主语言原文，返回 {"id.field": "text"} 扁平结构。

    无 i18n 字段时返回空 dict。
    """
    if not schema.has_i18n:
        return {}

    primary_key = schema.primary
    i18n_field_names = [f.name for f in schema.i18n_fields]
    out: dict[str, str] = {}

    for row in rows:
        row_id = row.get(primary_key)
        if row_id is None:
            continue
        for field_name in i18n_field_names:
            text = row.get(field_name, "")
            if text is None:
                text = ""
            key = f"{row_id}.{field_name}"
            out[key] = str(text)

    return out


def _source_path(i18n_dir: Path, table: str) -> Path:
    return i18n_dir / "source" / f"{table}.json"


def load_source_file(i18n_dir: Path, table: str) -> dict[str, str]:
    """读取 i18n/source/{table}.json，文件不存在时返回空 dict。"""
    path = _source_path(i18n_dir, table)
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_source_file(
    i18n_dir: Path,
    schema: TableSchema,
    data: dict[str, str],
) -> Path:
    """写出 source 文件，返回写入路径。"""
    path = _source_path(i18n_dir, schema.table)
    field_order = [f.name for f in schema.i18n_fields]
    dump_source_file(data, path, field_order)
    return path
