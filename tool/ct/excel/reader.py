"""Read Excel data files using openpyxl read_only mode and parse rows
according to a TableSchema definition.

Key concepts:
- Header rows are determined by ``schema.header_rows`` (max_nesting_depth + 1).
- Struct fields are expanded into multiple contiguous columns.  A struct with
  two sub-fields occupies two columns; nested structs expand recursively.
- Array fields occupy a single cell whose value is split by
  ``field.separator``.
- Empty rows (all *None*) are silently skipped.
- Extra columns beyond those declared in the schema trigger a warning.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from ct.schema.models import FieldDef, TableSchema
from ct.schema.type_traits import TYPE_TRAITS, validate_field_value
from ct.validate.errors import IssueCode, ValidationIssue

logger = logging.getLogger(__name__)


def _flatten_fields(fields: list[FieldDef]) -> list[tuple[str, FieldDef]]:
    """Return a flat list of ``(dotted_path, leaf_field)`` tuples.

    For example, a struct ``drop_range`` with sub-fields ``min`` and ``max``
    yields::

        [("drop_range.min", <FieldDef min>),
         ("drop_range.max", <FieldDef max>)]

    Non-struct fields simply yield ``(name, field)``.
    """
    result: list[tuple[str, FieldDef]] = []
    for f in fields:
        if f.type == "struct" and f.fields:
            for sub_path, sub_field in _flatten_fields(f.fields):
                result.append((f"{f.name}.{sub_path}", sub_field))
        else:
            result.append((f.name, f))
    return result


def leaf_column_map(schema: TableSchema) -> dict[str, int]:
    """返回 ``{dotted_path: 0-based 列索引}``（struct 展开后按叶子列计）。"""
    result: dict[str, int] = {}
    col = 0
    for path, leaf in _flatten_fields(schema.fields):
        result[path] = col
        col += leaf.column_span()
    return result


# Row parsing
# ---------------------------------------------------------------------------

def _build_nested_dict(flat: dict[str, Any]) -> dict[str, Any]:
    """Convert a flat dict with dotted keys into a nested dict.

    >>> _build_nested_dict({"drop_range.min": 10, "drop_range.max": 20})
    {"drop_range": {"min": 10, "max": 20}}
    """
    result: dict[str, Any] = {}
    for dotted_key, val in flat.items():
        parts = dotted_key.split(".")
        d = result
        for part in parts[:-1]:
            d = d.setdefault(part, {})
        d[parts[-1]] = val
    return result


def _parse_row(
    cells: tuple[Any, ...],
    flat_columns: list[tuple[str, FieldDef]],
    top_fields: list[FieldDef],
    *,
    schema: TableSchema,
    excel_row: int,
    row_index: int,
) -> tuple[dict[str, Any] | None, list[ValidationIssue]]:
    """Parse a single data row into a dict + 解析期问题列表。

    Returns ``(None, [])`` if the row is entirely empty. 标量单元格 coerce
    失败（显式 ``ok=False``）时产出带行列定位的 issue；数组元素失败
    留给校验器报带元素序号的精确消息（见 type_traits._coerce_array）。
    """
    # Check if the row is empty (all None / empty string)
    if all(c is None or (isinstance(c, str) and not c.strip()) for c in cells):
        return None, []

    flat: dict[str, Any] = {}
    issues: list[ValidationIssue] = []
    for col_idx, (dotted_path, field) in enumerate(flat_columns):
        if col_idx >= len(cells):
            raw = None
        else:
            raw = cells[col_idx]

        # Determine if this is an array field (arrays are always top-level,
        # never inside structs, per model validation).
        # We check against the top-level field name.
        top_name = dotted_path.split(".")[0]
        top_field = next((f for f in top_fields if f.name == top_name), None)

        if top_field and top_field.type == "array" and "." not in dotted_path:
            coerced, _ok = TYPE_TRAITS["array"].coerce(top_field, raw)
            flat[dotted_path] = coerced
        else:
            coerced, ok = TYPE_TRAITS[field.type].coerce(field, raw)
            flat[dotted_path] = coerced
            if not ok:
                msgs = validate_field_value(raw, field)
                msg = msgs[0][1] if msgs else f"期望 {field.type} 类型"
                issues.append(
                    ValidationIssue(
                        table=schema.table,
                        code=IssueCode.TYPE,
                        message=msg,
                        row_index=row_index,
                        excel_row=excel_row,
                        column=col_idx,
                        field=dotted_path,
                        value=raw,
                    )
                )

    return _build_nested_dict(flat), issues


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ParsedRows:
    """解析结果：数据行 + Excel 绝对行号 + 解析期问题列表。

    数据与定位信息分离，避免行号泄漏进 JSON / Binary 等导出产物。
    ``issues`` 是 reader 在标量 coerce 失败时直接产出的行列定位问题
    （契约显式化，替代"返回原值、由下游猜测"）；消费方（校验、i18n
    extractor）据此跳过坏行，不必重新推导类型。
    """

    rows: list[dict[str, Any]]
    excel_rows: list[int]
    issues: list[ValidationIssue] = field(default_factory=list)


def read_excel(excel_path: Path, schema: TableSchema) -> ParsedRows:
    """Read an Excel file and return parsed data rows.

    Parameters
    ----------
    excel_path:
        Path to the ``.xlsx`` file.
    schema:
        The ``TableSchema`` describing the table structure.

    Returns
    -------
    ParsedRows
        ``rows``: 与旧返回完全一致的数据行（struct 为嵌套 dict）；
        ``excel_rows``: 与 ``rows`` 平行的 Excel 绝对行号（空行被跳过，
        但真实行号保留）。
    """
    wb = load_workbook(str(excel_path), read_only=True, data_only=True)
    try:
        ws = wb.active
        if ws is None:
            logger.warning("工作簿 %s 没有活动工作表", excel_path)
            return ParsedRows([], [])

        header_row_count = schema.header_rows
        flat_columns = _flatten_fields(schema.fields)
        expected_col_count = len(flat_columns)

        rows: list[dict[str, Any]] = []
        excel_rows: list[int] = []
        issues: list[ValidationIssue] = []
        for row_idx, row in enumerate(ws.iter_rows(values_only=True), start=1):
            # Skip header rows
            if row_idx <= header_row_count:
                # On the last header row, check for extra columns
                if row_idx == header_row_count:
                    actual_cols = len(row)
                    if actual_cols > expected_col_count:
                        extra = actual_cols - expected_col_count
                        logger.warning(
                            "表 %s (%s): 发现 %d 个多余列（schema 定义 %d 列，"
                            "Excel 有 %d 列）",
                            schema.table, excel_path.name,
                            extra, expected_col_count, actual_cols,
                        )
                continue

            parsed, row_issues = _parse_row(
                row,
                flat_columns,
                schema.fields,
                schema=schema,
                excel_row=row_idx,
                row_index=len(rows) + 1,
            )
            if parsed is not None:
                rows.append(parsed)
                excel_rows.append(row_idx)
                issues.extend(row_issues)

        return ParsedRows(rows, excel_rows, issues)
    finally:
        wb.close()
