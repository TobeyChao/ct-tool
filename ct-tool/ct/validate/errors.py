"""Error formatting helpers for config table validation."""

from __future__ import annotations

import sys
import traceback


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


def report_errors(errors: list[str], verbose: bool = False) -> None:
    """Print validation errors to stderr.

    Args:
        errors: List of formatted error strings.
        verbose: If True, include the current traceback for debugging.
    """
    if not errors:
        return

    print(f"\n验证发现 {len(errors)} 个错误：", file=sys.stderr)
    for err in errors:
        print(f"  ✗ {err}", file=sys.stderr)

    if verbose:
        print("\n--- traceback (--verbose) ---", file=sys.stderr)
        traceback.print_stack(file=sys.stderr)

    print("", file=sys.stderr)
