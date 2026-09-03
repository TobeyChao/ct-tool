"""Table-level Code/Group query indexes (canonical v4).

A Code lookup is an auxiliary unique lookup over a non-i18n string field and
never replaces the integer primary key; a Group lookup is non-unique over a
scalar/Enum field. Index fields must be declared explicitly as table-level
``indexes``, never as scattered boolean switches.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from ct.schema.resources import TableResource
from ct.schema.type_expression import NamedType, ScalarType, VectorType

IndexKind = Literal["code", "group"]

_GROUP_SCALARS = frozenset({"int32", "int64", "float", "double", "bool", "string"})


@dataclass(frozen=True)
class QueryIndex:
    kind: IndexKind
    field: str


def parse_indexes(raw: list[dict[str, Any]]) -> tuple[QueryIndex, ...]:
    """Parse and validate the declarative indexes list (max one per kind)."""
    indexes: list[QueryIndex] = []
    seen_kinds: set[str] = set()
    for item in raw or []:
        kind = item.get("kind")
        field = item.get("field")
        if kind not in ("code", "group") or not isinstance(field, str) or not field:
            raise ValueError("indexes 每条必须包含 kind(code|group) 与 field")
        if kind in seen_kinds:
            raise ValueError(f"首版每张表最多一个 {kind} 索引")
        seen_kinds.add(kind)
        indexes.append(QueryIndex(kind=kind, field=field))
    return tuple(indexes)


def validate_indexes(table: TableResource, indexes: tuple[QueryIndex, ...]) -> None:
    """Validate index fields against the table schema (no data scan)."""
    by_name = {field.name: field for field in table.fields}
    for index in indexes:
        field = by_name.get(index.field)
        if field is None:
            raise ValueError(
                f"表 {table.table}: 索引字段 '{index.field}' 不在字段列表中"
            )
        if field.i18n:
            raise ValueError(
                f"表 {table.table}/{index.field}: 索引字段不能带 i18n "
                "（查询键不能随导出语言改变）"
            )
        type_expr = field.type_expr
        if isinstance(type_expr, VectorType):
            raise ValueError(
                f"表 {table.table}/{index.field}: 索引字段不能是 vector"
            )
        if index.kind == "code":
            if not (
                isinstance(type_expr, ScalarType) and type_expr.name == "string"
            ):
                raise ValueError(
                    f"表 {table.table}/{index.field}: Code 索引字段必须为非 i18n string"
                )
        else:  # group
            if isinstance(type_expr, NamedType):
                if type_expr.expected_kind != "enum":
                    raise ValueError(
                        f"表 {table.table}/{index.field}: Group 索引字段必须是标量或 Enum"
                    )
            elif not (
                isinstance(type_expr, ScalarType)
                and type_expr.name in _GROUP_SCALARS
            ):
                raise ValueError(
                    f"表 {table.table}/{index.field}: Group 索引字段必须是标量或 Enum"
                )
