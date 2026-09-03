"""Canonical FlatBuffers binary serialization for  Table resources.

Rows (already canonical nested dicts) are serialized into a single-table
FlatBuffers buffer with the same container shape as the legacy writer:

- row = FlatBuffers ``table``; field slots follow client-field order;
- enum leaf -> ``byte``; named Record -> nested ``table`` (offset);
- ``vector<T>`` -> FlatBuffers vector (scalar inline, string/record offsets);
- container = ``items`` (Excel row order) + ``index`` (by-id IndexEntry).

``server_only`` fields are excluded from the client buffer.
"""

from __future__ import annotations

from typing import Any

import flatbuffers

from ct.schema.resources import (
    EnumResource,
    RecordResource,
    TableResource,
)
from ct.schema.type_expression import (
    NamedType,
    ScalarType,
    TypeExpression,
    VectorType,
)

_FBS_SCALAR = {"int32", "int64", "float", "double", "bool", "string"}


def _slot(index: int) -> int:
    return 4 + 2 * index


class _Builder:
    def __init__(
        self,
        table: TableResource,
        records: dict[str, RecordResource],
        enums: dict[str, EnumResource],
    ) -> None:
        self.table = table
        self.records = records
        self.enums = enums

    def _named_kind(self, named: NamedType) -> str:
        if named.expected_kind:
            return named.expected_kind
        return "record" if named.name in self.records else "enum"

    def _prepend_scalar(self, builder, type_expr: ScalarType, value: Any, slot: int) -> None:
        name = type_expr.name
        if name == "int32":
            builder.PrependInt32Slot(slot, int(value) if value is not None else 0, 0)
        elif name == "int64":
            builder.PrependInt64Slot(slot, int(value) if value is not None else 0, 0)
        elif name == "float":
            builder.PrependFloat32Slot(slot, float(value) if value is not None else 0.0, 0.0)
        elif name == "double":
            builder.PrependFloat64Slot(slot, float(value) if value is not None else 0.0, 0.0)
        elif name == "bool":
            builder.PrependBoolSlot(slot, bool(value) if value is not None else False, False)
        elif name == "string":
            offset = builder.CreateSharedString(str(value) if value is not None else "")
            builder.PrependUOffsetTRelativeSlot(slot, offset, 0)

    def _build_record(
        self,
        builder,
        record: RecordResource,
        data: dict[str, Any] | None,
    ) -> int | None:
        if data is None:
            return None
        fields = record.fields
        offsets: dict[int, int] = {}
        for index, field in enumerate(fields):
            if self._is_offset_type(field.type_expr):
                offsets[index] = self._build_offset(builder, field.type_expr, data.get(field.name))
        builder.StartObject(len(fields))
        for index, field in enumerate(fields):
            if index in offsets:
                if offsets[index] is not None:
                    builder.PrependUOffsetTRelativeSlot(index, offsets[index], 0)
            elif self._is_offset_type(field.type_expr):
                continue  # None-valued string/vector: leave slot absent
            elif isinstance(field.type_expr, ScalarType):
                self._prepend_scalar(builder, field.type_expr, data.get(field.name), index)
            elif isinstance(field.type_expr, NamedType) and self._named_kind(field.type_expr) == "enum":
                builder.PrependInt8Slot(index, self._enum_index(field.type_expr, data.get(field.name)), 0)
        return builder.EndObject()

    def _enum_index(self, named: NamedType, value: Any) -> int:
        enum = self.enums[named.name]
        return enum.values.index(value) if value in enum.values else 0

    def _is_offset_type(self, type_expr: TypeExpression) -> bool:
        if isinstance(type_expr, ScalarType):
            return type_expr.name == "string"
        if isinstance(type_expr, VectorType):
            return True
        if isinstance(type_expr, NamedType):
            return self._named_kind(type_expr) == "record"
        return False

    def _build_offset(self, builder, type_expr: TypeExpression, value: Any) -> int | None:
        if isinstance(type_expr, ScalarType):
            if type_expr.name == "string":
                return builder.CreateSharedString(str(value) if value is not None else "") if value is not None else None
            return None
        if isinstance(type_expr, VectorType):
            return self._build_vector(builder, type_expr, value or [])
        if isinstance(type_expr, NamedType) and self._named_kind(type_expr) == "record":
            return self._build_record(builder, self.records[type_expr.name], value)
        return None

    def _element_is_named(self, element: TypeExpression) -> NamedType | None:
        return element if isinstance(element, NamedType) else None

    def _build_vector(self, builder, vector: VectorType, values: list[Any]) -> int:
        element = vector.element
        named = self._element_is_named(element)
        if named is not None and self._named_kind(named) == "record":
            offsets = [
                self._build_record(builder, self.records[named.name], value)
                for value in values
            ]
            builder.StartVector(4, len(offsets), 4)
            for offset in reversed(offsets):
                builder.PrependUOffsetTRelative(offset or 0)
            return builder.EndVector()
        if isinstance(element, ScalarType):
            name = element.name
            if name == "string":
                offsets = [builder.CreateSharedString(str(v)) for v in values]
                builder.StartVector(4, len(offsets), 4)
                for offset in reversed(offsets):
                    builder.PrependUOffsetTRelative(offset)
                return builder.EndVector()
            if name == "int32":
                builder.StartVector(4, len(values), 4)
                for v in reversed(values):
                    builder.PrependInt32(int(v))
                return builder.EndVector()
            if name == "int64":
                builder.StartVector(8, len(values), 8)
                for v in reversed(values):
                    builder.PrependInt64(int(v))
                return builder.EndVector()
            if name == "float":
                builder.StartVector(4, len(values), 4)
                for v in reversed(values):
                    builder.PrependFloat32(float(v))
                return builder.EndVector()
            if name == "double":
                builder.StartVector(8, len(values), 8)
                for v in reversed(values):
                    builder.PrependFloat64(float(v))
                return builder.EndVector()
            if name == "bool":
                builder.StartVector(1, len(values), 1)
                for v in reversed(values):
                    builder.PrependBool(bool(v))
                return builder.EndVector()
        if named is not None and self._named_kind(named) == "enum":
            enum = self.enums[named.name]
            builder.StartVector(1, len(values), 1)
            for v in reversed(values):
                builder.PrependByte(enum.values.index(v) if v in enum.values else 0)
            return builder.EndVector()
        raise ValueError(f"不支持的 vector 元素: {element}")

    def _build_row(self, builder, row: dict[str, Any]) -> int:
        fields = [
            field for field in self.table.fields if not field.server_only
        ]
        offsets: dict[int, int] = {}
        for index, field in enumerate(fields):
            if self._is_offset_type(field.type_expr):
                offset = self._build_offset(builder, field.type_expr, row.get(field.name))
                if offset is not None:
                    offsets[index] = offset
        builder.StartObject(len(fields))
        for index, field in enumerate(fields):
            if index in offsets:
                builder.PrependUOffsetTRelativeSlot(index, offsets[index], 0)
            elif self._is_offset_type(field.type_expr):
                continue  # None-valued string/vector: leave slot absent
            elif isinstance(field.type_expr, ScalarType):
                self._prepend_scalar(builder, field.type_expr, row.get(field.name), index)
            elif isinstance(field.type_expr, NamedType):
                if self._named_kind(field.type_expr) == "enum":
                    builder.PrependInt8Slot(index, self._enum_index(field.type_expr, row.get(field.name)), 0)
                elif self._named_kind(field.type_expr) == "record":
                    offset = self._build_record(builder, self.records[field.type_expr.name], row.get(field.name))
                    if offset is not None:
                        builder.PrependUOffsetTRelativeSlot(_slot(index), offset, 0)
        return builder.EndObject()

    def build(self, rows: list[dict[str, Any]]) -> bytes:
        builder = flatbuffers.Builder(1024)
        client_fields = [f for f in self.table.fields if not f.server_only]
        row_offsets = [self._build_row(builder, row) for row in rows]

        builder.StartVector(4, len(row_offsets), 4)
        for offset in reversed(row_offsets):
            builder.PrependUOffsetTRelative(offset)
        items_vec = builder.EndVector()

        index_vec = None
        if self.table.primary:
            primary = self.table.primary
            ordered = sorted(
                enumerate(rows),
                key=lambda item: int(item[1].get(primary, 0) or 0),
            )
            builder.StartVector(8, len(ordered), 4)
            for original_index, row in reversed(ordered):
                builder.PrependInt32(original_index)
                builder.PrependInt32(int(row.get(primary, 0) or 0))
            index_vec = builder.EndVector()

        num_fields = 2 if index_vec is not None else 1
        builder.StartObject(num_fields)
        builder.PrependUOffsetTRelativeSlot(0, items_vec, 0)
        if index_vec is not None:
            builder.PrependUOffsetTRelativeSlot(1, index_vec, 0)
        container = builder.EndObject()
        builder.Finish(container)
        return bytes(builder.Output())


