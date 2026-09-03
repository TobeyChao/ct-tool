"""fbs 结构标准（FbsConvention）与检查器。

标准与策略分离：
- **不变量（检查器强制）**：任何类型名与任何字段名不得相同（flatc 拒绝）；
  每张表必须有 ``{Table}Table`` 容器与 ``root_type``。
- **策略（YAML 生成器使用）**：Enum/Struct/Elem 后缀只是当前保证不变量
  的手段；未来 .fbs 源可自由命名，只要通过不变量检查。
"""

from __future__ import annotations

import re
from pathlib import Path

from ct.diagnostics.errors import Issue, IssueCode, ValidationIssue, WorkspaceIssue


class FbsConvention:
    """ct 的 fbs 结构规范：类型映射与命名策略常量。"""

    # Schema 类型 → FlatBuffers 类型
    TYPE_MAP: dict[str, str] = {
        "int32": "int32",
        "int64": "int64",
        "float": "float32",
        "double": "float64",
        "bool": "bool",
        "string": "string",
    }

    # 命名策略（YAML 生成器当前采用，保证不变量）
    ENUM_SUFFIX = "Enum"
    STRUCT_SUFFIX = "Struct"
    ELEM_SUFFIX = "Elem"
    CONTAINER_SUFFIX = "Table"

    # 结构规范
    I18N_ENTRY_SUFFIX = "I18nEntry"
    I18N_TABLE_SUFFIX = "I18nTable"
    BUNDLE_TABLE = "BundledTable"
    BUNDLE_ROOT = "DataBundle"


_TYPE_DECL = re.compile(r"^(?:enum|table)\s+([A-Za-z_][A-Za-z0-9_]*)", re.M)
_FIELD_LINE = re.compile(r"^\s+([A-Za-z_][A-Za-z0-9_]*)\s*:", re.M)
_ROOT_TYPE = re.compile(r"^root_type\s+([A-Za-z_][A-Za-z0-9_]*)\s*;", re.M)


def _check_name_collisions(text: str, table: str) -> list[Issue]:
    """不变量：类型名与字段名不得相同。"""
    type_names = set(_TYPE_DECL.findall(text))
    field_names = set(_FIELD_LINE.findall(text))
    collisions = sorted(type_names & field_names)
    if not collisions:
        return []
    return [
        ValidationIssue(
            table=table,
            code=IssueCode.SCHEMA,
            message=(
                f"类型名与字段名冲突: {', '.join(collisions)}"
                "（flatc 拒绝字段名 == 类型名，请改名或换后缀策略）"
            ),
            field=collisions[0],
        )
    ]


def _check_structure(text: str, table: str) -> list[Issue]:
    """结构规范：至少一个 table、root_type 必须指向已声明表、花括号配平。"""
    issues: list[Issue] = []
    table_names = {
        name
        for name in _TYPE_DECL.findall(text)
        if re.search(rf"^table\s+{re.escape(name)}\b", text, re.M)
    }

    if not table_names:
        issues.append(
            WorkspaceIssue(table, IssueCode.SCHEMA, "未声明任何 table")
        )

    root_matches = _ROOT_TYPE.findall(text)
    if len(root_matches) != 1:
        issues.append(
            WorkspaceIssue(
                table, IssueCode.SCHEMA,
                f"必须且只能有一个 root_type（当前 {len(root_matches)} 个）",
            )
        )
    elif root_matches[0] not in table_names:
        issues.append(
            WorkspaceIssue(
                table, IssueCode.SCHEMA,
                f"root_type {root_matches[0]} 未声明为 table",
            )
        )

    if text.count("{") != text.count("}"):
        issues.append(
            WorkspaceIssue(table, IssueCode.SCHEMA, "花括号不配平")
        )

    return issues


def validate_fbs_conventions(
    text: str,
    *,
    table: str = "",
) -> list[Issue]:
    """校验单份 .fbs 文本是否符合 ct 结构标准（撞名不变量 + 容器/root_type）。"""
    issues: list[Issue] = []
    issues.extend(_check_name_collisions(text, table))
    issues.extend(_check_structure(text, table))
    return issues
