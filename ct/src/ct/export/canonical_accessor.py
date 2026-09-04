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

_CSHARP_MAX_LINE = 100  # 表达式体 vs block body 的行长阈值（.NET IDE0022 when_on_single_line 共识）


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


def _csharp_ctor_lines(type_name: str) -> list[str]:
    """Emit an Allman-style constructor body for a row struct."""
    return [
        f"internal {type_name}(IntPtr row, int version)",
        "{",
        "    _row = row;",
        "    _version = version;",
        "}",
    ]


def _csharp_member_lines(type_text: str, name: str, expr: str, indent: int) -> list[str]:
    """Emit one property as lines already indented ``indent`` spaces, choosing
    expression-body vs block-body by final line length (``_CSHARP_MAX_LINE``)."""
    pad = " " * indent
    one_line = f"{pad}public {type_text} {name} => {expr};"
    if len(one_line) <= _CSHARP_MAX_LINE:
        return [one_line]
    return [
        f"{pad}public {type_text} {name}",
        f"{pad}{{",
        f"{pad}    get",
        f"{pad}    {{",
        f"{pad}        return {expr};",
        f"{pad}    }}",
        f"{pad}}}",
    ]


def _indent(lines: list[str], width: int) -> list[str]:
    pad = " " * width
    return [f"{pad}{line}" for line in lines]


