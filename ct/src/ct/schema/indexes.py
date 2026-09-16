"""Table-level CodeName query index (canonical ).

A CodeName lookup is an auxiliary unique lookup and **always targets the field named
``CodeName`` of type ``string``** (see ``resources.CODENAME_FIELD``) — it is not a
switch that may point at an arbitrary string field, so the declaration carries no
``field``. Indexes must be declared explicitly as table-level ``indexes``, never as
scattered boolean switches.

⚠️ A **Group** index (non-unique lookup over an int32/bool/Enum field) was implemented
and then cut before it ever reached a real table: no table declared it, the Lua side was
still an ``error(...)`` stub, and the Excel reader silently dropped rows whose group cell
was blank (missing from key 0, while the field itself read as 0). Re-adding it means
re-adding ``field`` to :class:`QueryIndex`, the two container slots (4 = sorted
``(key, row)`` pairs, 5 = ``(start, count)`` bucket table), the native binding, and a
default-value fallback in the binary exporter. The recorded plan lives in the game
repo's ``Docs/TODO/开工方案.md``.
"""

from __future__ import annotations

from typing import Any

from ct.schema.resources import CODENAME_FIELD, QueryIndex, TableResource
from ct.schema.type_expression import ScalarType, VectorType


def parse_indexes(raw: list[dict[str, Any]]) -> tuple[QueryIndex, ...]:
    """Parse and validate the declarative indexes list (max one per kind).

    ``codename`` 不写 ``field``（固定指向 ``CodeName``）。旧写法 ``kind: code``（以及已砍掉的
    ``kind: group``）一律拒绝 —— 不给兼容别名，避免两套名字并存。
    """
    indexes: list[QueryIndex] = []
    seen_kinds: set[str] = set()
    for item in raw or []:
        extra = set(item) - {"kind"}
        if extra:
            # 静默忽略多余键比报错危险：写 field 的人会以为字段名是可配的
            raise ValueError(
                f"indexes 条目只接受 kind 一个键，多出 {sorted(extra)}"
                f"（codename 固定指向 {CODENAME_FIELD}，不写 field）"
            )
        kind = item.get("kind")
        if kind != "codename":
            raise ValueError(
                "indexes 每条必须包含 kind(codename)；codename 不写 field"
            )
        if kind in seen_kinds:
            raise ValueError(f"每张表最多一个 {kind} 索引")
        seen_kinds.add(kind)
        indexes.append(QueryIndex(kind=kind))
    return tuple(indexes)


def validate_indexes(table: TableResource, indexes: tuple[QueryIndex, ...]) -> None:
    """Validate the index against the table schema (no data scan).

    codename 索引固定指向 :data:`CODENAME_FIELD`，所以要校验的是「表里**存在**这样一个字段，
    且它是非 i18n / 非 server_only / 非 vector 的 string」。
    """
    by_name = {field.name: field for field in table.fields}
    for index in indexes:  # noqa: B007 — 目前唯一的 kind 就是 codename
        field = by_name.get(CODENAME_FIELD)
        if field is None:
            raise ValueError(
                f"表 {table.table}: codename 索引要求存在名为 {CODENAME_FIELD} 的"
                "字段（type: string），当前字段列表里没有"
                "（如需删除/改名该字段，先移除 codename 索引声明）"
            )
        if field.i18n:
            raise ValueError(
                f"表 {table.table}/{CODENAME_FIELD}: 索引字段不能带 i18n "
                "（查询键不能随导出语言改变）"
            )
        if field.server_only:
            raise ValueError(
                f"表 {table.table}/{CODENAME_FIELD}: 索引字段不能是 server_only "
                "（该字段不进客户端二进制，客户端建不出索引）"
            )
        type_expr = field.type_expr
        if isinstance(type_expr, VectorType):
            raise ValueError(
                f"表 {table.table}/{CODENAME_FIELD}: 索引字段不能是 vector"
            )
        if not (isinstance(type_expr, ScalarType) and type_expr.name == "string"):
            raise ValueError(
                f"表 {table.table}/{CODENAME_FIELD}: codename 索引要求 "
                f"{CODENAME_FIELD} 是非 i18n 的 string"
            )
