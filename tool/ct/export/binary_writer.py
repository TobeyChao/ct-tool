from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import flatbuffers

from ct.schema.models import FieldDef, TableSchema

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Slot / vector writers（函数组合成类 6.9：查表取代重复的 if/elif 链）
# ---------------------------------------------------------------------------

_OFFSET_TYPES = frozenset({"string", "struct", "array"})


def _slot_enum(builder: flatbuffers.Builder, slot: int, field: FieldDef, value: Any) -> None:
    values = field.values or []
    idx = values.index(value) if value in values else 0
    builder.PrependInt8Slot(slot, idx, 0)


def _slot_bool(builder: flatbuffers.Builder, slot: int, field: FieldDef, value: Any) -> None:
    builder.PrependBoolSlot(slot, bool(value) if value is not None else False, False)


def _slot_int32(builder: flatbuffers.Builder, slot: int, field: FieldDef, value: Any) -> None:
    builder.PrependInt32Slot(slot, int(value) if value is not None else 0, 0)


def _slot_int64(builder: flatbuffers.Builder, slot: int, field: FieldDef, value: Any) -> None:
    builder.PrependInt64Slot(slot, int(value) if value is not None else 0, 0)


def _slot_float(builder: flatbuffers.Builder, slot: int, field: FieldDef, value: Any) -> None:
    builder.PrependFloat32Slot(slot, float(value) if value is not None else 0.0, 0.0)


def _slot_double(builder: flatbuffers.Builder, slot: int, field: FieldDef, value: Any) -> None:
    builder.PrependFloat64Slot(slot, float(value) if value is not None else 0.0, 0.0)


_SCALAR_SLOT_WRITERS: dict[str, Any] = {
    "enum": _slot_enum,
    "bool": _slot_bool,
    "int32": _slot_int32,
    "int64": _slot_int64,
    "float": _slot_float,
    "double": _slot_double,
}


def _prepend_slot(
    builder: flatbuffers.Builder,
    slot: int,
    field: FieldDef,
    value: Any,
    offset: int | None = None,
) -> None:
    """按字段类型写入 vtable slot；string/struct/array 使用预构建的 offset。"""
    if field.type in _OFFSET_TYPES:
        if offset is not None:
            builder.PrependUOffsetTRelativeSlot(slot, offset, 0)
        return
    _SCALAR_SLOT_WRITERS[field.type](builder, slot, field, value)


def _vector_strings(builder: flatbuffers.Builder, field: FieldDef, values: list) -> int:
    str_offsets = [builder.CreateString(str(v)) for v in values]
    builder.StartVector(4, len(str_offsets), 4)
    for o in reversed(str_offsets):
        builder.PrependUOffsetTRelative(o)
    return builder.EndVector()


def _vector_enum(builder: flatbuffers.Builder, field: FieldDef, values: list) -> int:
    elem_values = field.element_values or []
    builder.StartVector(1, len(values), 1)
    for v in reversed(values):
        idx = elem_values.index(v) if v in elem_values else 0
        builder.PrependByte(idx)
    return builder.EndVector()


def _vector_int32(builder: flatbuffers.Builder, field: FieldDef, values: list) -> int:
    builder.StartVector(4, len(values), 4)
    for v in reversed(values):
        builder.PrependInt32(int(v))
    return builder.EndVector()


def _vector_int64(builder: flatbuffers.Builder, field: FieldDef, values: list) -> int:
    builder.StartVector(8, len(values), 8)
    for v in reversed(values):
        builder.PrependInt64(int(v))
    return builder.EndVector()


def _vector_float(builder: flatbuffers.Builder, field: FieldDef, values: list) -> int:
    builder.StartVector(4, len(values), 4)
    for v in reversed(values):
        builder.PrependFloat32(float(v))
    return builder.EndVector()


