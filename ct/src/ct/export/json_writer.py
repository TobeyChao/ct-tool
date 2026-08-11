from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ct.schema.models import TableSchema
from ct.schema.type_traits import TYPE_TRAITS


def serialize_row(row: dict[str, Any], schema: TableSchema) -> dict[str, Any]:
    """序列化单行数据为 JSON 格式。"""
    result: dict[str, Any] = {}
    for field in schema.fields:
        value = row.get(field.name)
        result[field.name] = TYPE_TRAITS[field.type].json_value(field, value)
    return result


def write_json(
    rows: list[dict[str, Any]],
    schema: TableSchema,
    lang: str,
    output_dir: Path,
) -> Path:
    """将行数据序列化为 JSON 文件。

    输出格式: { "items": [ {...}, {...} ] }
    文件路径: output/json/{table}_{lang}.json
    """
    json_dir = output_dir / "json"
    json_dir.mkdir(parents=True, exist_ok=True)

    root_key = schema.resolved_json_key
    items = [serialize_row(row, schema) for row in rows]
    data = {root_key: items}

    out_path = json_dir / f"{schema.table}_{lang}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        lines = ",\n    ".join(
            json.dumps(item, ensure_ascii=False) for item in items
        )
        f.write(f'{{\n  "{root_key}": [\n    {lines}\n  ]\n}}')

    return out_path
