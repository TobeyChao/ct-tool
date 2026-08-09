from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ct.export.i18n.io import dump_source_file
from ct.schema.models import TableSchema


def _pk_value_matches_type(value: Any, field: FieldDef) -> bool:
    """主键值是否与声明的字段类型一致。

    reader 的类型转换失败（如 int32 填 "abc"）会返回原值（宽容契约，
    由校验器负责判定）；这里跳过类型不符的主键，避免垃圾 source key
    混入 i18n 文件。
    """
    if field.type in ("int32", "int64"):
        return isinstance(value, int) and not isinstance(value, bool)
    if field.type in ("float", "double"):
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if field.type == "bool":
        return isinstance(value, bool)
    if field.type == "string":
        return isinstance(value, str)
    return True


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
    pk_field = schema.primary_field
    i18n_field_names = [f.name for f in schema.i18n_fields]
    out: dict[str, str] = {}

    for row in rows:
        row_id = row.get(primary_key)
        if row_id is None:
            continue
        if not _pk_value_matches_type(row_id, pk_field):
            # 主键 coercion 失败（类型不对）保持原值：跳过该行，
            # 不产生 "abc.Name" 之类的垃圾 source key。
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
