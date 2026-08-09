"""行级类型校验：主键唯一性 + 汇集字段值校验问题并填充定位。

字段值校验本身（标量 / 数组元素 / struct 子字段）集中在
``ct.schema.type_traits`` 注册表；本模块只负责把它与行列定位、
ValidationIssue 构造、主键唯一性检查组合。
"""

from __future__ import annotations

from typing import Any

from ct.excel.reader import leaf_column_map
from ct.schema.models import TableSchema
from ct.schema.type_traits import validate_field_value
from ct.validate.errors import IssueCode, ValidationIssue


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _dotted_value(row: dict, path: str) -> Any:
    """按 dotted path 取嵌套值（struct 叶子）。"""
    node: Any = row
    for part in path.split("."):
        if isinstance(node, dict):
            node = node.get(part)
        else:
            return None
    return node


def validate_table(
    rows: list[dict],
    schema: TableSchema,
    excel_rows: list[int] | None = None,
) -> list[ValidationIssue]:
    """Validate all rows of a parsed table against its schema.

    Performs two kinds of checks:
    1. Type validation — every field value conforms to its declared type.
    2. Primary key uniqueness — no duplicate primary keys.

    Args:
        rows: Parsed data rows (list of dicts keyed by field name).
        schema: The TableSchema describing the table.

    Returns:
        List of error message strings. Empty list means no errors.
    """
    errors: list[ValidationIssue] = []
    table_name = schema.table
    primary_key_name = schema.primary
    col_map = leaf_column_map(schema)

    # Track primary key values for uniqueness check.
    seen_pks: dict[Any, int] = {}  # pk_value -> first row number (1-based)

    for row_idx, row in enumerate(rows):
        row_num = row_idx + 1  # 1-based row number from data start
        excel_row = excel_rows[row_idx] if excel_rows is not None else None

        for field in schema.fields:
            value = row.get(field.name)
            for path, msg in validate_field_value(value, field):
                errors.append(
                    ValidationIssue(
                        table=table_name,
                        code=IssueCode.TYPE,
                        message=msg,
                        row_index=row_num,
                        excel_row=excel_row,
                        column=col_map.get(path, col_map.get(field.name)),
                        field=path,
                        value=_dotted_value(row, path),
                    )
                )

        # Primary key uniqueness.
        pk_value = row.get(primary_key_name)
        if pk_value is not None:
            if pk_value in seen_pks:
                errors.append(
                    ValidationIssue(
                        table_name,
                        IssueCode.DUPLICATE_PK,
                        f"主键值 {pk_value!r} 重复（首次出现在第{seen_pks[pk_value]}行）",
                        row_index=row_num,
                        excel_row=excel_row,
                        column=col_map.get(primary_key_name),
                        field=primary_key_name,
                        value=pk_value,
                    )
                )
            else:
                seen_pks[pk_value] = row_num

    return errors
