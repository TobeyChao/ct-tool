"""Table-level CodeName/Group query indexes (canonical ).

A CodeName lookup is an auxiliary unique lookup and **always targets the field named
``CodeName`` of type ``string``** (see ``resources.CODENAME_FIELD``) — it is not a
switch that may point at an arbitrary string field. A Group lookup is non-unique over
a scalar/Enum field and *does* name its field. Indexes must be declared explicitly as
table-level ``indexes``, never as scattered boolean switches.
"""

from __future__ import annotations

from typing import Any, Literal

from ct.schema.resources import CODENAME_FIELD, QueryIndex, TableResource
from ct.schema.type_expression import NamedType, ScalarType, VectorType

IndexKind = Literal["codename", "group"]

# Group 索引在二进制里以 **int32 key** 编码（见 canonical_binary._group_key），
# 所以只支持能无损放进 int32 的字段类型：int32 / bool / enum。
_GROUP_SCALARS = frozenset({"int32", "bool"})


def parse_indexes(raw: list[dict[str, Any]]) -> tuple[QueryIndex, ...]:
    """Parse and validate the declarative indexes list (max one per kind).

    ``codename`` 不写 ``field``（固定指向 ``CodeName``）；``group`` 必须写 ``field``。
    field 规则的细节由 :class:`QueryIndex` 自身校验（含「codename 不得写 field」）。
    """
    indexes: list[QueryIndex] = []
    seen_kinds: set[str] = set()
    for item in raw or []:
        kind = item.get("kind")
        if kind not in ("codename", "group"):
            raise ValueError(
                "indexes 每条必须包含 kind(codename|group)"
                "（codename 不写 field；group 必须写 field）"
            )
        if kind in seen_kinds:
            raise ValueError(f"首版每张表最多一个 {kind} 索引")
        seen_kinds.add(kind)
        indexes.append(QueryIndex(kind=kind, field=item.get("field")))
    return tuple(indexes)


def validate_indexes(table: TableResource, indexes: tuple[QueryIndex, ...]) -> None:
    """Validate index fields against the table schema (no data scan)."""
    by_name = {field.name: field for field in table.fields}
    for index in indexes:
        field = by_name.get(index.field)
        if field is None:
            if index.kind == "codename":
                raise ValueError(
                    f"表 {table.table}: codename 索引要求存在名为 {CODENAME_FIELD} 的"
                    "字段（type: string），当前字段列表里没有"
                )
            raise ValueError(
                f"表 {table.table}: 索引字段 '{index.field}' 不在字段列表中"
            )
        if field.i18n:
            raise ValueError(
                f"表 {table.table}/{index.field}: 索引字段不能带 i18n "
                "（查询键不能随导出语言改变）"
            )
        if field.server_only:
            raise ValueError(
                f"表 {table.table}/{index.field}: 索引字段不能是 server_only "
                "（该字段不进客户端二进制，客户端建不出索引）"
            )
        type_expr = field.type_expr
        if isinstance(type_expr, VectorType):
            raise ValueError(
                f"表 {table.table}/{index.field}: 索引字段不能是 vector"
            )
        if index.kind == "codename":
            if index.field != CODENAME_FIELD:
                # QueryIndex 会归一化，正常走不到这里；留作防御
                raise ValueError(
                    f"表 {table.table}: codename 索引只能指向 {CODENAME_FIELD}"
                )
            if not (
                isinstance(type_expr, ScalarType) and type_expr.name == "string"
            ):
                raise ValueError(
                    f"表 {table.table}/{index.field}: codename 索引要求 "
                    f"{CODENAME_FIELD} 是非 i18n 的 string"
                )
        else:  # group
            if isinstance(type_expr, NamedType):
                if type_expr.expected_kind != "enum":
                    raise ValueError(
                        f"表 {table.table}/{index.field}: Group 索引字段必须是 int32/bool/Enum"
                    )
            elif not (
                isinstance(type_expr, ScalarType)
                and type_expr.name in _GROUP_SCALARS
            ):
                raise ValueError(
                    f"表 {table.table}/{index.field}: Group 索引字段必须是 int32/bool/Enum"
                    "（首版以 int32 编码 key，int64/float/double/string 不支持）"
                )
