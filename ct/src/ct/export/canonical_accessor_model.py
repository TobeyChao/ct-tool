"""Shared canonical Accessor/Index model for C# and Lua generators.

Both languages consume the same model: client fields in slot order, primary,
i18n fields, and the CodeName index contract. Neither generator parses
Type Expressions or re-derives index rules. Named ``record`` fields are resolved
against the workspace ``records`` map so the generators can emit nested row
accessors whose wire shape matches the FlatBuffers binary (a record is a nested
table at an offset; a ``vector<Record>`` is a vector of such offsets).
"""

from __future__ import annotations

from dataclasses import dataclass

from ct.schema.indexes import QueryIndex
from ct.schema.resources import CODENAME_FIELD, RecordResource, TableResource
from ct.schema.type_expression import (
    NamedType,
    ScalarType,
    VectorType,
    serialize_type_expression,
)

#: C# 标量类型：type_text → C# 类型（**唯一来源**）。
#: 放在 model 而不是生成器里：model 自己也要把标量映射成 C# 类型文本；若反过来
#: 从 ``canonical_accessor`` 取，就会形成 model → accessor → model 的 import 环。
CSHARP_SCALAR_TYPES = {
    "int8": "sbyte",
    "uint8": "byte",
    "int16": "short",
    "uint16": "ushort",
    "int32": "int",
    "uint32": "uint",
    "int64": "long",
    "uint64": "ulong",
    "float": "float",
    "double": "double",
    "bool": "bool",
}


@dataclass(frozen=True)
class AccessorField:
    name: str
    slot: int  # 0-based vtable slot among client fields (or record fields)
    kind: str  # scalar | enum | record | vector | string
    type_text: str
    i18n: bool = False
    record: RecordResource | None = None  # nested record (kind=record, or vector-of-record)
    element_kind: str | None = None  # for vector: scalar | enum | record | string
    element_type: str = ""  # for vector: element type text (int32 / string / enum name / record name)
    ref_table: str | None = None  # cross-table ref 目标表名（ref 只能是「目标表.主键」）

    @property
    def record_name(self) -> str | None:
        return self.record.name if self.record else None

    @property
    def container_text(self) -> str | None:
        """The ref-style single value container type for a vector field."""
        if self.kind != "vector":
            return None
        if self.element_kind == "record" and self.record_name:
            return f"NStructArray<{self.record_name}>"
        if self.element_kind == "string":
            return "NStructArray<NString>"
        if self.element_kind == "enum":
            return f"NArray<{self.element_type}>"
        # 复用**唯一来源**的 C# 类型映射（避免新增标量时漏改这里）
        return f"NArray<{CSHARP_SCALAR_TYPES[self.element_type]}>"


@dataclass(frozen=True)
class AccessorIndex:
    kind: str  # 当前只有 "codename"
    slot: int


@dataclass(frozen=True)
class CanonicalAccessorModel:
    table: TableResource
    client_fields: tuple[AccessorField, ...]
    primary: AccessorField
    i18n_fields: tuple[AccessorField, ...]
    indexes: tuple[AccessorIndex, ...]
    records: dict[str, RecordResource] | None = None
    # 定宽布局（uniform）：非空表示该表所有行共享同一 vtable，
    # 这张 slot→行内偏移映射是**表级常量**，生成器据此发射字面量偏移（无偏移表）。
    uniform_offsets: dict[int, int] | None = None
    # 稀疏 i18n 表名（如 ``Item_i18n``）：非空时多语言字段的 getter 按**行下标**去该表读
    # 当前语言的文本，缺失时回退主表原文（切语言只换这张表，主表行句柄不动）。
    # 该表**不再**单独产出一份 accessor：它对外没有独立用途，读路径已经完全内联到这里。
    i18n_table: str | None = None
    # 稀疏 i18n 表**自己的**定宽偏移表（vtable 字节偏移 → 行内偏移）。为空表示该表不是定宽
    # 布局，生成物按槽位走 vtable 读（与主表的 uniform_offsets 是两份独立的表级常量）。
    i18n_uniform_offsets: dict[int, int] | None = None

    @property
    def has_i18n(self) -> bool:
        return bool(self.i18n_fields)

    @property
    def is_uniform(self) -> bool:
        return bool(self.uniform_offsets)


def _lookup_record(named: NamedType, records) -> RecordResource | None:
    if records is None:
        return None
    return records.get(named.name)


