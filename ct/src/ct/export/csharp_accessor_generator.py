"""Generate {Table}Accessor.cs files for each config table.

生成器产出**行模式访问器**（design D6），零第三方依赖（不引用
Google.FlatBuffers / flatc 类型）：

- ``{Table}Accessor`` 静态类：窗口（``_table``/``_i18nTable`` IntPtr）+
  预缓存 items 基址（``_itemsBase``）+ 行指针缓存（``_rowPtrs``）；
  ``EnsureLoaded`` 由加载点失效信号（ConfigAccessors）驱动，本地判断零 P/Invoke
- ``{Table}Row`` readonly struct：行指针 + epoch 校验（等价 Lua check_ud），
  属性先 ``EnsureFresh`` 再经 ``WireReader`` 指针直读
- struct 字段：``{Struct}View`` readonly struct（指针 + epoch）
- i18n：``WireReader.SearchEntry`` 二分 i18n entries，未命中兜底原文

slot = vtable 槽位 = 4 + 2*字段序（与原生 C / Lua 读取器一致）。
"""

from __future__ import annotations

from pathlib import Path

from ct.export.accessor_model import build_accessor_model
from ct.schema.models import FieldDef, TableSchema

# 标量字段 → WireReader 方法 + C# 返回类型
_SCALAR_READERS = {
    "int32": ("I32", "int"),
    "int64": ("I64", "long"),
    "float": ("F32", "float"),
    "double": ("F64", "double"),
    "enum": ("I8", "byte"),
    "bool": ("Bool", "bool"),
}
# 数组元素 → WireReader 元素读取方法
_ARR_READERS = {
    "int32": "ArrI32",
    "int64": "ArrI64",
    "float": "ArrF32",
    "double": "ArrF64",
    "bool": "ArrBool",
    "string": "ArrStr",
    "enum": "ArrI8",
}


def _slot(idx: int) -> int:
    """vtable 槽位 = 4 + 2*字段序（flatbuffers 约定）。"""
    return 4 + 2 * idx


def _row_prop_type(f: FieldDef) -> str:
    if f.type == "string":
        return "string"
    if f.type == "struct":
        return f"{f.name}View"
    if f.type == "array":
        return ""  # 数组不生成单属性，拆 Count/At
    return _SCALAR_READERS[f.type][1]


def _arr_elem_type(f: FieldDef) -> str:
    if f.element == "string":
        return "string"
    if f.element == "enum":
        return "byte"
    return _SCALAR_READERS.get(f.element, ("", "int"))[1]


def _gen_row_property(
    f: FieldDef,
    slot: int,
    pk_slot: int,
    i18n_slot: int | None = None,
    accessor_name: str = "",
) -> list[str]:
    """产出 ItemRow 的一个属性（含 EnsureFresh 先行）。

    ``pk_slot`` 主表主键槽位（i18n 查询用）；``i18n_slot`` i18n entry 内
    目标字段槽位（entry 布局：pk 槽位 0，i18n 字段从槽位 1 起）。
    """
    if f.type == "array":  # 数组拆 Count/At 两个成员，不输出单属性头
        elem = _ARR_READERS.get(f.element, "ArrI32")
        return [
            f"    public int {f.name}Count {{ get {{ EnsureFresh(); return WireReader.ArrLen(_row, {slot}); }} }}",
            f"    public {_arr_elem_type(f)} {f.name}At(int i) {{ EnsureFresh(); return WireReader.{elem}(_row, {slot}, i); }}",
        ]
    lines = [f"    public {_row_prop_type(f)} {f.name}"]
    if f.type == "string":
        if f.i18n:
            lines += [
                "    {",
                "        get",
                "        {",
                "            EnsureFresh();",
                "            var entry = WireReader.SearchEntry(" + accessor_name + ".I18nTable, WireReader.I32(_row, " + str(pk_slot) + "), 4);",
                "            if (entry != IntPtr.Zero)",
                "            {",
                "                var v = WireReader.Str(entry, " + str(i18n_slot) + ");",
                "                if (v != null) return v;",
                "            }",
                f"            return WireReader.Str(_row, {slot});",
                "        }",
                "    }",
            ]
        else:
            lines += [
                "    {",
                "        get",
                "        {",
                "            EnsureFresh();",
                f"            return WireReader.Str(_row, {slot});",
                "        }",
                "    }",
            ]
    elif f.type == "struct":
        lines += [
            "    {",
            "        get",
            "        {",
            "            EnsureFresh();",
            f"            return new {f.name}View(WireReader.Indirect(_row, {slot}));",
            "        }",
            "    }",
        ]
    elif f.type == "array":
        elem = _ARR_READERS.get(f.element, "ArrI32")
        lines += [
            f"    public int {f.name}Count {{ get {{ EnsureFresh(); return WireReader.ArrLen(_row, {slot}); }} }}",
            f"    public {_arr_elem_type(f)} {f.name}At(int i) {{ EnsureFresh(); return WireReader.{elem}(_row, {slot}, i); }}",
        ]
    else:
        method, _ = _SCALAR_READERS[f.type]
        lines += [
            "    {",
            "        get",
            "        {",
            "            EnsureFresh();",
            f"            return WireReader.{method}(_row, {slot});",
            "        }",
            "    }",
        ]
    return lines


