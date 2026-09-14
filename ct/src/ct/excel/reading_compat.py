"""Reading-compatibility gate: can this workbook be read as this layout?

Saving YAML no longer rebuilds Excel, so a workbook may still carry the layout of
an older schema. Reading it with the current layout would silently swap values
between columns (two same-typed fields), misread nested groups or drop expanded
vector slots. Before any data is interpreted, ``validate``/``export`` therefore
prove that:

1. a trusted layout manifest exists for the table,
2. the manifest's column mapping still equals the current reading layout
   (stable path, type expression, depth and header rows), and
3. the real workbook's *managed header cells* say the same thing.

Only the reading structure is compared: field names, leaf type annotations, row
counts and column positions. Comments, header colours and other presentation
never block reading (they only show up as template drift), and unmanaged trailing
columns stay a warning, exactly as before.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

from ct.diagnostics.errors import Issue, IssueCode, ValidationIssue
from ct.excel.canonical_template import segments_for
from ct.excel.layout import Layout
from ct.excel.layout_manifest import LayoutManifest


@dataclass(frozen=True)
class ReadingCompatibility:
    """Outcome of the gate for one table."""

    ok: bool
    issues: tuple[Issue, ...] = ()
    reason: str = ""


def expected_header_grid(layout: Layout) -> dict[tuple[int, int], str]:
    """``(row, column) -> text`` for every managed header cell the template writes.

    Mirrors ``canonical_template._write_header_rows``: paired comment/field rows
    per depth, one anchor cell per group (merged cells keep their value on the
    first column), ``#n`` slot nodes annotated with the leaf type.
    """
    max_depth = layout.header_rows // 2
    grid: dict[tuple[int, int], str] = {}
    for depth in range(1, max_depth + 1):
        grouped: dict[tuple[str, ...], list[Any]] = {}
        for column in layout.columns:
            parts = segments_for(layout.table_id, column.stable_path)
            if len(parts) < depth:
                continue
            grouped.setdefault(tuple(parts[:depth]), []).append(column)
        for parts, cols in grouped.items():
            anchor = min(column.index for column in cols)
            segment = parts[-1]
            annotation = cols[0].field_annotation or cols[0].annotation
            if depth > 1 and segment.startswith("#"):
                annotation = cols[0].type_text
            grid[(depth * 2, anchor)] = f"{segment}\n{annotation}"
    return grid


def _cell_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    return text if text.strip() else ""


def read_header_grid(excel_path: Path, header_rows: int) -> dict[tuple[int, int], str]:
    """Read the workbook's field rows (comment rows carry prose, not structure)."""
    workbook = load_workbook(str(excel_path), read_only=True, data_only=True)
    try:
        sheet = workbook.active
        grid: dict[tuple[int, int], str] = {}
        if sheet is None:
            return grid
        for row_index, row in enumerate(
            sheet.iter_rows(min_row=1, max_row=header_rows, values_only=True), start=1
        ):
            if row_index % 2:  # comment row: presentation only
                continue
            for column_index, value in enumerate(row, start=1):
                text = _cell_text(value)
                if text:
                    grid[(row_index, column_index)] = text
        return grid
    finally:
        workbook.close()


def _manifest_signature(manifest: LayoutManifest) -> list[tuple[int, str, str, int]]:
    return [
        (
            int(column.get("index", 0)),
            str(column.get("stablePath", "")),
            str(column.get("typeExpr", "")),
            int(column.get("depth", 0)),
        )
        for column in manifest.columns
    ]


def _layout_signature(layout: Layout) -> list[tuple[int, str, str, int]]:
    return [
        (column.index, column.stable_path, column.type_text, column.depth)
        for column in layout.columns
    ]


def _blocker(table: str, message: str) -> Issue:
    """结构级阻断项：定位（列/行）写在 message 里，不带单元格值语义。"""
    return ValidationIssue(table, IssueCode.TEMPLATE, message)


def check_reading_compatibility(
    table: str,
    layout: Layout,
    excel_path: Path,
    *,
    manifest: LayoutManifest | None,
) -> ReadingCompatibility:
    """Decide whether ``excel_path`` can be read as ``layout``."""
    if manifest is None:
        return ReadingCompatibility(
            ok=False,
            issues=(
                _blocker(
                    table,
                    "缺少布局 manifest，无法确认 Excel 与当前 schema 的读取布局兼容。"
                    f"该表还没有工作簿时，运行 `ct gen-template --table {table}` 生成空模板；"
                    "已有旧工作簿时，工具不会在缺少 manifest 的情况下搬移数据："
                    "请先备份并删除旧工作簿，再生成空模板并重新录入（见 ct/docs/schema-save-migration.md）。",
                ),
            ),
            reason="manifest-missing",
        )

    if manifest.header_rows != layout.header_rows:
        return ReadingCompatibility(
            ok=False,
            issues=(
                _blocker(
                    table,
                    f"表头行数不一致（manifest {manifest.header_rows} 行 vs 当前布局 "
                    f"{layout.header_rows} 行），数据起始行无法确定；请更新模板",
                ),
            ),
            reason="header-rows",
        )

    expected_columns = _layout_signature(layout)
    manifest_columns = _manifest_signature(manifest)
    if manifest_columns != expected_columns:
        detail = "列数与当前布局不同"
        for expected, actual in zip(expected_columns, manifest_columns):
            if expected != actual:
                detail = (
                    f"第 {get_column_letter(expected[0])} 列：manifest 记录 "
                    f"{actual[1]}（{actual[2]}，深度 {actual[3]}），当前布局为 "
                    f"{expected[1]}（{expected[2]}，深度 {expected[3]}）"
                )
                break
        else:
            extra = manifest_columns[len(expected_columns):] or expected_columns[len(manifest_columns):]
            if extra:
                detail = f"第 {get_column_letter(extra[0][0])} 列起托管列数量不同"
        return ReadingCompatibility(
            ok=False,
            issues=(
                _blocker(
                    table,
                    f"布局 manifest 与当前 schema 的读取结构不一致：{detail}；"
                    "保存 YAML 不会重建模板，请先更新模板再校验/导出",
                ),
            ),
            reason="manifest-layout",
        )

    expected_grid = expected_header_grid(layout)
    actual_grid = read_header_grid(excel_path, layout.header_rows)

    for (row, column), expected_text in sorted(expected_grid.items()):
        actual_text = actual_grid.get((row, column))
        if actual_text == expected_text:
            continue
        location = f"{get_column_letter(column)}{row}"
        if actual_text is None:
            detail = f"缺少表头单元格 {location}（期望 {expected_text!r}）"
        else:
            detail = f"表头单元格 {location} 为 {actual_text!r}，期望 {expected_text!r}"
        return ReadingCompatibility(
            ok=False,
            issues=(
                _blocker(
                    table,
                    f"工作簿受管表头与当前布局不符：{detail}；"
                    "不按当前布局解释数据，请更新模板",
                ),
            ),
            reason="workbook-headers",
        )

    managed_columns = {column.index for column in layout.columns}
    unexpected = [
        (row, column, text)
        for (row, column), text in sorted(actual_grid.items())
        if column not in managed_columns
    ]
    # 额外未受管尾列维持既有警告语义：不进 issues，也不阻止读取。
    del unexpected
    return ReadingCompatibility(ok=True)
