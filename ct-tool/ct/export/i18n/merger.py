from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from ct.schema.models import TableSchema

logger = logging.getLogger(__name__)


def load_translation(i18n_dir: Path, lang: str) -> dict:
    path = i18n_dir / f"strings_{lang}.json"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def merge_translations(
    rows: list[dict[str, Any]],
    schema: TableSchema,
    lang: str,
    translations: dict,
    primary_lang: str,
) -> list[dict[str, Any]]:
    """将翻译合并到行数据中。缺失时回退主语言并 warning。"""
    if not schema.has_i18n:
        return rows

    i18n_field_names = [f.name for f in schema.i18n_fields]
    primary_key = schema.primary
    merged_rows = []

    for row in rows:
        new_row = dict(row)
        row_id = row.get(primary_key)
        for field_name in i18n_field_names:
            key = f"{schema.table}.{row_id}.{field_name}"
            if key in translations:
                entry = translations[key]
                translated = entry.get("text", "")
                if translated:
                    new_row[field_name] = translated
                    continue
            # 缺失翻译 → 回退主语言
            logger.warning(
                f"[{schema.table}] 第{row_id}行 {field_name}: "
                f"缺少 {lang} 翻译，使用 {primary_lang} 原文"
            )
        merged_rows.append(new_row)

    return merged_rows
