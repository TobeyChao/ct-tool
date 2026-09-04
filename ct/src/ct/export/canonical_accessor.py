"""C# / Lua accessor emitters for the canonical model.

Emit deterministic row accessors plus the table-level Code/Group query APIs.
Both languages expose the same method names and missing/ordering semantics;
the actual binary traversal delegates to the platform reader (WireReader /
GD). This text is a format-contract surface and is verified by golden tests.

Wire contract for nested ``record`` fields (FlatBuffers stores a record as a
nested table at an offset):
- C#: ``WireReader.Rec(table, slot, row)`` returns the sub-table offset (int);
  ``WireReader.RecVec(table, slot, row, i)`` returns the i-th element offset.
  The returned offset is passed back into the scalar readers
  (``WireReader.I32(table, subSlot, offset)``) exactly like a row index.
- Lua: ``GD.Rec(table, slot, row)`` and ``GD.RecVec(table, slot, row, i)``
  return the sub-table offset; ``GD.I32(table, subSlot, offset)`` reads it.

Vector element readers:
- C#: ``VecLen`` for count; ``VecI32/VecI64/VecF32/VecF64/VecBool`` for scalars,
  ``VecStr`` for strings, ``VecI8`` for enum bytes, ``RecVec`` for records.
- Lua: ``GD.VecLen`` for count; ``GD.VecI32/VecI64/VecF32/VecF64/VecBool`` /
  ``GD.VecStr`` / ``GD.VecI8`` / ``GD.RecVec`` for elements.
"""

from __future__ import annotations

from ct.export.canonical_accessor_model import (
    AccessorField,
    CanonicalAccessorModel,
    build_accessor_model,
    record_accessor_fields,
    referenced_records,
)
from ct.schema.indexes import QueryIndex


# ---------------------------------------------------------------- C# helpers


def _vtable_slot(field: AccessorField) -> int:
    """FlatBuffers vtable slot = 4 + 2*字段序（与指针式 reader 一致）。"""
    return 4 + 2 * field.slot


def _csharp_scalar_reader(field: AccessorField) -> str:
    if field.kind == "string":
        return "WireReader.Str"
    if field.kind == "scalar":
        return {
            "int32": "WireReader.I32",
            "int64": "WireReader.I64",
            "float": "WireReader.F32",
            "double": "WireReader.F64",
            "bool": "WireReader.Bool",
        }.get(field.type_text, "WireReader.I32")
    return "WireReader.I8"  # enum


def _csharp_type(field: AccessorField) -> str:
    if field.kind == "string":
        return "string"
    if field.kind == "scalar":
        return {
            "int32": "int",
            "int64": "long",
            "float": "float",
            "double": "double",
            "bool": "bool",
        }.get(field.type_text, "int")
    return "int"  # enum (byte wire, exposed as int)


def _emit_csharp_field(field: AccessorField, qualified_row: str, nested: bool) -> list[str]:
    """Emit one field's accessor lines. ``qualified_row`` prefixes a nested row ref
    at top level (e.g. ``ItemAccessor.``); inside the accessor class use ``""``"""
    slot = _vtable_slot(field)
    if field.kind == "vector":
        # harmony 风格单一容器（NArray<T> / NStructArray<T>）；record 行类型需带 qualified 前缀
        if field.element_kind == "record" and field.record_name:
            container = f"NStructArray<{qualified_row}{field.record_name}Row>"
        elif field.container_text:
            container = field.container_text
        else:
            container = "NArray<int>"
        return [
            f"    public {container} {field.name} => new {container}(_row, {slot}, _version);",
        ]
    if field.kind == "record":
        return [
            f"    public {qualified_row}{field.record_name}Row {field.name} => "
            f"new {qualified_row}{field.record_name}Row(WireReader.Indirect(_row, {slot}), _version);",
        ]
    reader = _csharp_scalar_reader(field)
    if field.kind == "string":
        # 字符串走 NString（隐式转 string）+ NStringCache 驻留
        return [
            f"    public string {field.name} => new NString((byte*)WireReader.Indirect(_row, {slot}), _version);",
        ]
    if field.kind == "enum":
        return [
            f"    public {field.type_text} {field.name} => ({field.type_text}){reader}(_row, {slot});",
        ]
    lines = [
        f"    public {_csharp_type(field)} {field.name} => {reader}(_row, {slot});",
    ]
    # 跨表 ref：保留裸 id + 类型化访问（目标表 ByID，走 id→行缓存）
    if field.ref_table:
        lines.append(
            f"    public {field.ref_table}Row? {field.ref_table} => {field.ref_table}Accessor.ByID({field.name});"
        )
    return lines


