"""结构化校验问题模型 + 渲染（自 `ct.diagnostics.errors` 重新导出）。

为保持既有调用方兼容，本模块保留为薄转发层；领域契约已下沉到
``ct.diagnostics.errors``，schema 域不再依赖本包。
"""

from __future__ import annotations

import sys
import traceback
from typing import Iterable

from ct.diagnostics.errors import (  # noqa: F401
    Issue,
    IssueCode,
    ValidationIssue,
    WorkspaceIssue,
    format_error,
)

__all__ = [
    "Issue",
    "IssueCode",
    "ValidationIssue",
    "WorkspaceIssue",
    "format_error",
    "report_errors",
]


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
