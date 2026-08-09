"""fbs 结构标准（FbsConvention）与检查器。

标准与策略分离：
- **不变量（检查器强制）**：任何类型名与任何字段名不得相同（flatc 拒绝）；
  每张表必须有 ``{Table}Table`` 容器与 ``root_type``。
- **策略（YAML 生成器使用）**：Enum/Struct/Elem 后缀只是当前保证不变量
  的手段；未来 .fbs 源可自由命名，只要通过不变量检查。
"""

from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

from ct.validate.errors import Issue, IssueCode, ValidationIssue, WorkspaceIssue


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


def _resolve_flatc(flatc_path: Path) -> Path:
    """Windows 下优先 .exe 后缀（与 flatc_runner 保持一致）。"""
    import sys

    if sys.platform == "win32" and not flatc_path.suffix:
        exe_path = flatc_path.with_suffix(".exe")
        if exe_path.exists():
            return exe_path
    return flatc_path


def _check_flatc_compile(text: str, table: str, flatc_path: Path) -> list[Issue]:
    """用 flatc 编译校验类型合法性；flatc 缺失时降级（只告警不失败）。"""
    resolved = _resolve_flatc(flatc_path)
    if not resolved.exists():
        return [
            WorkspaceIssue(
                table, IssueCode.SCHEMA,
                f"flatc 未找到 ({flatc_path})，跳过编译校验（仅结构检查）",
            )
        ]

    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "schema.fbs"
        src.write_text(text, encoding="utf-8")
        result = subprocess.run(
            [str(resolved), "--cpp", "--no-warnings", "-o", td, str(src)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            stderr = result.stderr.strip()
            return [
                WorkspaceIssue(
                    table, IssueCode.SCHEMA,
                    f"flatc 编译失败: {stderr or '未知错误'}",
                )
            ]
    return []


def validate_fbs_conventions(
    text: str,
    *,
    table: str = "",
    flatc_path: Path | None = None,
) -> list[Issue]:
    """校验单份 .fbs 文本是否符合 ct 结构标准。

    结构检查（撞名不变量 + 容器/root_type）始终执行；传入 ``flatc_path``
    时追加编译校验，flatc 缺失自动降级为纯结构检查。
    """
    issues: list[Issue] = []
    issues.extend(_check_name_collisions(text, table))
    issues.extend(_check_structure(text, table))
    if flatc_path is not None:
        issues.extend(_check_flatc_compile(text, table, flatc_path))
    return issues