def build_canonical_table_bytes(
    rows: list[dict[str, Any]],
    table: TableResource,
    *,
    records: dict[str, RecordResource],
    enums: dict[str, EnumResource],
    exclude_server_only: bool = True,
) -> bytes:
    if exclude_server_only:
        table = table.model_copy(
            update={
                "fields": [field for field in table.fields if not field.server_only]
            }
        )
    return _Builder(table, records, enums).build(rows)


def build_canonical_bundle(
    table_name_to_bytes: dict[str, bytes],
) -> bytes:
    """Build a real FlatBuffers ``DataBundle`` (BundledTable list)."""
    builder = flatbuffers.Builder(1024)
    entries: list[int] = []
    for name in sorted(table_name_to_bytes):
        data_vec = builder.CreateByteVector(table_name_to_bytes[name])
        name_offset = builder.CreateString(name)
        builder.StartObject(2)
        builder.PrependUOffsetTRelativeSlot(0, name_offset, 0)
        builder.PrependUOffsetTRelativeSlot(1, data_vec, 0)
        entries.append(builder.EndObject())
    builder.StartVector(4, len(entries), 4)
    for offset in reversed(entries):
        builder.PrependUOffsetTRelative(offset)
    tables_vec = builder.EndVector()
    builder.StartObject(1)
    builder.PrependUOffsetTRelativeSlot(0, tables_vec, 0)
    root = builder.EndObject()
    builder.Finish(root)
    return bytes(builder.Output())