def _emit_csharp_record_structs(model: CanonicalAccessorModel) -> list[str]:
    """Emit nested ``{Record}Row`` structs for every referenced record."""
    lines: list[str] = []
    for record in referenced_records(model):
        fields = record_accessor_fields(record, model.records)
        lines.append(f"    public unsafe readonly struct {record.name}Row")
        lines.append("    {")
        lines.append("        private readonly IntPtr _row;")
        lines.append("        private readonly int _version;")
        lines.append(f"        internal {record.name}Row(IntPtr row, int version) {{ _row = row; _version = version; }}")
        for field in fields:
            for line in _emit_csharp_field(field, qualified_row="", nested=True):
                lines.append(line.replace("    ", "        ", 1))
        lines.append("    }")
        lines.append("")
    return lines


def _emit_csharp_query_api(model: CanonicalAccessorModel) -> list[str]:
    """Emit per-table Count/ByID/ByIndex (+ ByCode/ByGroupKey if indexes)."""
    table = model.table.table
    lines: list[str] = []
    lines.append(f"    private const string TableName = \"{table}\";")
    lines.append("    /// <summary>行数。</summary>")
    lines.append("    public static int Count => Runtime.Count(TableName);")
    lines.append("")
    lines.append("    /// <summary>按主键查行；未找到返回 null。</summary>")
    lines.append(f"    public static {table}Row? ByID(int id)")
    lines.append("    {")
    lines.append("        IntPtr p = Runtime.ByID(TableName, id);")
    lines.append(f"        return p == IntPtr.Zero ? ({table}Row?)null : new {table}Row(p, Runtime.Version(TableName));")
    lines.append("    }")
    lines.append("")
    lines.append("    /// <summary>按 Excel 序行下标取行。</summary>")
    lines.append(f"    public static {table}Row ByIndex(int i) => new {table}Row(Runtime.RowAt(TableName, i), Runtime.Version(TableName));")
    for index in model.indexes:
        if index.kind == "code":
            lines.append("")
            lines.append("    /// <summary>Exact-string Code lookup; returns null when missing.</summary>")
            lines.append(f"    public static {table}Row? ByCode(string code)")
            lines.append("    {")
            lines.append(f"        int row = Runtime.ByCode(TableName, {index.slot}, code);")
            lines.append(f"        return row < 0 ? ({table}Row?)null : new {table}Row(Runtime.RowAt(TableName, row), Runtime.Version(TableName));")
            lines.append("    }")
        else:
            lines.append("")
            lines.append("    /// <summary>Group lookup; returns rows in deterministic order.</summary>")
            lines.append(f"    public static IReadOnlyList<{table}Row> ByGroupKey(int value)")
            lines.append("    {")
            lines.append(f"        var rows = Runtime.GroupKey(TableName, {index.slot}, value);")
            lines.append(f"        var result = new List<{table}Row>(rows.Length);")
            lines.append("        foreach (var row in rows) result.Add(new " + table + "Row(Runtime.RowAt(TableName, row), Runtime.Version(TableName)));")
            lines.append("        return result;")
            lines.append("    }")
    return lines