def generate_csharp_accessor(schema: TableSchema, output_dir: Path) -> Path:
    """Generate ``{Table}Accessor.cs`` and write it to *output_dir*."""
    model = build_accessor_model(schema)
    output_dir.mkdir(parents=True, exist_ok=True)

    table_pascal = schema.table
    class_name = f"{table_pascal}Accessor"
    row_name = f"{table_pascal}Row"
    client_fields: list[FieldDef] = model.client_fields
    pk_idx = next(i for i, f in enumerate(client_fields) if f.name == schema.primary)
    pk_slot = _slot(pk_idx)

    lines: list[str] = []
    w = lines.append

    # -- file header ----------------------------------------------------------
    w("// <auto-generated/>")
    w("// Generated by ct/export/csharp_accessor_generator.py -- DO NOT EDIT")
    w("")
    w("using System;")
    w("")
    w(f"public static class {class_name}")
    w("{")
    w("    private static IntPtr _table;        // 当前世代子表窗口")
    if schema.has_i18n:
        w(f"    private static IntPtr _i18nTable;   // 可为零（zh 无 i18n）")
    w("    private static IntPtr _itemsBase;    // 预缓存 items 向量基址")
    w("    private static IntPtr[] _rowPtrs;    // 行指针缓存（idx → 指针，懒填充）")
    w("")
    w("    static " + class_name + "()")
    w("    {")
    w("        ConfigAccessors.Register(Invalidate);")
    w("    }")
    w("")
    w("    private static void Invalidate()      // 加载点推送：清窗口 + 清行指针缓存")
    w("    {")
    w("        _table = IntPtr.Zero;")
    if schema.has_i18n:
        w("        _i18nTable = IntPtr.Zero;")
    w("        _rowPtrs = null;")
    w("    }")
    w("")
    w("    private static void EnsureLoaded()    // 本地判断（零 P/Invoke）")
    w("    {")
    w("        if (_table == IntPtr.Zero)")
    w("        {")
    w(f'            _table = GDNative.FindTable("{schema.table}");')
    if schema.has_i18n:
        w(f'            _i18nTable = GDNative.FindTableI18n("{schema.table}_i18n");')
    w("            if (_table == IntPtr.Zero)              // 主表缺失（异常态）：空窗口兜底")
    w("            {")
    w("                _rowPtrs = Array.Empty<IntPtr>();")
    w("                return;")
    w("            }")
    w("            _itemsBase = WireReader.VectorBase(_table);")
    w("            _rowPtrs = new IntPtr[WireReader.Count(_table)];")
    w("        }")
    w("    }")
    w("")
    w("    private static IntPtr RowPtr(int idx) // 行指针缓存：命中零解析")
    w("    {")
    w("        var p = _rowPtrs[idx];")
    w("        if (p == IntPtr.Zero) { p = WireReader.RowAt(_itemsBase, idx); _rowPtrs[idx] = p; }")
    w("        return p;")
    w("    }")
    w("")
    if schema.has_i18n:
        w("    internal static IntPtr I18nTable => _i18nTable;")
        w("")
    w("    public static int Count { get { EnsureLoaded(); return _rowPtrs.Length; } }")
    w("")
    w("    /// <summary>按主键查行；未找到返回 null。</summary>")
    w("    public static " + row_name + "? ByID(int id)")
    w("    {")
    w("        EnsureLoaded();")
    w("        int idx = WireReader.IndexSearch(_table, id);")
    w("        return idx < 0 ? (" + row_name + "?)null : new " + row_name + "(RowPtr(idx));")
    w("    }")
    w("")
    w("    /// <summary>按 Excel 序行下标取行。i 越界（&lt;0 或 ≥Count）抛 IndexOutOfRangeException。</summary>")
    w("    public static " + row_name + " ByIndex(int i)")
    w("    {")
    w("        EnsureLoaded();")
    w("        return new " + row_name + "(RowPtr(i));")
    w("    }")
    w("}")
    w("")
    w("// ---- 行对象：值类型零堆分配；epoch 校验等价 Lua check_ud ----")
    w(f"public readonly struct {row_name}")
    w("{")
    w("    private readonly IntPtr _row;")
    w("    private readonly int _epoch;")
    w(f"    internal {row_name}(IntPtr row) {{ _row = row; _epoch = ConfigAccessors.Epoch; }}")
    w("")
    w("    private void EnsureFresh()")
    w("    {")
    w("        if (_epoch != ConfigAccessors.Epoch)")
    w("            throw new InvalidOperationException(")
    w('                "[Config] stale row (language switched), re-fetch via ByID/ByIndex");')
    w("    }")
    w("")
    for i, f in enumerate(client_fields):
        i18n_slot = None
        if f.type == "string" and f.i18n:
            # i18n entry：pk 槽位 0，i18n 字段从槽位 1 起 → slot = 4+2*(1+j)
            j = model.i18n_fields.index(f)
            i18n_slot = _slot(1 + j)
        for line in _gen_row_property(f, _slot(i), pk_slot, i18n_slot, class_name):
            w(line)
        w("")
    w("}")
    w("")

    # -- struct 视图（每个 struct 字段一个）-----------------------------------
    for f in client_fields:
        if f.type == "struct" and f.fields:
            w(f"// ---- struct 视图（{f.name}）----")
            w(f"public readonly struct {f.name}View")
            w("{")
            w("    private readonly IntPtr _p;")
            w("    private readonly int _epoch;")
            w(f"    internal {f.name}View(IntPtr p) {{ _p = p; _epoch = ConfigAccessors.Epoch; }}")
            w("")
            w("    private void EnsureFresh()")
            w("    {")
            w("        if (_epoch != ConfigAccessors.Epoch)")
            w('            throw new InvalidOperationException("[Config] stale view (language switched)");')
            w("    }")
            w("")
            for i, sf in enumerate(f.fields):
                method, cs_type = _SCALAR_READERS.get(sf.type, ("I32", "int"))
                w(f"    public {cs_type} {sf.name} {{ get {{ EnsureFresh(); return WireReader.{method}(_p, {_slot(i)}); }} }}")
            w("}")
            w("")

    out_path = output_dir / f"{class_name}.cs"
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))

    return out_path