def _vector_double(builder: flatbuffers.Builder, field: FieldDef, values: list) -> int:
    builder.StartVector(8, len(values), 8)
    for v in reversed(values):
        builder.PrependFloat64(float(v))
    return builder.EndVector()


def _vector_bool(builder: flatbuffers.Builder, field: FieldDef, values: list) -> int:
    builder.StartVector(1, len(values), 1)
    for v in reversed(values):
        builder.PrependBool(bool(v))
    return builder.EndVector()


_ELEMENT_VECTOR_WRITERS: dict[str, Any] = {
    "string": _vector_strings,
    "enum": _vector_enum,
    "int32": _vector_int32,
    "int64": _vector_int64,
    "float": _vector_float,
    "double": _vector_double,
    "bool": _vector_bool,
}


def _build_string(builder: flatbuffers.Builder, s: str | None) -> int | None:
    if s is None:
        return None
    return builder.CreateString(str(s))


def _build_value(
    builder: flatbuffers.Builder,
    field: FieldDef,
    value: Any,
) -> Any:
    """将一个字段值转换为 FlatBuffers 可用的值或 offset。"""
    if field.type == "string":
        return _build_string(builder, value)
    elif field.type == "enum":
        values = field.values or []
        if value in values:
            return values.index(value)
        return 0
    elif field.type == "struct":
        return _build_struct(builder, field, value or {})
    elif field.type == "array":
        return _build_array(builder, field, value or [])
    else:
        return value


def _build_struct(
    builder: flatbuffers.Builder,
    field: FieldDef,
    data: dict,
) -> int:
    """构建 struct（作为 FlatBuffers table）。"""
    sub_fields = field.fields or []
    # 先构建需要 offset 的字段（string, struct, array）
    offsets: dict[str, Any] = {}
    for sf in sub_fields:
        val = data.get(sf.name)
        if sf.type in _OFFSET_TYPES:
            offsets[sf.name] = _build_value(builder, sf, val)

    num_fields = len(sub_fields)
    builder.StartObject(num_fields)
    for i, sf in enumerate(sub_fields):
        _prepend_slot(builder, i, sf, data.get(sf.name), offsets.get(sf.name))
    return builder.EndObject()


def _build_array(
    builder: flatbuffers.Builder,
    field: FieldDef,
    values: list,
) -> int:
    """构建 array（FlatBuffers vector）。"""
    writer = _ELEMENT_VECTOR_WRITERS.get(field.element)
    if writer is None:
        return 0
    return writer(builder, field, values)


def build_table_bytes(
    rows: list[dict[str, Any]],
    schema: TableSchema,
    exclude_server_only: bool = True,
) -> bytes:
    """将行数据序列化为 FlatBuffers bytes（单表，不含 Bundle 容器）。"""
    builder = flatbuffers.Builder(1024)

    # 构建每一行
    row_offsets: list[int] = []
    for row in rows:
        active_fields = [f for f in schema.fields if not (exclude_server_only and f.server_only)]

        # 先构建所有需要 offset 的字段
        field_offsets: dict[str, Any] = {}
        for f in active_fields:
            val = row.get(f.name)
            if f.type in _OFFSET_TYPES:
                field_offsets[f.name] = _build_value(builder, f, val)

        num_fields = len(active_fields)
        builder.StartObject(num_fields)
        for i, f in enumerate(active_fields):
            _prepend_slot(builder, i, f, row.get(f.name), field_offsets.get(f.name))
        row_offsets.append(builder.EndObject())

    # 构建 items vector
    builder.StartVector(4, len(row_offsets), 4)
    for o in reversed(row_offsets):
        builder.PrependUOffsetTRelative(o)
    items_vec = builder.EndVector()

    # 构建 Table 容器
    builder.StartObject(1)
    builder.PrependUOffsetTRelativeSlot(0, items_vec, 0)
    table_offset = builder.EndObject()

    builder.Finish(table_offset)
    return bytes(builder.Output())