def generate_csharp_accessor(model: CanonicalAccessorModel) -> str:
    table = model.table.table
    lines: list[str] = []
    lines.append("// <auto-generated/>")
    lines.append(f"// Canonical C# accessor for {table} ()")
    lines.append("using System;")
    lines.append("using System.Collections.Generic;")
    lines.append("")
    lines.append(f"public static partial class {table}Accessor")
    lines.append("{")
    lines.extend(_emit_csharp_query_api(model))
    record_structs = _emit_csharp_record_structs(model)
    if record_structs:
        lines.append("")
        lines.extend(record_structs)
    lines.append("}")
    lines.append("")
    lines.append(f"public unsafe readonly struct {table}Row")
    lines.append("{")
    lines.append("    private readonly IntPtr _row;")
    lines.append("    private readonly int _version;")
    lines.append(f"    internal {table}Row(IntPtr row, int version) {{ _row = row; _version = version; }}")
    qualified = f"{table}Accessor."
    for field in model.client_fields:
        for line in _emit_csharp_field(field, qualified_row=qualified, nested=False):
            lines.append(line)
    lines.append("}")
    return "\n".join(lines)


# ---------------------------------------------------------------- Lua helpers


def _lua_reader(field: AccessorField) -> str:
    if field.kind == "string":
        return "GD.Str"
    if field.kind == "scalar":
        return {
            "int32": "GD.I32",
            "int64": "GD.I64",
            "float": "GD.F32",
            "double": "GD.F64",
            "bool": "GD.I8",
        }.get(field.type_text, "GD.I32")
    return "GD.I8"  # enum (byte wire)


def _lua_vec(field: AccessorField) -> tuple[str, str, bool]:
    if field.element_kind == "record":
        return "GD.VecLen", "GD.RecVec", True
    if field.element_kind == "string":
        return "GD.VecLen", "GD.VecStr", False
    if field.element_kind == "enum":
        return "GD.VecLen", "GD.VecI8", False
    return {
        "int32": ("GD.VecLen", "GD.VecI32", False),
        "int64": ("GD.VecLen", "GD.VecI64", False),
        "float": ("GD.VecLen", "GD.VecF32", False),
        "double": ("GD.VecLen", "GD.VecF64", False),
        "bool": ("GD.VecLen", "GD.VecBool", False),
    }.get(field.element_type, ("GD.VecLen", "GD.VecI32", False))


def _lua_vector_body(field) -> str:
    """Return the body of a vector accessor (`local n ... return out`)."""
    count_reader, at_reader, is_record = _lua_vec(field)
    if is_record:
        return (
            f"local n = {count_reader}(_tbl, {field.slot}, s) local out = {{}} "
            f"for i = 1, n do out[i] = setmetatable({{_row = {at_reader}(_tbl, {field.slot}, s, i - 1)}}, "
            f"{field.record_name}Meta) end return out"
        )
    return (
        f"local n = {count_reader}(_tbl, {field.slot}, s) local out = {{}} "
        f"for i = 1, n do out[i] = {at_reader}(_tbl, {field.slot}, s, i - 1) end return out"
    )


def _emit_lua_record_metas(model: CanonicalAccessorModel) -> list[str]:
    """Emit one `{Record}Meta` metatable per referenced record."""
    lines: list[str] = []
    for record in referenced_records(model):
        fields = record_accessor_fields(record, model.records)
        lines.append(f"local {record.name}Meta = {{")
        for field in fields:
            if field.kind == "vector":
                lines.append(f"  {field.name} = function(s) {_lua_vector_body(field)} end,")
            elif field.kind == "record":
                lines.append(
                    f"  {field.name} = function(s) return setmetatable({{_row = GD.Rec(_tbl, {field.slot}, s)}}, {field.record_name}Meta) end,"
                )
            else:
                reader = _lua_reader(field)
                if field.kind == "bool":
                    lines.append(
                        f"  {field.name} = function(s) return {reader}(_tbl, {field.slot}, s) ~= 0 end,"
                    )
                else:
                    lines.append(
                        f"  {field.name} = function(s) return {reader}(_tbl, {field.slot}, s) end,"
                    )
        lines.append("}")
        lines.append("")
    return lines