def _emit_csharp_field(field: AccessorField, qualified_row: str, indent: int) -> list[str]:
    """Emit one field's accessor as lines indented ``indent`` spaces.
    ``qualified_row`` prefixes a nested row ref at top level (e.g.
    ``ItemAccessor.``); inside the accessor class pass ``""``"""
    slot = _vtable_slot(field)
    if field.kind == "vector":
        # harmony 风格单一容器（NArray<T> / NStructArray<T>）；record 行类型需带 qualified 前缀
        if field.element_kind == "record" and field.record_name:
            container = f"NStructArray<{qualified_row}{field.record_name}Row>"
        elif field.container_text:
            container = field.container_text
        else:
            container = "NArray<int>"
        return _csharp_member_lines(
            container, field.name, f"new {container}(_row, {slot}, _version)", indent
        )
    if field.kind == "record":
        return _csharp_member_lines(
            f"{qualified_row}{field.record_name}Row",
            field.name,
            f"new {qualified_row}{field.record_name}Row(WireReader.Indirect(_row, {slot}), _version)",
            indent,
        )
    reader = _csharp_scalar_reader(field)
    if field.kind == "string":
        # 字符串走 NString（隐式转 string）+ NStringCache 驻留
        return _csharp_member_lines(
            "string",
            field.name,
            f"new NString((byte*)WireReader.Indirect(_row, {slot}), _version)",
            indent,
        )
    if field.kind == "enum":
        return _csharp_member_lines(
            field.type_text,
            field.name,
            f"({field.type_text}){reader}(_row, {slot})",
            indent,
        )
    lines = _csharp_member_lines(
        _csharp_type(field), field.name, f"{reader}(_row, {slot})", indent
    )
    # 跨表 ref：保留裸 id + 类型化访问（目标表 ByID，走 id→行缓存）
    if field.ref_table:
        pad = " " * indent
        lines.append(
            f"{pad}public {field.ref_table}Row? {field.ref_table} => {field.ref_table}Accessor.ByID({field.name});"
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
        lines.extend(_indent(_csharp_ctor_lines(f"{record.name}Row"), 8))
        for field in fields:
            lines.extend(_emit_csharp_field(field, "", 8))
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
    lines.append("        if (p == IntPtr.Zero)")
    lines.append("        {")
    lines.append("            return null;")
    lines.append("        }")
    lines.append("        else")
    lines.append("        {")
    lines.append(f"            return new {table}Row(p, Runtime.Version(TableName));")
    lines.append("        }")
    lines.append("    }")
    lines.append("")
    lines.append("    /// <summary>按 Excel 序行下标取行；越界返回 null。</summary>")
    lines.append(f"    public static {table}Row? ByIndex(int i)")
    lines.append("    {")
    lines.append("        IntPtr p = Runtime.RowAt(TableName, i);")
    lines.append("        if (p == IntPtr.Zero)")
    lines.append("        {")
    lines.append("            return null;")
    lines.append("        }")
    lines.append("        else")
    lines.append("        {")
    lines.append(f"            return new {table}Row(p, Runtime.Version(TableName));")
    lines.append("        }")
    lines.append("    }")
    for index in model.indexes:
        if index.kind == "code":
            lines.append("")
            lines.append("    /// <summary>Exact-string Code lookup; returns null when missing.</summary>")
            lines.append(f"    public static {table}Row? ByCode(string code)")
            lines.append("    {")
            lines.append(f"        int row = Runtime.ByCode(TableName, {index.slot}, code);")
            lines.append("        if (row < 0)")
            lines.append("        {")
            lines.append("            return null;")
            lines.append("        }")
            lines.append("        else")
            lines.append("        {")
            lines.append(f"            return new {table}Row(Runtime.RowAt(TableName, row), Runtime.Version(TableName));")
            lines.append("        }")
            lines.append("    }")
        else:
            lines.append("")
            lines.append("    /// <summary>Group lookup; returns rows in deterministic order.</summary>")
            lines.append(f"    public static IReadOnlyList<{table}Row> ByGroupKey(int value)")
            lines.append("    {")
            lines.append(f"        var rows = Runtime.GroupKey(TableName, {index.slot}, value);")
            lines.append(f"        var result = new List<{table}Row>(rows.Length);")
            lines.append("        foreach (var row in rows)")
            lines.append("        {")
            lines.append(f"            result.Add(new {table}Row(Runtime.RowAt(TableName, row), Runtime.Version(TableName)));")
            lines.append("        }")
            lines.append("        return result;")
            lines.append("    }")
    return lines


def generate_csharp_accessor(model: CanonicalAccessorModel) -> str:
    table = model.table.table
    lines: list[str] = []
    lines.append("// <auto-generated/>")
    lines.append(f"// Canonical C# accessor for {table}")
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
    lines.extend(_indent(_csharp_ctor_lines(f"{table}Row"), 4))
    qualified = f"{table}Accessor."
    for field in model.client_fields:
        lines.extend(_emit_csharp_field(field, qualified_row=qualified, indent=4))
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


def _lua_vector_parts(field) -> tuple[str, str, bool]:
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


def _lua_vector_body(field: AccessorField) -> str:
    """Return the one-line body of a vector accessor (``local n ... return out``)."""
    count_reader, at_reader, is_record = _lua_vector_parts(field)
    if is_record:
        return (
            f"local n = {count_reader}(_tbl, {field.slot}, s) local out = {{}} "
            f"for i = 1, n do out[i] = setmetatable("
            f"{{_row = {at_reader}(_tbl, {field.slot}, s, i - 1)}}, {field.record_name}Meta) end "
            f"return out"
        )
    return (
        f"local n = {count_reader}(_tbl, {field.slot}, s) local out = {{}} "
        f"for i = 1, n do out[i] = {at_reader}(_tbl, {field.slot}, s, i - 1) end "
        f"return out"
    )


def _lua_member_lines(field: AccessorField, indent: str) -> list[str]:
    """Emit one Lua accessor entry as single-line(s) (compact rowmeta style).

    A cross-table ref emits two lines — the bare id and the typed lookup —
    matching C# so the raw id is never dropped.
    """
    if field.kind == "vector":
        return [f"{indent}{field.name} = function(s) {_lua_vector_body(field)} end,"]
    if field.kind == "record":
        return [
            f"{indent}{field.name} = function(s) return setmetatable("
            f"{{_row = GD.Rec(_tbl, {field.slot}, s)}}, {field.record_name}Meta) end,",
        ]
    reader = _lua_reader(field)
    if field.kind == "bool":
        return [
            f"{indent}{field.name} = function(s) return {reader}(_tbl, {field.slot}, s) ~= 0 end,",
        ]
    lines = [
        f"{indent}{field.name} = function(s) return {reader}(_tbl, {field.slot}, s) end,",
    ]
    if field.ref_table:
        lines.append(
            f"{indent}{field.ref_table} = function(s) local rid = {reader}(_tbl, {field.slot}, s) "
            f"return {field.ref_table}Accessor.ByID(rid) end,"
        )
    return lines


def _emit_lua_record_metas(model: CanonicalAccessorModel) -> list[str]:
    """Emit one `{Record}Meta` metatable per referenced record."""
    lines: list[str] = []
    for record in referenced_records(model):
        fields = record_accessor_fields(record, model.records)
        lines.append(f"local {record.name}Meta = {{")
        for field in fields:
            lines.extend(_lua_member_lines(field, "  "))
        lines.append("}")
        lines.append("")
    return lines


def generate_lua_accessor(model: CanonicalAccessorModel) -> str:
    table = model.table.table
    lines: list[str] = []
    lines.append(f"-- Auto-generated canonical Lua accessor for {table}")
    lines.append('local GD = require("gd")')
    lines.append(f"local _tbl = \"{table}\"")
    lines.append("")
    # record metatables first (referenced by RowMeta)
    record_metas = _emit_lua_record_metas(model)
    if record_metas:
        lines.extend(record_metas)
    lines.append("local RowMeta = {")
    for field in model.client_fields:
        lines.extend(_lua_member_lines(field, "  "))
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
