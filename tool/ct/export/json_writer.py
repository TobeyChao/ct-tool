from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ct.schema.models import TableSchema


def serialize_row(row: dict[str, Any], schema: TableSchema, exclude_server_only: bool = False) -> dict[str, Any]:
    """序列化单行数据为 JSON 格式。"""
    result: dict[str, Any] = {}
    for field in schema.fields:
        if exclude_server_only and field.server_only:
            continue
        value = row.get(field.name)
        if field.type == "enum":
            result[field.name] = str(value) if value is not None else None
        elif field.type == "struct" and field.fields:
            if isinstance(value, dict):
                result[field.name] = value
            else:
                result[field.name] = None
        elif field.type == "array":
            if isinstance(value, list):
                if field.element == "enum":
                    result[field.name] = [str(v) for v in value]
                else:
                    result[field.name] = value
            else:
                result[field.name] = []
        else:
            result[field.name] = value
    return result


def write_json(
    rows: list[dict[str, Any]],
    schema: TableSchema,
    lang: str,
    output_dir: Path,
    exclude_server_only: bool = False,
) -> Path:
    """将行数据序列化为 JSON 文件。

    输出格式: { "items": [ {...}, {...} ] }
    文件路径: output/json/{table}_{lang}.json
    """
    json_dir = output_dir / "json"
    json_dir.mkdir(parents=True, exist_ok=True)

    root_key = schema.resolved_json_key
    items = [serialize_row(row, schema, exclude_server_only) for row in rows]
    data = {root_key: items}

    out_path = json_dir / f"{schema.table}_{lang}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        lines = ",\n    ".join(
            json.dumps(item, ensure_ascii=False) for item in items
        )
        f.write(f'{{\n  "{root_key}": [\n    {lines}\n  ]\n}}')

    return out_path