def generate_lua_accessor(model: CanonicalAccessorModel) -> str:
    table = model.table.table
    lines: list[str] = []
    lines.append(f"-- Auto-generated canonical Lua accessor for {table} ()")
    lines.append('local GD = require("gd")')
    lines.append(f"local _tbl = \"{table}\"")
    lines.append("")
    # record metatables first (referenced by RowMeta)
    record_metas = _emit_lua_record_metas(model)
    if record_metas:
        lines.extend(record_metas)
    lines.append("local RowMeta = {")
    for field in model.client_fields:
        if field.kind == "vector":
            lines.append(f"  {field.name} = function(s) {_lua_vector_body(field)} end,")
        elif field.kind == "record":
            lines.append(
                f"  {field.name} = function(s) return setmetatable({{_row = GD.Rec(_tbl, {field.slot}, s)}}, {field.record_name}Meta) end,"
            )
        elif field.kind == "bool":
            lines.append(
                f"  {field.name} = function(s) return GD.I8(_tbl, {field.slot}, s) ~= 0 end,"
            )
        elif field.kind == "string":
            lines.append(f"  {field.name} = function(s) return GD.Str(_tbl, {field.slot}, s) end,")
        else:
            reader = _lua_reader(field)
            lines.append(f"  {field.name} = function(s) return {reader}(_tbl, {field.slot}, s) end,")
            # 跨表 ref：类型化查找（目标表 accessor 的 ByID）
            if field.ref_table:
                lines.append(f"  {field.ref_table} = function(s) local rid = {reader}(_tbl, {field.slot}, s) return {field.ref_table}Accessor.ByID(rid) end,")
    lines.append("}")
    lines.append("")
    lines.append("local M = {}")
    for index in model.indexes:
        if index.kind == "code":
            lines.append("-- exact-string Code lookup; nil when missing")
            lines.append(f"function M.ByCode(code) local row = GD.IndexCode(_tbl, {index.slot}, code) if row < 0 then return nil end return setmetatable({{_row = row}}, RowMeta) end")
        else:
            lines.append("-- Group lookup; returns rows in deterministic order")
            lines.append(f"function M.ByGroupKey(value) local rows = GD.IndexGroup(_tbl, {index.slot}, value) local out = {{}} for i = 1, #rows do out[i] = setmetatable({{_row = rows[i]}}, RowMeta) end return out end")
    lines.append(f"function M.Count() return GD.Count(_tbl) end")
    lines.append(f"function M.ByIndex(i) return setmetatable({{_row = GD.ByIndex(_tbl, i)}}, RowMeta) end")
    lines.append(f"function M.ByID(id) return setmetatable({{_row = GD.ByID(_tbl, id)}}, RowMeta) end")
    lines.append("return M")
    return "\n".join(lines)


# ---------------------------------------------------------------- public render


def render_csharp_accessor(table, indexes, records=None) -> str:
    return generate_csharp_accessor(build_accessor_model(table, indexes, records=records))


def render_lua_accessor(table, indexes, records=None) -> str:
    return generate_lua_accessor(build_accessor_model(table, indexes, records=records))


def _table():
    from ct.schema.resources import TableResource, FieldDef

    return TableResource(
        table="Item",
        primary="Id",
        fields=[
            FieldDef(name="Id", type="int32"),
            FieldDef(name="CodeName", type="string"),
            FieldDef(name="Category", type="int32"),
        ],
    )


def golden_csharp(table=None, indexes=None, records=None) -> str:
    if table is None:
        table = _table()
    if indexes is None:
        indexes = (QueryIndex(kind="code", field="CodeName"), QueryIndex(kind="group", field="Category"))
    return render_csharp_accessor(table, indexes, records=records)


def golden_lua(table=None, indexes=None, records=None) -> str:
    if table is None:
        table = _table()
    if indexes is None:
        indexes = (QueryIndex(kind="code", field="CodeName"), QueryIndex(kind="group", field="Category"))
    return render_lua_accessor(table, indexes, records=records)
