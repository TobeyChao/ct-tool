"""结构化校验问题模型 + 渲染（以对象取代基本类型 7.3）。

校验结果不再以字符串传递：`ValidationIssue` 携带表名/行号/列/当前值等
结构信息；`render()` 复现旧版文本格式，保证 CLI 输出逐字一致。
"""

from __future__ import annotations

import sys
import traceback
from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable

from openpyxl.utils import get_column_letter


class IssueCode(str, Enum):
    TYPE = "type"
    REF = "ref"
    DUPLICATE_PK = "duplicate_pk"
    SCHEMA = "schema"
    TEMPLATE = "template"
    WORKSPACE = "workspace"


@dataclass(frozen=True)
class Issue:
    """问题基类：表名 + 分类 + 详情。"""

    table: str
    code: IssueCode
    message: str

    def render(self) -> str:
        return self.message

    def to_dict(self) -> dict[str, Any]:
        return {
            "table": self.table,
            "code": self.code.value,
            "message": self.message,
        }


@dataclass(frozen=True)
class ValidationIssue(Issue):
    """行级校验问题。

    - ``row_index``：数据行序号（1-based，现有 CLI 文本使用的行号）；
    - ``excel_row``：Excel 绝对行号（供未来面板定位，本次只建模不消费）；
    - ``column``：0-based 列索引（struct 展开后按叶子列计）。
    """

    row_index: int | None = None
    excel_row: int | None = None
    column: int | None = None
    field: str = ""
    value: Any = None

    def render(self) -> str:
        if self.excel_row is not None and self.column is not None:
            letter = get_column_letter(self.column + 1)
            return (
                f"[{self.table}.xlsx] Excel 第{self.excel_row}行 · "
                f"列{letter} ({self.field}) · 当前值 {self.value!r} → {self.message}"
            )
        # 回退：无绝对定位信息时使用旧格式（相对数据行号）
        return format_error(self.table, self.row_index, self.field, self.message)

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data.update(
            {
                "row_index": self.row_index,
                "excel_row": self.excel_row,
                "column": self.column,
                "field": self.field,
                "value": self.value,
            }
        )
        return data


@dataclass(frozen=True)
class WorkspaceIssue(Issue):
    """项目级问题：缺文件、schema 加载错误等。"""

    detail: str = ""


def format_error(table: str, row: int, field: str, message: str) -> str:
    """Format a single validation error in a planner-friendly format.

    Args:
        table: Table name (without .xlsx extension).
        row: 1-based row number (from data start, after header).
        field: Field name where the error occurred.
        message: Detailed error description.

    Returns:
        Formatted error string like ``[表名.xlsx] 第N行 字段名：详细信息``.
    """
    return f"[{table}.xlsx] 第{row}行 {field}：{message}"


def report_errors(errors: Iterable[Issue], verbose: bool = False) -> None:
    """Print validation errors to stderr.

    Args:
        errors: Issues to render (``render()`` keeps legacy text identical).
        verbose: If True, include the current traceback for debugging.
    """
    errs = list(errors)
    if not errs:
        return

    print(f"\n验证发现 {len(errs)} 个错误：", file=sys.stderr)
    for err in errs:
        print(f"  ✗ {err.render()}", file=sys.stderr)

    if verbose:
        print("\n--- traceback (--verbose) ---", file=sys.stderr)
        traceback.print_stack(file=sys.stderr)

    print("", file=sys.stderr)
