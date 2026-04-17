from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ct.schema.models import TableSchema


def extract_i18n_strings(
    rows: list[dict[str, Any]],
    schema: TableSchema,
    existing: dict | None = None,
) -> dict[str, dict]:
    """从解析数据中提取 i18n 字段，生成/更新 strings_source.json 格式的字典。

    返回格式:
    {
        "table.id.field": {
            "table": "item",
            "id": 1001,
            "field": "name",
            "text": "宝剑",
            "status": "new" | "translated" | "stale"
        }
    }
    """
    if not schema.has_i18n:
        return existing or {}

    result = dict(existing) if existing else {}
    i18n_field_names = [f.name for f in schema.i18n_fields]
    primary_key = schema.primary
    current_keys: set[str] = set()

    for row in rows:
        row_id = row.get(primary_key)
        if row_id is None:
            continue
        for field_name in i18n_field_names:
            key = f"{schema.table}.{row_id}.{field_name}"
            current_keys.add(key)
            text = row.get(field_name, "")
            if text is None:
                text = ""

            if key in result:
                old_entry = result[key]
                if old_entry["text"] != str(text):
                    # 源文本变化 → stale
                    result[key] = {
                        "table": schema.table,
                        "id": row_id,
                        "field": field_name,
                        "text": str(text),
                        "status": "stale",
                    }
                # 否则保持原状态
            else:
                result[key] = {
                    "table": schema.table,
                    "id": row_id,
                    "field": field_name,
                    "text": str(text),
                    "status": "new",
                }

    # 删除行时移除条目
    table_prefix = f"{schema.table}."
    to_remove = [
        k for k in result
        if k.startswith(table_prefix) and k not in current_keys
    ]
    for k in to_remove:
        del result[k]

    return result


def load_source_strings(i18n_dir: Path) -> dict:
    path = i18n_dir / "strings_source.json"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_source_strings(data: dict, i18n_dir: Path) -> None:
    i18n_dir.mkdir(parents=True, exist_ok=True)
    path = i18n_dir / "strings_source.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
