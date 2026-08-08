from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import flatbuffers

from ct.schema.models import FieldDef, TableSchema

logger = logging.getLogger(__name__)




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
    # 先构建需要 offset 的字段（string, struct, array, vector）
    offsets: dict[str, Any] = {}
    for sf in sub_fields:
        val = data.get(sf.name)
        if sf.type in ("string", "struct", "array"):
            offsets[sf.name] = _build_value(builder, sf, val)

    num_fields = len(sub_fields)
    builder.StartObject(num_fields)
    for i, sf in enumerate(sub_fields):
        val = data.get(sf.name)
        if sf.type == "string":
            if offsets.get(sf.name) is not None:
                builder.PrependUOffsetTRelativeSlot(i, offsets[sf.name], 0)
        elif sf.type == "struct":
            if offsets.get(sf.name) is not None:
                builder.PrependUOffsetTRelativeSlot(i, offsets[sf.name], 0)
        elif sf.type == "array":
            if offsets.get(sf.name) is not None:
                builder.PrependUOffsetTRelativeSlot(i, offsets[sf.name], 0)
        elif sf.type == "enum":
            values = sf.values or []
            idx = values.index(val) if val in values else 0
            builder.PrependInt8Slot(i, idx, 0)
        elif sf.type == "bool":
            builder.PrependBoolSlot(i, bool(val) if val is not None else False, False)
        elif sf.type in ("int32",):
            builder.PrependInt32Slot(i, int(val) if val is not None else 0, 0)
        elif sf.type in ("int64",):
            builder.PrependInt64Slot(i, int(val) if val is not None else 0, 0)
        elif sf.type in ("float",):
            builder.PrependFloat32Slot(i, float(val) if val is not None else 0.0, 0.0)
        elif sf.type in ("double",):
            builder.PrependFloat64Slot(i, float(val) if val is not None else 0.0, 0.0)
    return builder.EndObject()


def _build_array(
    builder: flatbuffers.Builder,
    field: FieldDef,
    values: list,
) -> int:
    """构建 array（FlatBuffers vector）。"""
    if field.element == "string":
        str_offsets = [builder.CreateString(str(v)) for v in values]
        builder.StartVector(4, len(str_offsets), 4)
        for o in reversed(str_offsets):
            builder.PrependUOffsetTRelative(o)
        return builder.EndVector()
    elif field.element == "enum":
        elem_values = field.element_values or []
        builder.StartVector(1, len(values), 1)
        for v in reversed(values):
            idx = elem_values.index(v) if v in elem_values else 0
            builder.PrependByte(idx)
        return builder.EndVector()
    elif field.element in ("int32",):
        builder.StartVector(4, len(values), 4)
        for v in reversed(values):
            builder.PrependInt32(int(v))
        return builder.EndVector()
    elif field.element in ("int64",):
        builder.StartVector(8, len(values), 8)
        for v in reversed(values):
            builder.PrependInt64(int(v))
        return builder.EndVector()
    elif field.element in ("float",):
        builder.StartVector(4, len(values), 4)
        for v in reversed(values):
            builder.PrependFloat32(float(v))
        return builder.EndVector()
    elif field.element in ("double",):
        builder.StartVector(8, len(values), 8)
        for v in reversed(values):
            builder.PrependFloat64(float(v))
        return builder.EndVector()
    elif field.element in ("bool",):
        builder.StartVector(1, len(values), 1)
        for v in reversed(values):
            builder.PrependBool(bool(v))
        return builder.EndVector()
    else:
        return 0


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
        field_offsets: dict[str, Any] = {}
        active_fields = [f for f in schema.fields if not (exclude_server_only and f.server_only)]

        # 先构建所有需要 offset 的字段
        for f in active_fields:
            val = row.get(f.name)
            if f.type in ("string", "struct", "array"):
                field_offsets[f.name] = _build_value(builder, f, val)

        num_fields = len(active_fields)
        builder.StartObject(num_fields)
        for i, f in enumerate(active_fields):
            val = row.get(f.name)
            if f.type == "string":
                if field_offsets.get(f.name) is not None:
                    builder.PrependUOffsetTRelativeSlot(i, field_offsets[f.name], 0)
            elif f.type in ("struct", "array"):
                if field_offsets.get(f.name) is not None:
                    builder.PrependUOffsetTRelativeSlot(i, field_offsets[f.name], 0)
            elif f.type == "enum":
                values = f.values or []
                idx = values.index(val) if val in values else 0
                builder.PrependInt8Slot(i, idx, 0)
            elif f.type == "bool":
                builder.PrependBoolSlot(i, bool(val) if val is not None else False, False)
            elif f.type == "int32":
                builder.PrependInt32Slot(i, int(val) if val is not None else 0, 0)
            elif f.type == "int64":
                builder.PrependInt64Slot(i, int(val) if val is not None else 0, 0)
            elif f.type == "float":
                builder.PrependFloat32Slot(i, float(val) if val is not None else 0.0, 0.0)
            elif f.type == "double":
                builder.PrependFloat64Slot(i, float(val) if val is not None else 0.0, 0.0)
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
