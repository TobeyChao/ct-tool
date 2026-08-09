"""Type validation for parsed config table rows."""

from __future__ import annotations

from typing import Any

from ct.excel.reader import leaf_column_map
from ct.schema.models import FieldDef, TableSchema
from ct.validate.errors import IssueCode, ValidationIssue


# ---------------------------------------------------------------------------
# Scalar validators
# ---------------------------------------------------------------------------

def _validate_int(value: Any, field: FieldDef) -> str | None:
    """Validate int32 / int64."""
    if not isinstance(value, int) or isinstance(value, bool):
        return f"期望整数类型，实际值为 {value!r}（{type(value).__name__}）"
    return None


def _validate_float(value: Any, field: FieldDef) -> str | None:
    """Validate float / double."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return f"期望数值类型，实际值为 {value!r}（{type(value).__name__}）"
    return None


def _validate_bool(value: Any, field: FieldDef) -> str | None:
    """Validate bool."""
    if not isinstance(value, bool):
        return f"期望布尔类型，实际值为 {value!r}（{type(value).__name__}）"
    return None


def _validate_string(value: Any, field: FieldDef) -> str | None:
    """Validate string (None is coerced to empty string upstream)."""
    if value is not None and not isinstance(value, str):
        return f"期望字符串类型，实际值为 {value!r}（{type(value).__name__}）"
    return None


def _validate_enum(value: Any, field: FieldDef) -> str | None:
    """Validate enum — value must be in the allowed values list."""
    if not isinstance(value, str):
        return f"期望枚举字符串，实际值为 {value!r}（{type(value).__name__}）"
    if field.values and value not in field.values:
        return f"枚举值 {value!r} 不在允许列表 {field.values} 中"
    return None


# Map basic type names to their validators.
_SCALAR_VALIDATORS: dict[str, Any] = {
    "int32": _validate_int,
    "int64": _validate_int,
    "float": _validate_float,
    "double": _validate_float,
    "bool": _validate_bool,
    "string": _validate_string,
    "enum": _validate_enum,
}


# ---------------------------------------------------------------------------
# Array validator
# ---------------------------------------------------------------------------

def _validate_array(value: Any, field: FieldDef) -> list[tuple[str, str]]:
    """Validate an array field. Returns ``(dotted_path, message)`` pairs."""
    errors: list[tuple[str, str]] = []
    if not isinstance(value, list):
        errors.append(
            (field.name, f"期望数组类型，实际值为 {value!r}（{type(value).__name__}）")
        )
        return errors

    element_type = field.element
    if not element_type:
        return errors  # schema validation already ensures element is set

    for idx, elem in enumerate(value):
        if element_type == "enum":
            # For array<enum>, validate against element_values.
            if not isinstance(elem, str):
                errors.append(
                    (
                        field.name,
                        f"数组第{idx + 1}个元素期望枚举字符串，"
                        f"实际值为 {elem!r}（{type(elem).__name__}）",
                    )
                )
            elif field.element_values and elem not in field.element_values:
                errors.append(
                    (
                        field.name,
                        f"数组第{idx + 1}个元素枚举值 {elem!r} "
                        f"不在允许列表 {field.element_values} 中",
                    )
                )
        else:
            # Build a temporary FieldDef-like object for scalar validation.
            validator = _SCALAR_VALIDATORS.get(element_type)
            if validator:
                # Create a minimal FieldDef for the element type (model_construct
                # 跳过校验：临时对象不做命名校验）。
                elem_field = FieldDef.model_construct(
                    name=f"{field.name}[{idx}]", type=element_type)  # type: ignore[arg-type]
                err = validator(elem, elem_field)
                if err:
                    errors.append((field.name, f"数组第{idx + 1}个元素{err}"))

    return errors


# ---------------------------------------------------------------------------
# Struct validator
# ---------------------------------------------------------------------------

def _validate_struct(value: Any, field: FieldDef) -> list[tuple[str, str]]:
    """Validate a struct field. Returns ``(dotted_path, message)`` pairs."""
    errors: list[tuple[str, str]] = []
    if not isinstance(value, dict):
        errors.append(
            (
                field.name,
                f"期望结构体（dict），实际值为 {value!r}（{type(value).__name__}）",
            )
        )
        return errors

    if not field.fields:
        return errors

    for sub_field in field.fields:
        sub_value = value.get(sub_field.name)
        for path, msg in _validate_field_value(sub_value, sub_field):
            errors.append((f"{field.name}.{path}", msg))

    return errors


# ---------------------------------------------------------------------------
# Unified field validator
# ---------------------------------------------------------------------------

def _validate_field_value(value: Any, field: FieldDef) -> list[tuple[str, str]]:
    """Validate a single field value. Returns ``(dotted_path, message)`` pairs."""
    # Allow None for string type (treat as empty string).
    if field.type == "string" and value is None:
        return []

    # None / missing value for non-string fields.
    if value is None:
        return [(field.name, f"值不能为空（类型 {field.type}）")]

    if field.type == "array":
        return _validate_array(value, field)

    if field.type == "struct":
        return _validate_struct(value, field)

    # Scalar types (int32, int64, float, double, bool, string, enum).
    validator = _SCALAR_VALIDATORS.get(field.type)
    if validator:
        err = validator(value, field)
        if err:
            return [(field.name, err)]

    return []


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
            for path, msg in _validate_field_value(value, field):
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