def _build_field(
    field,
    slot: int,
    records,
) -> AccessorField:
    """Resolve one FieldDef (or record field) into an AccessorField."""
    type_expr = field.type_expr
    text = serialize_type_expression(type_expr)
    if isinstance(type_expr, VectorType):
        element = type_expr.element
        if isinstance(element, NamedType):
            rec = _lookup_record(element, records)
            return AccessorField(
                name=field.name,
                slot=slot,
                kind="vector",
                type_text=text,
                i18n=field.i18n,
                record=rec,
                element_kind="record" if rec else "enum",
                element_type=element.name,
            )
        if isinstance(element, ScalarType):
            return AccessorField(
                name=field.name,
                slot=slot,
                kind="vector",
                type_text=text,
                i18n=field.i18n,
                element_kind="string" if element.name == "string" else "scalar",
                element_type=element.name,
            )
        return AccessorField(
            name=field.name,
            slot=slot,
            kind="vector",
            type_text=text,
            i18n=field.i18n,
            element_kind="scalar",
        )
    if isinstance(type_expr, NamedType):
        rec = _lookup_record(type_expr, records)
        return AccessorField(
            name=field.name,
            slot=slot,
            kind=("record" if rec else "enum"),
            type_text=text,
            i18n=field.i18n,
            record=rec,
            ref_table=_ref_table(field),
        )
    if isinstance(type_expr, ScalarType):
        return AccessorField(
            name=field.name,
            slot=slot,
            kind=("string" if type_expr.name == "string" else "scalar"),
            type_text=text,
            i18n=field.i18n,
            ref_table=_ref_table(field),
        )
    return AccessorField(
        name=field.name,
        slot=slot,
        kind="scalar",
        type_text=text,
        i18n=field.i18n,
    )


def record_accessor_fields(
    record: RecordResource,
    records: dict[str, RecordResource] | None,
) -> tuple[AccessorField, ...]:
    """Resolve a Record's fields to AccessorFields (slots = field order)."""
    return tuple(
        _build_field(field, index, records)
        for index, field in enumerate(record.fields)
    )


def referenced_records(
    model: CanonicalAccessorModel,
) -> list[RecordResource]:
    """All records referenced by the table's client fields, transitively.

    Returns records in deterministic pre-order (parent before its nested
    records), so each generated row struct is emitted exactly once.
    """
    result: list[RecordResource] = []
    seen: set[str] = set()

    def visit(record: RecordResource) -> None:
        if record.name in seen:
            return
        seen.add(record.name)
        result.append(record)
        for sub in record_accessor_fields(record, model.records):
            if sub.record is not None:
                visit(sub.record)

    for field in model.client_fields:
        if field.record is not None:
            visit(field.record)
    return result


def _ref_table(field) -> str | None:
    if not field.ref:
        return None
    return field.ref.partition(".")[0] or None


def build_accessor_model(
    table: TableResource,
    indexes: tuple[QueryIndex, ...],
    records: dict[str, RecordResource] | None = None,
    uniform_offsets: dict[int, int] | None = None,
    i18n_table: str | None = None,
    i18n_uniform_offsets: dict[int, int] | None = None,
) -> CanonicalAccessorModel:
    client = [field for field in table.fields if not field.server_only]
    slots = {field.name: index for index, field in enumerate(client)}
    fields = tuple(
        _build_field(field, slots[field.name], records) for field in client
    )
    primary = next(field for field in fields if field.name == table.primary)
    i18n_fields = tuple(field for field in fields if field.i18n)

    # 稀疏 i18n 表名按约定推导（`{Table}_i18n`，与导出器 `_i18n_table()` 一致）。
    # 这样**单独**调用生成器也不会漏掉 i18n 读取（否则多语言字段会静默退回主表原文）。
    if i18n_table is None and i18n_fields:
        i18n_table = f"{table.table}_i18n"
    # codename 索引的槽位 = 约定字段 CodeName 在 client_fields 里的序号（导出器写库时同源）
    accessor_indexes = tuple(
        AccessorIndex(index.kind, slots[CODENAME_FIELD]) for index in indexes
    )
    return CanonicalAccessorModel(
        table=table,
        client_fields=fields,
        primary=primary,
        i18n_fields=i18n_fields,
        indexes=accessor_indexes,
        records=records,
        uniform_offsets=uniform_offsets,
        i18n_table=i18n_table,
        i18n_uniform_offsets=i18n_uniform_offsets,
    )
