"""Canonical FlatBuffers binary serialization for  Table resources.

Rows (already canonical nested dicts) are serialized into a single-table
FlatBuffers buffer with the same container shape as the legacy writer:

- row = FlatBuffers ``table``; field slots follow client-field order;
- enum leaf -> ``byte``; named Record -> nested ``table`` (offset);
- ``vector<T>`` -> FlatBuffers vector (scalar inline, string/record offsets);
- container = ``items`` (Excel row order) + ``index`` (by-id IndexEntry)
  + ``idHash`` (primary key buckets) + ``codeNameIndex`` (declared CodeName index only).

``server_only`` fields are excluded from the client buffer.
"""

from __future__ import annotations

import struct
from typing import Any

import flatbuffers

from ct.export.index_query import production_hash
from ct.schema.resources import (
    CODENAME_FIELD,
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

_FBS_SCALAR = {
    "int8", "uint8", "int16", "uint16", "int32", "uint32",
    "int64", "uint64", "float", "double", "bool", "string",
}

#: 标量 → (flatbuffers Builder 的 *Slot 方法名, 默认值, 强制转换)
#: `*Slot` 的语义：值 == 默认值时**不写槽位**（这正是需要 uniform 的原因）。
_SCALAR_SLOTS = {
    "int8": ("PrependInt8Slot", 0, int),
    "uint8": ("PrependUint8Slot", 0, int),
    "int16": ("PrependInt16Slot", 0, int),
    "uint16": ("PrependUint16Slot", 0, int),
    "int32": ("PrependInt32Slot", 0, int),
    "uint32": ("PrependUint32Slot", 0, int),
    "int64": ("PrependInt64Slot", 0, int),
    "uint64": ("PrependUint64Slot", 0, int),
    "float": ("PrependFloat32Slot", 0.0, float),
    "double": ("PrependFloat64Slot", 0.0, float),
    "bool": ("PrependBoolSlot", False, bool),
}

#: 标量 → flatbuffers Builder 的无条件写方法（uniform 用）+ 对齐
_SCALAR_PREPENDS = {
    "int8": ("PrependInt8", 1),
    "uint8": ("PrependUint8", 1),
    "int16": ("PrependInt16", 2),
    "uint16": ("PrependUint16", 2),
    "int32": ("PrependInt32", 4),
    "uint32": ("PrependUint32", 4),
    "int64": ("PrependInt64", 8),
    "uint64": ("PrependUint64", 8),
    "float": ("PrependFloat32", 4),
    "double": ("PrependFloat64", 8),
    "bool": ("PrependBool", 1),
}


def _coerce_scalar_value(name: str, value: Any) -> Any:
    """把值强制成该标量在 Python 侧的表示（None → 默认值）。"""
    entry = _SCALAR_SLOTS.get(name)
    if entry is None:
        raise ValueError(f"不支持的标量类型 {name}")
    _method, default, cast = entry
    return cast(value) if value is not None else default


def _slot(index: int) -> int:
    return 4 + 2 * index


class _Builder:
    def __init__(
        self,
        table: TableResource,
        records: dict[str, RecordResource],
        enums: dict[str, EnumResource],
        uniform: bool = False,
    ) -> None:
        self.table = table
        self.records = records
        self.enums = enums
        # uniform=True：每个槽位无条件写出（含默认值），使同一张表的所有行共享同一 vtable，
        # 从而「字段在行内的偏移」成为表级常量 —— 生成器可据此发射字面量偏移。
        self.uniform = uniform

    def _prepend_scalar_slot(self, builder, type_expr: ScalarType, value: Any, index: int) -> None:
        """无条件写槽位（uniform 布局用；默认值也占位）。"""
        name = type_expr.name
        entry = _SCALAR_PREPENDS.get(name)
        if entry is None:
            raise ValueError(f"uniform 布局不支持标量 {name}")
        method, _align = entry
        getattr(builder, method)(_coerce_scalar_value(name, value))
        builder.Slot(index)

    def _prepend_enum(
        self, builder, type_expr: NamedType, value: Any, index: int
    ) -> None:
        """写枚举槽位。

        非 uniform：``PrependInt8Slot(.., 0)`` —— 值为**第 0 个枚举项**（= 默认值）时
        flatbuffers 会**省略该槽位**，于是同一张表的不同行可能产生不同 vtable。

        uniform：必须**无条件占位**，否则「同表所有行共享同一 vtable」的前提不成立
        （含枚举的表仍会有多种 vtable），且 ``probe_row_layout`` 用空白行推导时会
        把该槽位推成 offset ``0``，生成器据此发射的字面量偏移会读到 vtable soffset
        —— **静默读错整行**。所以这里走裸 ``PrependInt8`` + ``Slot(index)``。
        """
        enum_index = self._enum_index(type_expr, value)
        if self.uniform:
            builder.PrependInt8(enum_index)
            builder.Slot(index)
        else:
            builder.PrependInt8Slot(index, enum_index, 0)

    def _named_kind(self, named: NamedType) -> str:
        if named.expected_kind:
            return named.expected_kind
        return "record" if named.name in self.records else "enum"

    def _prepend_scalar(self, builder, type_expr: ScalarType, value: Any, slot: int) -> None:
        name = type_expr.name
        if name == "string":
            offset = builder.CreateSharedString(str(value) if value is not None else "")
            builder.PrependUOffsetTRelativeSlot(slot, offset, 0)
            return
        entry = _SCALAR_SLOTS.get(name)
        if entry is None:
            raise ValueError(f"不支持的标量类型 {name}")
        method, default, cast = entry
        getattr(builder, method)(slot, cast(value) if value is not None else default, default)

    def _build_record(
        self,
        builder,
        record: RecordResource,
        data: dict[str, Any] | None,
    ) -> int | None:
        if data is None:
            if not self.uniform:
                return None
            data = {}
        fields = record.fields
        offsets: dict[int, int] = {}
        for index, field in enumerate(fields):
            if self._is_offset_type(field.type_expr):
                offsets[index] = self._build_offset(
                    builder, field.type_expr, data.get(field.name), required=self.uniform
                )
        builder.StartObject(len(fields))
        for index, field in enumerate(fields):
            if index in offsets and offsets[index] is not None:
                builder.PrependUOffsetTRelativeSlot(index, offsets[index], 0)
            elif self._is_offset_type(field.type_expr):
                continue
            elif isinstance(field.type_expr, ScalarType):
                if self.uniform:
                    self._prepend_scalar_slot(builder, field.type_expr, data.get(field.name), index)
                else:
                    self._prepend_scalar(builder, field.type_expr, data.get(field.name), index)
            elif isinstance(field.type_expr, NamedType) and self._named_kind(field.type_expr) == "enum":
                self._prepend_enum(builder, field.type_expr, data.get(field.name), index)
        return builder.EndObject()

    def _enum_index(self, named: NamedType, value: Any) -> int:
        enum = self.enums[named.name]
        names = [item.name for item in enum.values]
        return names.index(value) if value in names else 0

    def _is_offset_type(self, type_expr: TypeExpression) -> bool:
        if isinstance(type_expr, ScalarType):
            return type_expr.name == "string"
        if isinstance(type_expr, VectorType):
            return True
        if isinstance(type_expr, NamedType):
            return self._named_kind(type_expr) == "record"
        return False

    def _build_offset(
        self, builder, type_expr: TypeExpression, value: Any, required: bool = False
    ) -> int | None:
        if isinstance(type_expr, ScalarType):
            if type_expr.name == "string":
                if value is None and not required:
                    return None
                return builder.CreateSharedString(str(value) if value is not None else "")
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
            entry = _SCALAR_PREPENDS.get(name)
            if entry is None:
                raise ValueError(f"vector 不支持的元素标量类型 {name}")
            method, align = entry
            prepend = getattr(builder, method)
            builder.StartVector(align, len(values), align)
            for v in reversed(values):
                prepend(_coerce_scalar_value(name, v))
            return builder.EndVector()
        if named is not None and self._named_kind(named) == "enum":
            enum = self.enums[named.name]
            builder.StartVector(1, len(values), 1)
            for v in reversed(values):
                names = [item.name for item in enum.values]
                builder.PrependByte(names.index(v) if v in names else 0)
            return builder.EndVector()
        raise ValueError(f"不支持的 vector 元素: {element}")

    def _build_row(self, builder, row: dict[str, Any]) -> int:
        fields = [
            field for field in self.table.fields if not field.server_only
        ]
        offsets: dict[int, int] = {}
        for index, field in enumerate(fields):
            if self._is_offset_type(field.type_expr):
                offset = self._build_offset(
                    builder, field.type_expr, row.get(field.name), required=self.uniform
                )
                if offset is not None:
                    offsets[index] = offset
        builder.StartObject(len(fields))
        for index, field in enumerate(fields):
            if index in offsets:
                builder.PrependUOffsetTRelativeSlot(index, offsets[index], 0)
            elif self._is_offset_type(field.type_expr):
                continue  # None-valued string/vector: leave slot absent
            elif isinstance(field.type_expr, ScalarType):
                if self.uniform:
                    self._prepend_scalar_slot(builder, field.type_expr, row.get(field.name), index)
                else:
                    self._prepend_scalar(builder, field.type_expr, row.get(field.name), index)
            elif isinstance(field.type_expr, NamedType):
                if self._named_kind(field.type_expr) == "enum":
                    self._prepend_enum(builder, field.type_expr, row.get(field.name), index)
                elif self._named_kind(field.type_expr) == "record":
                    offset = self._build_record(
                        builder, self.records[field.type_expr.name], row.get(field.name)
                    )
                    if offset is not None:
                        builder.PrependUOffsetTRelativeSlot(_slot(index), offset, 0)
        return builder.EndObject()

    # ---- 容器 slot 约定 ----
    # 0 = items / 1 = 主键有序索引 / 2 = 主键哈希 / 3 = CodeName 索引
    # （4/5 曾用于 Group 排序对与区间哈希；该索引已砍，槽位空出）
    CONTAINER_SLOT_CODE = 3

    def _build_code_index(self, builder, rows: list[dict[str, Any]], field: str) -> int:
        """CodeName 索引：开放寻址桶表，桶里存 ``rowIndex + 1``（0 = 空）。

        key 用 **FNV-1a 64**（与 ``ct.export.index_query.production_hash`` 及运行期实现一致）
        取低位置做桶下标。不同字符串可能撞同一哈希，**运行期必须再按字段做精确字符串确认**，
        所以这里不需要处理冲突键的存储。负载因子 <= 0.7，平均探测 ~1.5 次。
        """
        slots = 1
        while slots < max(8, (len(rows) * 10 + 6) // 7):
            slots <<= 1
        mask = slots - 1
        buckets = [0] * slots
        for row_index, row in enumerate(rows):
            value = row.get(field)
            if value is None:
                continue
            text = str(value)
            if text == "":
                continue
            probe = production_hash(text) & mask
            while buckets[probe] != 0:
                probe = (probe + 1) & mask
            buckets[probe] = row_index + 1
        builder.StartVector(4, slots, 4)
        for v in reversed(buckets):
            builder.PrependInt32(v)
        return builder.EndVector()

    def build(self, rows: list[dict[str, Any]]) -> bytes:
        builder = flatbuffers.Builder(1024)
        client_fields = [f for f in self.table.fields if not f.server_only]
        row_offsets = [self._build_row(builder, row) for row in rows]

        builder.StartVector(4, len(row_offsets), 4)
        for offset in reversed(row_offsets):
            builder.PrependUOffsetTRelative(offset)
        items_vec = builder.EndVector()

        index_vec = None
        hash_vec = None
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

            # 开放寻址哈希索引：把 ByID 从 O(log n) 二分降到 O(1)（对齐 参考实现 的 idTableOffset）。
            # 桶里存「index 向量中的位置 + 1」，0 表示空 —— 探测时只需读 index 向量，
            # 不必触碰行本体。负载因子 <= 0.7，平均探测 ~1.5 次。
            keys = [int(row.get(primary, 0) or 0) for row in rows]
            slots = 1
            while slots < max(8, (len(rows) * 10 + 6) // 7):
                slots <<= 1
            mask = slots - 1
            table_arr = [0] * slots
            for pos, (original_index, _row) in enumerate(ordered):
                h = (keys[original_index] * 2654435761) & 0xFFFFFFFF
                b = h & mask
                while table_arr[b] != 0:
                    b = (b + 1) & mask
                table_arr[b] = pos + 1
            builder.StartVector(4, slots, 4)
            for v in reversed(table_arr):
                builder.PrependInt32(v)
            hash_vec = builder.EndVector()

        # 二级查询索引（表级声明，见 schema 的 indexes:）
        code_vec = None
        for index in getattr(self.table, "indexes", ()) or ():
            if index.kind == "codename":
                code_vec = self._build_code_index(builder, rows, CODENAME_FIELD)

        # vtable 槽位数必须覆盖**最高**用到的 slot
        num_fields = 1
        if index_vec is not None:
            num_fields = 2
        if hash_vec is not None:
            num_fields = 3
        if code_vec is not None:
            num_fields = 4
        builder.StartObject(num_fields)
        builder.PrependUOffsetTRelativeSlot(0, items_vec, 0)
        if index_vec is not None:
            builder.PrependUOffsetTRelativeSlot(1, index_vec, 0)
        if hash_vec is not None:
            builder.PrependUOffsetTRelativeSlot(2, hash_vec, 0)
        if code_vec is not None:
            builder.PrependUOffsetTRelativeSlot(3, code_vec, 0)
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
    uniform: bool = False,
) -> bytes:
    if exclude_server_only:
        table = table.model_copy(
            update={
                "fields": [field for field in table.fields if not field.server_only]
            }
        )
    return _Builder(table, records, enums, uniform=uniform).build(rows)


def _row_vtables(data: bytes) -> list[tuple[int, int, int]]:
    """返回每行的 ``(行对象偏移, vtable 偏移, vtable 长度)``。

    容器表布局：根表 slot 0 = items 向量；行对象在向量元素里（uoffset）。
    """
    container = struct.unpack_from("<i", data, 0)[0]
    cvt = container - struct.unpack_from("<i", data, container)[0]
    cvt_len = struct.unpack_from("<H", data, cvt)[0]
    items_off = struct.unpack_from("<H", data, cvt + 4)[0] if 4 < cvt_len else 0
    items = container + items_off + struct.unpack_from("<i", data, container + items_off)[0]
    count = struct.unpack_from("<i", data, items)[0]
    out: list[tuple[int, int, int]] = []
    for index in range(count):
        element = items + 4 + index * 4
        row = element + struct.unpack_from("<i", data, element)[0]
        vt = row - struct.unpack_from("<i", data, row)[0]
        out.append((row, vt, struct.unpack_from("<H", data, vt)[0]))
    return out


def count_vtables(data: bytes) -> int:
    """该表产出的**不同 vtable 内容数**。

    uniform=True 的正常结果是 1；>1 说明「同表所有行共享同一 vtable」的前提没达成，
    定宽布局下生成器发射的字面量偏移会读到错位数据（静默），所以导出期必须硬断言。
    """
    seen: set[bytes] = set()
    for _row, vt, vt_len in _row_vtables(data):
        seen.add(data[vt:vt + vt_len])
    return len(seen)


def written_slot_ratio(data: bytes, client_field_count: int) -> float:
    """已写出槽位的比例（= 填充率），**直接从产出字节统计**，不复刻写入规则。

    统计口径与导出器一致：vtable 里槽位（``4 + 2*字段序``）的值非 0 即视为「写出来了」。
    ``server_only`` 字段不进二进制，调用方传入的应是客户端字段数。
    """
    rows = _row_vtables(data)
    if not rows:
        return 1.0
    total = written = 0
    for _row, vt, vt_len in rows:
        for index in range(client_field_count):
            slot = 4 + 2 * index
            total += 1
            if slot + 2 <= vt_len and struct.unpack_from("<H", data, vt + slot)[0] != 0:
                written += 1
    return written / total


def probe_row_layout(
    table: TableResource,
    *,
    records: dict[str, RecordResource],
    enums: dict[str, EnumResource],
) -> dict[int, int]:
    """返回 uniform 布局下该表的 slot → 行内偏移映射。

    与 ``uniform=True`` 导出配套：所有行共享同一 vtable，因此该映射是表级常量，
    生成器可据此发射字面量偏移（``*(int*)(row + 36)``），彻底去掉偏移表间接层。
    """
    blank = {field.name: None for field in table.fields if not field.server_only}
    data = _Builder(table, records, enums, uniform=True).build([blank])
    client_fields = [f for f in table.fields if not f.server_only]

    # buffer 根是 container 表：slot 4 = items 向量；行对象在向量元素里（不是根表本身）
    container = struct.unpack_from("<i", data, 0)[0]
    cvt = container - struct.unpack_from("<i", data, container)[0]
    cvt_len = struct.unpack_from("<H", data, cvt)[0]
    items_off = struct.unpack_from("<H", data, cvt + 4)[0] if 4 < cvt_len else 0
    items = container + items_off + struct.unpack_from("<i", data, container + items_off)[0]
    first = items + 4
    row = first + struct.unpack_from("<i", data, first)[0]

    vt = row - struct.unpack_from("<i", data, row)[0]
    vt_len = struct.unpack_from("<H", data, vt)[0]
    out: dict[int, int] = {}
    for index in range(len(client_fields)):
        slot = 4 + 2 * index
        out[slot] = struct.unpack_from("<H", data, vt + slot)[0] if slot < vt_len else 0
    return out

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
