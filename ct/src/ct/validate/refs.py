"""Cross-table reference validation for config tables."""

from __future__ import annotations

from typing import Any

from ct.excel.reader import leaf_column_map
from ct.schema.models import FieldDef, TableSchema
from ct.validate.errors import IssueCode, ValidationIssue


def _resolve_ref_target(ref: str) -> tuple[str, str]:
    """Parse a ref string like ``"Item.id"`` into ``("Item", "id")``.

    If no dot is present, assumes the target field is ``"id"``.
    """
    if "." in ref:
        table, field = ref.split(".", 1)
        return table, field
    return ref, "id"


def _collect_ref_values(
    value: Any,
    field: FieldDef,
) -> list[tuple[Any, str]]:
    """Extract values that need to be checked against a referenced table.

    Returns a list of ``(value, description)`` pairs where *description*
    indicates the position (e.g. array index) for error reporting.
    """
    if value is None:
        return []

    if field.type == "array" and isinstance(value, list):
        results = []
        for idx, elem in enumerate(value):
            if elem is not None:
                results.append((elem, f"数组第{idx + 1}个元素"))
        return results

    return [(value, "")]


def validate_refs(
    rows: list[dict],
    schema: TableSchema,
    id_sets: dict[str, set],
    excel_rows: list[int] | None = None,
) -> list[ValidationIssue]:
    """Validate cross-table references for all rows.

    For each field that declares a ``ref``, check that every value (or
    array element) exists in the referenced table's id set.

    Args:
        rows: Parsed data rows.
        schema: The TableSchema describing the table.
        id_sets: Mapping of ``table_name`` to its set of primary key values.
                 The caller is responsible for providing id sets in
                 topological order.

    Returns:
        List of formatted error message strings.
    """
    errors: list[ValidationIssue] = []
    table_name = schema.table
    col_map = leaf_column_map(schema)

    # Collect fields with refs.
    ref_fields: list[tuple[FieldDef, str, str]] = []  # (field, target_table, target_field)
    for field in schema.fields:
        if field.ref:
            target_table, target_field = _resolve_ref_target(field.ref)
            ref_fields.append((field, target_table, target_field))

    if not ref_fields:
        return errors

    for row_idx, row in enumerate(rows):
        row_num = row_idx + 1
        excel_row = excel_rows[row_idx] if excel_rows is not None else None

        for field, target_table, target_field in ref_fields:
            value = row.get(field.name)
            ref_values = _collect_ref_values(value, field)

            # Get the target id set.
            target_ids = id_sets.get(target_table)
            if target_ids is None:
                # Referenced table not loaded — report as error.
                errors.append(
                    ValidationIssue(
                        table_name,
                        IssueCode.REF,
                        f"引用表 {target_table} 的数据未加载，无法校验",
                        row_index=row_num,
                        excel_row=excel_row,
                        column=col_map.get(field.name),
                        field=field.name,
                        value=value,
                    )
                )
                continue

            for ref_val, position in ref_values:
                if ref_val not in target_ids:
                    detail = (
                        f"{position}值 {ref_val!r} "
                        if position
                        else f"值 {ref_val!r} "
                    )
                    errors.append(
                        ValidationIssue(
                            table_name,
                            IssueCode.REF,
                            f"{detail}在引用表 {target_table}.{target_field} 中不存在",
                            row_index=row_num,
                            excel_row=excel_row,
                            column=col_map.get(field.name),
                            field=field.name,
                            value=ref_val,
                        )
                    )

    return errors
