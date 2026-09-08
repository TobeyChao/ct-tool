"""Read Excel data rows against a canonical  ``Layout``.

Values are rebuilt into their canonical shape from each column's stable path:

- a named Record field reassembles its leaf columns into a nested dict;
- an expanded ``vector<Record>`` reads each group's leaf columns in order and
  drops fully-empty trailing groups;
- a single-cell vector splits the cell by its separator.

Parse errors carry the Excel row, column and canonical field path.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import re
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from ct.excel.layout import Column, Layout
from ct.schema.resources import EnumResource, RecordResource, TableResource
from ct.schema.type_expression import NamedType, ScalarType, VectorType
from ct.diagnostics.errors import IssueCode, ValidationIssue

_BOOL_TRUE = frozenset({"true", "1", "yes", "TRUE", "True", "YES", "Yes", "✓"})
_BOOL_FALSE = frozenset({"false", "0", "no", "FALSE", "False", "NO", "No", "✗"})


def _coerce_scalar(type_text: str, raw: Any) -> tuple[Any, bool]:
    """Coerce one leaf cell; returns (value, ok). None passes through for scalars."""
    if raw is None:
        if type_text == "string":
            return "", True
        return None, True
    if type_text in ("int32", "int64"):
        try:
            return int(float(raw)) if isinstance(raw, float) else int(raw), True
        except (TypeError, ValueError):
            return raw, False
    if type_text in ("float", "double"):
        try:
            return float(raw), True
        except (TypeError, ValueError):
            return raw, False
    if type_text == "bool":
        if isinstance(raw, bool):
            return raw, True
        text = str(raw).strip()
        if text in _BOOL_TRUE:
            return True, True
        if text in _BOOL_FALSE:
            return False, True
        return raw, False
    # enum / named leaves are string identifiers
    return str(raw), True


def parse_vector_cell(text: str, element_text: str) -> tuple[list[Any], str | None]:
    """Parse the canonical bracketed vector grammar and return a diagnostic."""
    source = text.strip()
    if source in {"", "[]", "[ ]"}:
        return [], None
    if not (source.startswith("[") and source.endswith("]")):
        return [], "变长 vector 必须使用 [...] 格式"
    body = source[1:-1]
    tokens: list[str] = []
    i = 0
    while i < len(body):
        while i < len(body) and body[i].isspace():
            i += 1
        if i >= len(body):
            break
        start = i
        if body[i] == '"':
            i += 1
            escaped = False
            while i < len(body):
                ch = body[i]
                i += 1
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    break
            else:
                return [], f"字符串从位置 {start + 2} 开始未闭合"
            token = body[start:i]
            try:
                json.loads(token)
            except json.JSONDecodeError:
                return [], f"位置 {start + 2} 的字符串转义无效"
        else:
            while i < len(body) and body[i] != ",":
                i += 1
            token = body[start:i].strip()
        if not token:
            return [], f"位置 {start + 2} 存在空元素或尾逗号"
        tokens.append(token)
        while i < len(body) and body[i].isspace():
            i += 1
        if i < len(body):
            if body[i] != ",":
                return [], f"位置 {i + 2} 缺少逗号"
            i += 1
            if i >= len(body) or not body[i:].strip():
                return [], f"位置 {i + 2} 存在尾逗号"
    values: list[Any] = []
    for index, token in enumerate(tokens, start=1):
        if element_text == "string":
            if not (token.startswith('"') and token.endswith('"')):
                return [], f"第{index}个元素 string 必须使用 JSON 双引号"
            values.append(json.loads(token))
            continue
        if element_text == "bool":
            if token not in {"true", "false"}:
                return [], f"第{index}个元素 bool 必须是 true 或 false"
            values.append(token == "true")
            continue
        if element_text in {"int32", "int64"}:
            if not re.fullmatch(r"[+-]?\d+", token):
                return [], f"第{index}个元素期望 {element_text} 类型"
            values.append(int(token))
            continue
        if element_text in {"float", "double"}:
            if not re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", token):
                return [], f"第{index}个元素期望 {element_text} 类型"
            values.append(float(token))
            continue
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", token):
            return [], f"第{index}个元素 Enum 标识符无效"
        values.append(token)
    return values, None


@dataclass(frozen=True)
class CanonicalParsedRows:
    rows: list[dict[str, Any]]
    excel_rows: list[int]
    issues: list[ValidationIssue] = field(default_factory=list)


def _leaf_path_after_table(table_id: str, stable_path: str) -> list[str]:
    """Segments after the table id, with ``[g]`` markers kept as segments."""
    tail = stable_path[len(table_id) + 1:]
    segments: list[str] = []
    for chunk in tail.split("/"):
        if "[" in chunk:
            name, _, rest = chunk.partition("[")
            segments.append(name)
            segments.append(rest.split("]", 1)[0])
        else:
            segments.append(chunk)
    return segments


class _RowReader:
    def __init__(
        self,
        layout: Layout,
        table: TableResource,
        *,
        records: dict[str, object],
        enums: dict[str, EnumResource] | None = None,
        excel_row: int,
        row_index: int,
    ) -> None:
        self.layout = layout
        self.table = table
        self.records = records
        self.enums = enums or {}
        self.excel_row = excel_row
        self.row_index = row_index
        self.issues: list[ValidationIssue] = []
        self.value_by_path: dict[str, Any] = {}

    def read(self, cells: tuple[Any, ...]) -> dict[str, Any] | None:
        if all(
            c is None or (isinstance(c, str) and not c.strip()) for c in cells
        ):
            return None
        for column in self.layout.columns:
            raw = cells[column.index - 1] if column.index - 1 < len(cells) else None
            self.value_by_path[column.stable_path] = raw
        result: dict[str, Any] = {}
        for field in self.table.fields:
            field_value = self._read_field(field, cells)
            if field_value is not None:
                result[field.name] = field_value
        return result

    def _coerce(self, column: Column, raw: Any) -> Any:
        value, ok = _coerce_scalar(column.type_text, raw)
        if not ok:
            self.issues.append(
                ValidationIssue(
                    table=self.table.table,
                    code=IssueCode.TYPE,
                    message=f"期望 {column.type_text} 类型",
                    row_index=self.row_index,
                    excel_row=self.excel_row,
                    column=column.index - 1,
                    field=column.stable_path,
                    value=raw,
                )
            )
        return value

    def _is_record(self, named: NamedType) -> bool:
        return named.name in self.records

    def _read_field(self, field, cells: tuple[Any, ...]) -> Any:
        type_expr = field.type_expr
        owner = self.table.resource_id
        top = f"{owner}/{field.name}"

        if isinstance(type_expr, VectorType) and isinstance(
            type_expr.element, NamedType
        ) and self._is_record(type_expr.element) and (field.excel_columns or 0) > 0:
            groups: list[dict[str, Any]] = []
            group_count = field.excel_columns or 0
            last_filled = 0
            for group in range(1, group_count + 1):
                element = self._read_record_group(type_expr.element, top, group)
                if element is not None:
                    last_filled = group
            for group in range(1, last_filled + 1):
                groups.append(self._read_record_group(type_expr.element, top, group) or self._default(type_expr.element))
            return groups
        if isinstance(type_expr, VectorType) and (field.excel_columns or 0) > 0:
            values: list[Any] = []
            last_filled = 0
            for group in range(1, field.excel_columns + 1):
                path = f"{top}[{group}]"
                column = next(
                    column for column in self.layout.columns
                    if column.stable_path == path
                )
                raw = self.value_by_path.get(path)
                if raw is not None and not (isinstance(raw, str) and not raw.strip()):
                    last_filled = group
            for group in range(1, last_filled + 1):
                path = f"{top}[{group}]"
                column = next(column for column in self.layout.columns if column.stable_path == path)
                raw = self.value_by_path.get(path)
                values.append(self._default(type_expr.element) if raw is None or (isinstance(raw, str) and not raw.strip()) else self._coerce(column, raw))
            return values
        if isinstance(type_expr, VectorType):
            column = next(
                column
                for column in self.layout.columns
                if column.stable_path == top
            )
            raw = self.value_by_path.get(top)
            return self._split_vector(type_expr, column, raw)
        if isinstance(type_expr, NamedType):
            if self._is_record(type_expr):
                return self._read_record(type_expr, top)
            column = next(
                column for column in self.layout.columns if column.stable_path == top
            )
            return self._coerce(column, self.value_by_path.get(top))
        column = next(
            column for column in self.layout.columns if column.stable_path == top
        )
        return self._coerce(column, self.value_by_path.get(top))


    def _record_leaf_columns(self, top: str, group: int | None) -> list[Column]:
        return [
            column
            for column in self.layout.columns
            if column.stable_path.startswith(top)
            and (group is None or column.group_index == group)
        ]

    def _read_record(self, named: NamedType, top: str) -> dict[str, Any]:
        record = self.records.get(named.name)
        if not isinstance(record, RecordResource):
            return {}
        return self._read_record_fields(record, top, group=None)

    def _read_record_fields(self, record: RecordResource, top: str, group: int | None) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for field in record.fields:
            path = f"{top}/{field.name}"
            typ = field.type_expr
            if isinstance(typ, NamedType) and self._is_record(typ):
                result[field.name] = self._read_record_fields(self.records[typ.name], path, group)
                continue
            if isinstance(typ, VectorType):
                continue
            column = next((c for c in self.layout.columns if c.stable_path == path and (group is None or c.group_index == group)), None)
            if column is not None:
                raw = self.value_by_path.get(path)
                result[field.name] = self._default(typ) if raw is None or (isinstance(raw, str) and not raw.strip()) else self._coerce(column, raw)
            else:
                result[field.name] = self._default(typ)
        return result

    def _read_record_group(self, named: NamedType, top: str, group: int) -> dict[str, Any] | None:
        columns = [
            column
            for column in self._record_leaf_columns(top, group=group)
            if column.group_index == group
        ]
        if not columns:
            return None
        if all(
            self.value_by_path.get(column.stable_path) is None
            or (isinstance(self.value_by_path.get(column.stable_path), str) and not self.value_by_path.get(column.stable_path).strip())
            for column in columns
        ):
            return None  # fully-empty group
        record = None
        # Resolve the element type from the top-level field path supplied by the caller.
        for field in self.table.fields:
            if f"{self.table.resource_id}/{field.name}" == top:
                record = self.records.get(field.type_expr.element.name) if isinstance(field.type_expr, VectorType) and isinstance(field.type_expr.element, NamedType) else None
                break
        if not isinstance(record, RecordResource):
            return None
        return self._read_record_fields(record, f"{top}[{group}]", group)

    def _default(self, typ):
        if isinstance(typ, ScalarType):
            return {"int32": 0, "int64": 0, "float": 0.0, "double": 0.0, "bool": False, "string": ""}[typ.name]
        if isinstance(typ, VectorType):
            return []
        if isinstance(typ, NamedType):
            if typ.expected_kind == "enum":
                enum = self.enums.get(typ.name)
                return enum.values[0].name if enum else ""
            record = self.records.get(typ.name)
            return self._read_record_fields(record, "", None) if isinstance(record, RecordResource) else {}
        return None

    def _split_vector(self, vector: VectorType, column: Column, raw: Any) -> list[Any]:
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            return []
        element_text = self._vector_element_text(vector)
        elements, error = parse_vector_cell(str(raw), element_text)
        if error:
            self.issues.append(
                ValidationIssue(
                    table=self.table.table,
                    code=IssueCode.TYPE,
                    message=error,
                    row_index=self.row_index,
                    excel_row=self.excel_row,
                    column=column.index - 1,
                    field=column.stable_path,
                    value=raw,
                )
            )
        return elements

    def _vector_element_text(self, vector: VectorType) -> str:
        from ct.schema.type_expression import serialize_type_expression

        return serialize_type_expression(vector.element)


def read_canonical_excel(
    excel_path: Path,
    layout: Layout,
    table: TableResource,
    *,
    records: dict[str, object] | None = None,
    enums: dict[str, EnumResource] | None = None,
) -> CanonicalParsedRows:
    """Read Excel rows against a canonical layout; returns canonical values."""
    wb = load_workbook(str(excel_path), read_only=True, data_only=True)
    try:
        ws = wb.active
        if ws is None:
            return CanonicalParsedRows([], [])
        rows: list[dict[str, Any]] = []
        excel_rows: list[int] = []
        issues: list[ValidationIssue] = []
        for row_index, row in enumerate(ws.iter_rows(values_only=True), start=1):
            if row_index <= layout.header_rows:
                continue
            reader = _RowReader(
                layout,
                table,
                records=records,
                enums=enums,
                excel_row=row_index,
                row_index=len(rows) + 1,
            )
            parsed = reader.read(tuple(row))
            if parsed is not None:
                rows.append(parsed)
                excel_rows.append(row_index)
                issues.extend(reader.issues)
        return CanonicalParsedRows(rows, excel_rows, issues)
    finally:
        wb.close()
