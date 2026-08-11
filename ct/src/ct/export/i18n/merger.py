from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from ct.schema.models import TableSchema

logger = logging.getLogger(__name__)


def load_translation(i18n_dir: Path, lang: str, table: str) -> dict[str, dict[str, Any]]:
    """读取 i18n/{lang}/{table}.json，文件不存在返回空 dict。"""
    path = i18n_dir / lang / f"{table}.json"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def merge_translations(
    rows: list[dict[str, Any]],
    schema: TableSchema,
    lang: str,
    translations: dict[str, dict[str, Any]],
    primary_lang: str,
) -> list[dict[str, Any]]:
    """将 lang 文件中的译文合并到行数据。

    仅当 entry.text 非空且 entry.confirmed=true 时使用译文。其余情况回退主语言并 warning。
    """
    if not schema.has_i18n:
        return rows

    i18n_field_names = [f.name for f in schema.i18n_fields]
    primary_key = schema.primary
    merged_rows: list[dict[str, Any]] = []

    for row in rows:
        new_row = dict(row)
        row_id = row.get(primary_key)
        for field_name in i18n_field_names:
            key = f"{row_id}.{field_name}"
            entry = translations.get(key)
            if entry is None:
                logger.warning(
                    f"[{schema.table}] 第{row_id}行 {field_name}: "
                    f"缺少 {lang} 翻译条目，使用 {primary_lang} 原文"
                )
                continue

            text = entry.get("text", "") or ""
            confirmed = bool(entry.get("confirmed", False))
            status = entry.get("status", "")

            if text and confirmed:
                new_row[field_name] = text
            else:
                logger.warning(
                    f"[{schema.table}] 第{row_id}行 {field_name}: "
                    f"{lang} 译文状态 {status or 'unknown'}，使用 {primary_lang} 原文"
                )
        merged_rows.append(new_row)

    return merged_rows
