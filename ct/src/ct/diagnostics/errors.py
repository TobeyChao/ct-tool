"""Dependency-neutral Issue/Location contracts.

Schema domain (and any lower layer) imports these diagnostics models without
depending on the validation package; validation builds on them for rendering.
This removes the schema→validate reverse coupling.
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
    """行级校验问题（携带 Excel 定位信息，供 CLI/Web 面板定位）。"""

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


def format_error(table: str, row: int, field: str, message: str) -> str:
    """Format a single validation error in a planner-friendly format."""
    return f"[{table}.xlsx] 第{row}行 {field}：{message}"


def report_errors(errors: Iterable[Issue], verbose: bool = False) -> None:
    """Print validation errors to stderr (legacy text preserved verbatim)."""
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