def build_i18n_table_bytes(
    rows: list[dict[str, Any]],
    schema: TableSchema,
) -> bytes:
    """构建 i18n 变体表的 FlatBuffers bytes。"""
    builder = flatbuffers.Builder(1024)
    pk_field = schema.primary_field
    i18n_fields = schema.i18n_fields

    entry_offsets: list[int] = []
    for row in rows:
        # 先构建 string offsets
        str_offsets: dict[str, int] = {}
        for f in i18n_fields:
            val = row.get(f.name, "")
            str_offsets[f.name] = builder.CreateString(str(val) if val else "")

        num_fields = 1 + len(i18n_fields)  # pk + i18n fields
        builder.StartObject(num_fields)
        # pk
        pk_val = row.get(pk_field.name, 0)
        if pk_field.type == "int32":
            builder.PrependInt32Slot(0, int(pk_val), 0)
        elif pk_field.type == "int64":
            builder.PrependInt64Slot(0, int(pk_val), 0)
        # i18n string fields
        for i, f in enumerate(i18n_fields):
            builder.PrependUOffsetTRelativeSlot(1 + i, str_offsets[f.name], 0)
        entry_offsets.append(builder.EndObject())

    # entries vector
    builder.StartVector(4, len(entry_offsets), 4)
    for o in reversed(entry_offsets):
        builder.PrependUOffsetTRelative(o)
    entries_vec = builder.EndVector()

    # I18nTable
    builder.StartObject(1)
    builder.PrependUOffsetTRelativeSlot(0, entries_vec, 0)
    table_offset = builder.EndObject()

    builder.Finish(table_offset)
    return bytes(builder.Output())


def build_bundle(
    table_bytes_map: dict[str, bytes],
) -> bytes:
    """构建 DataBundle，将多张表的 bytes 打包。"""
    builder = flatbuffers.Builder(4096)

    # 构建每个 BundledTable
    bt_offsets: list[int] = []
    for name, data in table_bytes_map.items():
        name_offset = builder.CreateString(name)
        data_offset = builder.CreateByteVector(data)

        builder.StartObject(2)
        builder.PrependUOffsetTRelativeSlot(0, name_offset, 0)
        builder.PrependUOffsetTRelativeSlot(1, data_offset, 0)
        bt_offsets.append(builder.EndObject())

    # tables vector
    builder.StartVector(4, len(bt_offsets), 4)
    for o in reversed(bt_offsets):
        builder.PrependUOffsetTRelative(o)
    tables_vec = builder.EndVector()

    # DataBundle
    builder.StartObject(1)
    builder.PrependUOffsetTRelativeSlot(0, tables_vec, 0)
    bundle_offset = builder.EndObject()

    builder.Finish(bundle_offset)
    return bytes(builder.Output())


def write_primary_bundle(
    all_table_bytes: dict[str, bytes],
    primary_lang: str,
    output_dir: Path,
) -> Path:
    """写入主语言 Bundle。"""
    binary_dir = output_dir / "binary"
    binary_dir.mkdir(parents=True, exist_ok=True)

    bundle_data = build_bundle(all_table_bytes)
    out_path = binary_dir / f"data_{primary_lang}.bin"
    with open(out_path, "wb") as f:
        f.write(bundle_data)

    return out_path


def write_i18n_bundle(
    i18n_table_bytes: dict[str, bytes],
    lang: str,
    output_dir: Path,
) -> Path | None:
    """写入次语言 i18n Bundle。如果没有 i18n 表则返回 None。"""
    if not i18n_table_bytes:
        logger.info(f"所有表均无 i18n 字段，不生成 {lang} 次语言 Bundle")
        return None

    binary_dir = output_dir / "binary"
    binary_dir.mkdir(parents=True, exist_ok=True)

    bundle_data = build_bundle(i18n_table_bytes)
    out_path = binary_dir / f"data_{lang}.bin"
    with open(out_path, "wb") as f:
        f.write(bundle_data)

    return out_path
