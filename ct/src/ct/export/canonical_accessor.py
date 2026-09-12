"""C# / Lua accessor emitters for the canonical model.

Emit deterministic row accessors plus the table-level CodeName query API.
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

_CSHARP_MAX_LINE = 100  # 一行式 vs 展开块体的行长阈值（.NET IDE0022 when_on_single_line 共识）

#: 行 / record getter 的开发期世代守卫条件。**必须**与
#: `Client/Assets/Scripts/Config/Native/ConfigRuntime.cs::TableVersion.Check` 内的条件一致。
#:
#: 生成物里用 `#if` **源码级**包住守卫，而不是发射一个「发布期为空」的 Check 调用 ——
#: 后者看着更干净，但实测会让一部分 getter 失去内联资格：同一份基准、同会话交替 A/B，
#: B3 float32 字段读 1.097 → 1.236 ns（+12.7%）、E9 定宽 .Id 1.545 → 1.696 ns（+9.8%），
#: 五轮全部稳定复现（B1/B5 等则持平）。发布包必须与「没有这个调用」逐字节等价，
#: 所以只能让调用点在发布包里根本不存在。
_CSHARP_GUARD_COND = "CONFIG_DEBUG || UNITY_EDITOR || DEVELOPMENT_BUILD"

#: 生成物整体包在 ``namespace {CSHARP_NAMESPACE}`` 里 ⇒ 所有行额外缩进这一层。
#: 行长阈值必须把它算进去（`_csharp_member_lines` 里的 pad 只算到类内那一层）。
_CSHARP_NS = "GameFramework.ConfigGen"
_CSHARP_NS_PAD = 4


def _vtable_slot(field: AccessorField) -> int:
    """FlatBuffers vtable slot = 4 + 2*字段序（与指针式 reader 一致）。"""
    return 4 + 2 * field.slot


def _csharp_scalar_reader(field: AccessorField) -> str:
    """槽位版读取器（表级行用 `_off`/字面量；嵌套 record 用槽位）。"""
    if field.kind == "scalar":
        # 单一来源：_CSHARP_SCALAR_READERS（新增标量只需改那一处）
        return _CSHARP_SCALAR_READERS[field.type_text]
    return "WireReader.I8"  # string 另有分支；enum 的 wire 是 byte


def _csharp_type(field: AccessorField) -> str:
    if field.kind == "string":
        return "string"
    if field.kind == "scalar":
        return CSHARP_SCALAR_TYPES[field.type_text]
    # enum 的 wire 是 byte，C# 侧暴露为具名枚举（cast 由调用点加）
    return "int"


def _string_cache_name(field_name: str) -> str:
    """DesignName -> DesignNameCache（accessor 上的静态属性名）。"""
    return f"{field_name}Cache"


def _i18n_cache_name(field_name: str) -> str:
    """DesignName -> DesignNameI18nCache（**译文**的 per-field 行下标缓存）。"""
    return f"{field_name}I18nCache"


def _i18n_reader_name(field_name: str) -> str:
    """DesignName -> I18nDesignName（按行下标读当前语言译文的私有方法）。"""
    return f"I18n{field_name}"


def _private_cache_field(name: str) -> str:
    """NameCache -> _nameCache（静态属性的后备字段名）。"""
    return f"_{name[0].lower()}{name[1:]}"


#: 行句柄的三种读取形态：
#:   ``slot``    —— ``WireReader.I32(_row, slot)``，每次现走 vtable（嵌套 record 子行用）
#:   ``offsets`` —— ``WireReader.I32At(_row, _off[slot])``，行句柄携带按 vtable 记忆化的偏移表
#:   ``literal`` —— ``WireReader.I32At(_row, 28)``，定宽布局 ⇒ 偏移是表级常量，无偏移表
ROW_MODE_SLOT = "slot"
ROW_MODE_OFFSETS = "offsets"
ROW_MODE_LITERAL = "literal"


def _csharp_ctor_lines(type_name: str, mode: str = ROW_MODE_SLOT) -> list[str]:
    """Emit an Allman-style constructor body for a row struct."""
    if mode == ROW_MODE_OFFSETS:
        return [
            f"internal {type_name}(IntPtr row, int[] offsets, int version, int rowIndex)",
            "{",
            "    _row = row;",
            "    _off = offsets;",
            "    _version = version;",
            "    _index = rowIndex;",
            "}",
        ]
    if mode == ROW_MODE_LITERAL:
        return [
            f"internal {type_name}(IntPtr row, int version, int rowIndex)",
            "{",
            "    _row = row;",
            "    _version = version;",
            "    _index = rowIndex;",
            "}",
        ]
    return [
        f"internal {type_name}(IntPtr row, int version)",
        "{",
        "    _row = row;",
        "    _version = version;",
        "}",
    ]


def _csharp_member_lines(type_text: str, name: str, expr: str, indent: int) -> list[str]:
    """Emit one row/record property, indented ``indent`` spaces.

    **每个 getter 都带开发期世代守卫** ``TableVersion.Check(_version)``，用 ``#if`` 包住。

    为什么逐字段检查：行 / record 结构体是**值类型**，里面只存裸指针 + 世代号，可以被存进
    字段、容器、闭包跨整包重载存活。句柄一旦过期，``_row`` 指向的就是已释放/被复用/尚未
    释放的内存 —— 读出来是静默错值（实测同尺寸复用时会读到别人的堆数据），既不是异常
    也不是 null。所以过期检查没有别的地方可放，只能在每次字段读时做。

    为什么是 ``#if`` 而不是「常驻调用 + 发布期空实现」：后者实测有热路径回归
    （同会话交替 A/B 五轮稳定复现，见 ``_CSHARP_GUARD_COND`` 的注释）。
    发布包里这些 getter 必须与改动前**逐字节一致**，所以调用点只能根本不存在。

    形态：永远是块体 —— 守卫是一条语句，表达式体装不下。
    """
    pad = " " * indent
    return [
        f"{pad}public {type_text} {name}",
        f"{pad}{{",
        f"{pad}    get",
        f"{pad}    {{",
        f"{pad}        #if {_CSHARP_GUARD_COND}",
        f"{pad}        TableVersion.Check(_version);",
        f"{pad}        #endif",
        f"{pad}        return {expr};",
        f"{pad}    }}",
        f"{pad}}}",
    ]


def _indent(lines: list[str], width: int) -> list[str]:
    pad = " " * width
    return [f"{pad}{line}" for line in lines]


def _emit_csharp_field(
    field: AccessorField,
    qualified_row: str,
    indent: int,
    mode: str = ROW_MODE_SLOT,
    literal_offsets: dict[int, int] | None = None,
    i18n_read: str | None = None,
) -> list[str]:
    """Emit one field's accessor as lines indented ``indent`` spaces.
    ``qualified_row`` prefixes a nested row ref at top level (e.g.
    ``ItemAccessor.``); inside the accessor class pass ``""``

    ``mode`` 见 ``ROW_MODE_*``：表级行走 ``offsets`` 或 ``literal``，嵌套 record 子行走 ``slot``。
    ``literal`` 模式下偏移来自 ``literal_offsets``（表级常量，由导出期 ``probe_row_layout`` 给出）。
    ``i18n_read`` 非空 ⇒ 多语言字段，值是**译文读取方法名**（同一个 accessor 内的私有静态方法）。
    """
    slot = _vtable_slot(field)

    # 多语言字段：先按**行下标**读当前语言的稀疏 i18n 表（私有方法 `i18n_read` 负责），
    # 拿不到（未加载该语言包／该行缺失／该字段无译文）再回退主表原文。
    #
    # 绝不在行句柄里缓存 i18n 指针 —— 切语言会换掉整个 i18n 表，缓存下来就是悬垂指针。
    # 也**不能**在 i18n 行存在时无条件返回它的值：字段为 null 时同样要回退，否则 C# 与
    # Lua（`v ~= nil and v or 原文`）在「行在、译文空」这一点上行为不一致。
    #
    # 回退分支走 per-field 行下标缓存：主语言（不加载 i18n 包＝默认发布形态）走的正是这条路，
    # 没缓存时每次读都要 UTF-8 解码 + 新建 string（实测 50.25 ns + 35.4 字节/次）。
    # 缓存的是**主表原文**，与语言无关（切语言不动主表）⇒ 用主表自己的世代即可，不会串语言。
    if field.i18n and i18n_read:
        pad = " " * indent
        off = _csharp_literal_offset(field, mode, literal_offsets, slot)
        cache = _string_cache_name(field.name)
        return [
            f"{pad}public string {field.name}",
            f"{pad}{{",
            f"{pad}    get",
            f"{pad}    {{",
            f"{pad}        #if {_CSHARP_GUARD_COND}",
            f"{pad}        TableVersion.Check(_version);",
            f"{pad}        #endif",
            f"{pad}        string v = {qualified_row}{i18n_read}(_index);",
            f"{pad}        if (v != null)",
            f"{pad}        {{",
            f"{pad}            return v;",
            f"{pad}        }}",
            f"{pad}        string[] c = {qualified_row}{cache};",
            f"{pad}        string s = c[_index];",
            f"{pad}        if (s != null)",
            f"{pad}        {{",
            f"{pad}            return s;",
            f"{pad}        }}",
            f"{pad}        s = NStringCache.Decode((byte*)WireReader.IndirectAt(_row, {off}));",
            f"{pad}        c[_index] = s;",
            f"{pad}        return s;",
            f"{pad}    }}",
            f"{pad}}}",
        ]

    if mode in (ROW_MODE_OFFSETS, ROW_MODE_LITERAL):
        if mode == ROW_MODE_LITERAL:
            if literal_offsets is None or slot not in literal_offsets:
                raise ValueError(f"字段 {field.name}（slot {slot}）缺字面量偏移")
            off = str(literal_offsets[slot])
        else:
            off = f"_off[{slot}]"
        if field.kind == "vector":
            if field.element_kind == "record" and field.record_name:
                container = f"NStructArray<{qualified_row}{field.record_name}>"
            elif field.container_text:
                container = field.container_text
            else:
                container = "NArray<int>"
            return _csharp_member_lines(
                container,
                field.name,
                f"new {container}((byte*)WireReader.IndirectAt(_row, {off}), _version)",
                indent,
            )
        if field.kind == "record":
            return _csharp_member_lines(
                f"{qualified_row}{field.record_name}",
                field.name,
                f"new {qualified_row}{field.record_name}((IntPtr)WireReader.IndirectAt(_row, {off}), _version)",
                indent,
            )
        if field.kind == "string":
            # per-field 行下标缓存：冷路径去哈希去锁，热路径一次数组下标。
            # 同时消除「指针做 key 在整包换代后 GC 复用地址命中陈旧条目」的隐患。
            cache = _string_cache_name(field.name)
            pad = " " * indent
            return [
                f"{pad}public string {field.name}",
                f"{pad}{{",
                f"{pad}    get",
                f"{pad}    {{",
                f"{pad}        #if {_CSHARP_GUARD_COND}",
                f"{pad}        TableVersion.Check(_version);",
                f"{pad}        #endif",
                f"{pad}        string[] c = {qualified_row}{cache};",
                f"{pad}        string s = c[_index];",
                f"{pad}        if (s != null)",
                f"{pad}        {{",
                f"{pad}            return s;",
                f"{pad}        }}",
                f"{pad}        s = NStringCache.Decode((byte*)WireReader.IndirectAt(_row, {off}));",
                f"{pad}        c[_index] = s;",
                f"{pad}        return s;",
                f"{pad}    }}",
                f"{pad}}}",
            ]
        if field.kind == "enum":
            # 枚举的 wire 是 byte（type_text 是枚举名，不参与标量查表）
            return _csharp_member_lines(
                field.type_text,
                field.name,
                f"({field.type_text})WireReader.I8At(_row, {off})",
                indent,
            )
        at_reader = _CSHARP_AT_READERS[field.type_text]
        return _csharp_member_lines(_csharp_type(field), field.name, f"{at_reader}(_row, {off})", indent)
    if field.kind == "vector":
        # 参考实现 风格单一容器（NArray<T> / NStructArray<T>）；record 行类型需带 qualified 前缀
        if field.element_kind == "record" and field.record_name:
            container = f"NStructArray<{qualified_row}{field.record_name}>"
        elif field.container_text:
            container = field.container_text
        else:
            container = "NArray<int>"
        return _csharp_member_lines(
            container, field.name, f"new {container}(_row, {slot}, _version)", indent
        )
    if field.kind == "record":
        return _csharp_member_lines(
            f"{qualified_row}{field.record_name}",
            field.name,
            f"new {qualified_row}{field.record_name}(WireReader.Indirect(_row, {slot}), _version)",
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
            f"{pad}public {field.ref_table}? {field.ref_table} => {field.ref_table}Accessor.ByID({field.name});"
        )
    return lines


def _csharp_literal_offset(
    field: AccessorField, mode: str, literal_offsets: dict[int, int] | None, slot: int
) -> str:
    """字段在当前布局下的偏移表达式：定宽是字面量常量，否则是 `_off[slot]`。"""
    if mode == ROW_MODE_LITERAL:
        if literal_offsets is None or slot not in literal_offsets:
            raise ValueError(f"字段 {field.name}（slot {slot}）缺字面量偏移")
        return str(literal_offsets[slot])
    return f"_off[{slot}]"


def _emit_csharp_string_caches(model: CanonicalAccessorModel) -> list[str]:
    """为表级 string 字段产出 per-field 行下标缓存（按主表世代整体重建）。

    取代原先「按字符串指针做 key 的全局 ConcurrentDictionary/Dictionary」：
    冷路径去哈希去锁，热路径一次数组下标；且行下标不会像指针那样在整包换代后被 GC 复用。
    """
    # 多语言字段**也要**这份缓存：它缓存的是**回退用的主表原文**（与语言无关，切语言不变），
    # 而主语言（不加载 i18n 包＝默认发布形态）走的正是这条回退路径 ——
    # 不加缓存时每次读都要 UTF-8 解码 + 新建 string（实测 50.25 ns + 35.4 字节/次）。
    # 译文另有一份按**i18n 世代**失效的缓存（见 `_emit_csharp_i18n_support`），两者互不冲突。
    names = [
        _string_cache_name(f.name)
        for f in model.client_fields
        if f.kind == "string"
    ]
    if not names:
        return []
    epoch = "TableVersion.Current"
    lines: list[str] = []
    lines.append("    // ---- per-field 字符串缓存（行下标索引，整套 bin 换代时整体重建）----")
    for n in names:
        lines.append(f"    private static string[] {_private_cache_field(n)};")
    lines.append("    private static int _strCacheVersion = -1;")
    lines.append("")
    lines.append("    [MethodImpl(MethodImplOptions.NoInlining)]")
    lines.append("    private static void ResetStringCaches()")
    lines.append("    {")
    lines.append("        int n = Table.Count;")
    for n in names:
        lines.append(f"        {_private_cache_field(n)} = new string[n];")
    lines.append(f"        _strCacheVersion = {epoch};")
    lines.append("    }")
    for n in names:
        private = _private_cache_field(n)
        lines.append("")
        lines.append(f"    internal static string[] {n}")
        lines.append("    {")
        lines.append("        [MethodImpl(MethodImplOptions.AggressiveInlining)]")
        lines.append("        get")
        lines.append("        {")
        lines.append(f"            string[] c = {private};")
        lines.append(f"            if (c != null && _strCacheVersion == {epoch})")
        lines.append("            {")
        lines.append("                return c;")
        lines.append("            }")
        lines.append("            ResetStringCaches();")
        lines.append(f"            return {private};")
        lines.append("        }")
        lines.append("    }")
    return lines


def _csharp_i18n_read_expr(model: CanonicalAccessorModel, i18n_index: int) -> str:
    """稀疏 i18n 表里第 ``i18n_index`` 个多语言字段的读取表达式（``p`` 是 i18n 行指针）。

    i18n 表的字段排布是「主键 + 主表里的多语言字段（按声明顺序，见导出器 `_i18n_table`）」
    ⇒ 第 k 个多语言字段的 vtable 字节偏移是 ``4 + 2*(1+k)``。
    定宽 i18n 表用**它自己的** ``slot_offsets`` 换成字面量行内偏移；否则走 vtable 槽位。
    """
    slot = 4 + 2 * (1 + i18n_index)
    offsets = model.i18n_uniform_offsets
    if offsets is None:
        return f"WireReader.Indirect(p, {slot})"
    if slot not in offsets:
        raise ValueError(f"i18n 字段序 {i18n_index}（slot {slot}）缺字面量偏移")
    return f"WireReader.IndirectAt(p, {offsets[slot]})"


def _emit_csharp_i18n_support(model: CanonicalAccessorModel) -> list[str]:
    """多语言字段的读取支撑：稀疏 i18n 表句柄 + 译文缓存 + 逐字段的私有读取方法。

    这一套原先是一份**独立的** ``{Table}_i18nAccessor``（含公开的 ``{Table}_i18n`` 行结构体）。
    但它的唯一消费者就是主表的 getter，对外没有任何用途 ⇒ 合并进来，且不再暴露任何类型。

    与主表的两处关键差异（合并后仍各自独立）：
    - 表只在**加载了对应语言包**时存在 ⇒ 用 ``Runtime.TryTable``，缺席时读回 null 让调用方回退；
    - 失效用 **i18n 世代**（``TableVersion.I18nCurrent``）⇒ 切语言只重建这里，主表行句柄继续有效。
    """
    if not model.i18n_fields or not model.i18n_table:
        return []
    lines: list[str] = []
    lines.append("    // ---- 多语言字段：当前语言的稀疏 i18n 表（按行下标读，与主表同序）----")
    lines.append("    // 该表只在加载了对应语言包时存在；缺席时读回 null，由字段 getter 回退主表原文。")
    lines.append(f'    private const string I18nTableName = "{model.i18n_table}";')
    lines.append("    private static ConfigTable _i18nTable;")
    lines.append("    private static int _i18nTableVersion = -1;")
    lines.append("")
    lines.append("    [MethodImpl(MethodImplOptions.NoInlining)]")
    lines.append("    private static void ResolveI18nTable()")
    lines.append("    {")
    lines.append("        _i18nTable = Runtime.TryTable(I18nTableName);")
    lines.append("        _i18nTableVersion = TableVersion.I18nCurrent;")
    lines.append("    }")
    lines.append("")
    lines.append("    internal static ConfigTable I18nTable")
    lines.append("    {")
    lines.append("        get")
    lines.append("        {")
    lines.append("            ConfigTable t = _i18nTable;")
    lines.append("            // ⚠️ 表**缺席**时也要认这个世代。只判 `t != null` 的话，主语言")
    lines.append("            //    （＝默认发布形态，根本不加载 i18n 包）每读一个多语言字段都要重走")
    lines.append("            //    一遍 TryTable（字典查找 + 字符串哈希）。")
    lines.append("            if (_i18nTableVersion == TableVersion.I18nCurrent)")
    lines.append("            {")
    lines.append("                return t;")
    lines.append("            }")
    lines.append("            ResolveI18nTable();")
    lines.append("            return _i18nTable;")
    lines.append("        }")
    lines.append("    }")
    fields = list(model.i18n_fields)
    names = [_i18n_cache_name(f.name) for f in fields]
    lines.append("")
    lines.append("    // 译文缓存：按 **i18n 世代**整体重建（切语言即失效）")
    for n in names:
        lines.append(f"    private static string[] {_private_cache_field(n)};")
    lines.append("    private static int _i18nStrCacheVersion = -1;")
    lines.append("")
    lines.append("    [MethodImpl(MethodImplOptions.NoInlining)]")
    lines.append("    private static void ResetI18nStringCaches()")
    lines.append("    {")
    lines.append("        ConfigTable t = I18nTable;")
    lines.append("        int n = t == null ? 0 : t.Count;")
    for n in names:
        lines.append(f"        {_private_cache_field(n)} = new string[n];")
    lines.append("        _i18nStrCacheVersion = TableVersion.I18nCurrent;")
    lines.append("    }")
    for index, field in enumerate(fields):
        name = names[index]
        private = _private_cache_field(name)
        lines.append("")
        lines.append(f"    private static string[] {name}")
        lines.append("    {")
        lines.append("        [MethodImpl(MethodImplOptions.AggressiveInlining)]")
        lines.append("        get")
        lines.append("        {")
        lines.append(f"            string[] c = {private};")
        lines.append("            if (c != null && _i18nStrCacheVersion == TableVersion.I18nCurrent)")
        lines.append("            {")
        lines.append("                return c;")
        lines.append("            }")
        lines.append("            ResetI18nStringCaches();")
        lines.append(f"            return {private};")
        lines.append("        }")
        lines.append("    }")
        lines.append("")
        lines.append(
            f"    /// <summary>{field.name}：当前语言译文；表/行缺失或该字段无译文时返回 null。</summary>"
        )
        # ⚠️ 必须是 internal：行结构体是**顶层类型**（不在 accessor 类里），private 够不着。
        # ⚠️ 必须标 unsafe：方法体里有 `(byte*)` 解引用（accessor 类是安全上下文）。
        lines.append(f"    internal static unsafe string {_i18n_reader_name(field.name)}(int index)")
        lines.append("    {")
        lines.append("        ConfigTable t = I18nTable;")
        lines.append("        if (t == null)")
        lines.append("        {")
        lines.append("            return null;")
        lines.append("        }")
        lines.append(f"        string[] c = {name};")
        lines.append("        if (index < 0 || index >= c.Length)")
        lines.append("        {")
        lines.append("            return null;")
        lines.append("        }")
        lines.append("        IntPtr p = t.RowAt(index);")
        lines.append("        if (p == IntPtr.Zero)")
        lines.append("        {")
        lines.append("            return null;")
        lines.append("        }")
        lines.append("        string s = c[index];")
        lines.append("        if (s != null)")
        lines.append("        {")
        lines.append("            return s;")
        lines.append("        }")
        lines.append(
            f"        s = NStringCache.Decode((byte*){_csharp_i18n_read_expr(model, index)});"
        )
        lines.append("        c[index] = s;")
        lines.append("        return s;")
        lines.append("    }")
    return lines


def _emit_csharp_record_structs(model: CanonicalAccessorModel) -> list[str]:
    """Emit nested ``{Record}`` structs for every referenced record."""
    lines: list[str] = []
    for record in referenced_records(model):
        fields = record_accessor_fields(record, model.records)
        lines.append(f"    public unsafe readonly struct {record.name}")
        lines.append("    {")
        lines.append("        private readonly IntPtr _row;")
        lines.append("        private readonly int _version;")
        lines.extend(_indent(_csharp_ctor_lines(f"{record.name}"), 8))
        for field in fields:
            lines.extend(_emit_csharp_field(field, "", 8))
        lines.append("    }")
        lines.append("")
    return lines


def _emit_csharp_query_api(model: CanonicalAccessorModel) -> list[str]:
    """Emit per-table Count/ByID/ByIndex (+ ByCodeName if the index is declared).

    OPT-3：表句柄缓存在 accessor 静态字段里，避免每次查找都做一次
    ``Dictionary<string, ConfigTable>`` 字符串哈希。
    OPT-1：行句柄随行携带按该行 vtable 解析出的偏移表（``ConfigTable.OffsetsFor``
    按 vtable 身份记忆化），因此不要求整表共用同一 vtable。
    """
    table = model.table.table
    max_slot = 4 + 2 * len(model.client_fields)
    literal = model.is_uniform
    # 行句柄构造实参：定宽表不带偏移表（偏移已是表级常量）
    # ⚠️ 每个查询 API 的行下标变量名不同，必须分别模板（写错会生成编译不过的代码）：
    #     ByID → idx、ByIndex → i、ByCodeName → row
    def _row_args(var: str) -> tuple[str, str]:
        return (
            f"p, t.OffsetsFor(p, MaxSlot), t.Version, {var}",
            f"p, t.Version, {var}",
        )

    offsets_by, literal_by = _row_args("idx")
    offsets_i, literal_i = _row_args("i")
    offsets_row, literal_row = _row_args("row")
    lines: list[str] = []
    lines.append(f"    private const string TableName = \"{table}\";")
    if not literal:
        # 定宽表不需要 MaxSlot（不发 OffsetsFor）
        lines.append(f"    private const int MaxSlot = {max_slot};")
    lines.append("    private static ConfigTable _table;")
    lines.append("    private static int _tableVersion = -1;")
    lines.append("")
    lines.append("    /// <summary>解析并缓存表句柄；整套 bin 换代后 Runtime 会重建表对象。</summary>")
    lines.append("    [MethodImpl(MethodImplOptions.NoInlining)]")
    lines.append("    private static void Resolve()")
    lines.append("    {")
    lines.append("        _table = Runtime.Table(TableName);")
    lines.append("        _tableVersion = TableVersion.Current;")
    lines.append("    }")
    lines.append("")
    lines.append("    internal static ConfigTable Table")
    lines.append("    {")
    lines.append("        get")
    lines.append("        {")
    lines.append("            ConfigTable t = _table;")
    lines.append("            // 世代守卫：整套 bin 换代（LoadBundle/Clear）后必须重新取句柄，")
    lines.append("            // 否则会继续用已被 Dispose 的旧表缓冲（悬垂指针）。")
    epoch = "TableVersion.Current"
    lines.append(f"            if (t != null && _tableVersion == {epoch})")
    lines.append("            {")
    lines.append("                return t;")
    lines.append("            }")
    lines.append("            Resolve();")
    lines.append("            return _table;")
    lines.append("        }")
    lines.append("    }")
    lines.append("")
    lines.append("    /// <summary>行数。</summary>")
    lines.append("    public static int Count => Table.Count;")
    lines.append("")
    lines.append("    /// <summary>按主键查行；未找到返回 null。</summary>")
    lines.append(f"    public static {table}? ByID(int id)")
    lines.append("    {")
    lines.append("        ConfigTable t = Table;")
    lines.append("        int idx;")
    lines.append("        IntPtr p = t.ByID(id, out idx);")
    lines.append("        if (p == IntPtr.Zero)")
    lines.append("        {")
    lines.append("            return null;")
    lines.append("        }")
    lines.append("        else")
    lines.append("        {")
    lines.append(f"            return new {table}({literal_by if literal else offsets_by});")
    lines.append("        }")
    lines.append("    }")
    lines.append("")
    lines.append("    /// <summary>按 Excel 序行下标取行；越界返回 null。</summary>")
    lines.append(f"    public static {table}? ByIndex(int i)")
    lines.append("    {")
    lines.append("        ConfigTable t = Table;")
    lines.append("        IntPtr p = t.RowAt(i);")
    lines.append("        if (p == IntPtr.Zero)")
    lines.append("        {")
    lines.append("            return null;")
    lines.append("        }")
    lines.append("        else")
    lines.append("        {")
    lines.append(f"            return new {table}({literal_i if literal else offsets_i});")
    lines.append("        }")
    lines.append("    }")
    for index in model.indexes:
        if index.kind == "codename":
            lines.append("")
            lines.append("    /// <summary>Exact-string CodeName lookup; returns null when missing.</summary>")
            lines.append(f"    public static {table}? ByCodeName(string codeName)")
            lines.append("    {")
            lines.append("        ConfigTable t = Table;")
            lines.append(f"        int row = Runtime.ByCodeName(TableName, {index.slot}, codeName);")
            lines.append("        if (row < 0)")
            lines.append("        {")
            lines.append("            return null;")
            lines.append("        }")
            lines.append("        else")
            lines.append("        {")
            lines.append("            IntPtr p = t.RowAt(row);")
            lines.append(f"            return new {table}({literal_row if literal else offsets_row});")
            lines.append("        }")
            lines.append("    }")
    return lines


def _csharp_wrap_namespace(body: list[str]) -> list[str]:
    """把生成物整体包进 ``namespace {_CSHARP_NS}``。

    生成物此前在**全局命名空间**里，于是行类型必须靠 ``Row`` 后缀避免与玩法类撞名
    （`Player`/`Shop`/`Order` 这类表名早晚会撞上）。加一层命名空间后行类型可以叫裸名。
    """
    pad = " " * _CSHARP_NS_PAD
    indented = [f"{pad}{line}" if line else "" for line in body]
    return [f"namespace {_CSHARP_NS}", "{", *indented, "}"]


def generate_csharp_enums(enums) -> str:
    """产出 **枚举类型声明**（``public enum X : byte { ... }``）。

    生成物里的 ``(ItemRarity)WireReader.I8At(...)`` cast 需要这个声明才能编译 ——
    此前只产出 cast、不产出声明，业务侧必须手写 enum，一旦 ord 错位就是**盲 cast**。
    枚举项顺序即 wire 序号（第 0 项是默认值，不写槽位），所以顺序必须与 schema 一致。
    """
    body = [
        "// <auto-generated/> 枚举声明（wire 为 byte，值 = schema 中的顺序序号）",
        "// 顺序即 wire 序号：第 0 项是默认值（导出时该槽位不写，读回 0）。不要重排。",
        "",
    ]
    for name in sorted(enums):
        enum = enums[name]
        body.append(f"public enum {name} : byte")
        body.append("{")
        for index, item in enumerate(enum.values):
            comment = f"   // {item.comment}" if item.comment else ""
            body.append(f"    {item.name} = {index},{comment}")
        body.append("}")
        body.append("")
    text = "\n".join(_csharp_wrap_namespace(body)).rstrip("\n")
    return text + "\n"


def generate_lua_enums(enums) -> str:
    """Lua 侧枚举常量表（与 C# 同一套序号）。"""
    lines = [
        "-- <auto-generated/> 枚举常量表（值 = schema 中的顺序序号，不要重排）",
        "local Enums = {}",
        "",
    ]
    for name in sorted(enums):
        enum = enums[name]
        lines.append(f"Enums.{name} = {{")
        for index, item in enumerate(enum.values):
            comment = f"  -- {item.comment}" if item.comment else ""
            lines.append(f"    {item.name} = {index},{comment}")
        lines.append("}")
    lines.append("")
    lines.append("return Enums")
    return "\n".join(lines) + "\n"


def generate_csharp_accessor(model: CanonicalAccessorModel) -> str:
    table = model.table.table
    body: list[str] = []
    body.append(f"public static partial class {table}Accessor")
    body.append("{")
    body.extend(_emit_csharp_query_api(model))
    string_caches = _emit_csharp_string_caches(model)
    if string_caches:
        body.append("")
        body.extend(string_caches)
    i18n_support = _emit_csharp_i18n_support(model)
    if i18n_support:
        body.append("")
        body.extend(i18n_support)
    record_structs = _emit_csharp_record_structs(model)
    if record_structs:
        body.append("")
        body.extend(record_structs)
    body.append("}")
    body.append("")
    mode = ROW_MODE_LITERAL if model.is_uniform else ROW_MODE_OFFSETS
    body.append(f"public unsafe readonly struct {table}")
    body.append("{")
    body.append("    private readonly IntPtr _row;")
    if mode == ROW_MODE_OFFSETS:
        body.append("    private readonly int[] _off;")
    body.append("    private readonly int _version;")
    body.append("    private readonly int _index;")
    body.extend(_indent(_csharp_ctor_lines(f"{table}", mode), 4))
    qualified = f"{table}Accessor."
    for field in model.client_fields:
        body.extend(
            _emit_csharp_field(
                field,
                qualified_row=qualified,
                indent=4,
                mode=mode,
                literal_offsets=model.uniform_offsets,
                i18n_read=_i18n_reader_name(field.name) if field.i18n else None,
            )
        )
    body.append("}")

    lines: list[str] = []
    lines.append("// <auto-generated/>")
    lines.append(f"// Canonical C# accessor for {table}")
    lines.append("using System;")
    lines.append("using System.Collections.Generic;")
    lines.append("using System.Runtime.CompilerServices;")
    lines.append("")
    lines.extend(_csharp_wrap_namespace(body))
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- Lua helpers


#: C# 标量类型：type_text → C# 类型（**唯一来源**，`canonical_accessor_model` 也用它）。
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

#: C# 标量读取器（槽位版）：type_text → WireReader 方法。
_CSHARP_SCALAR_READERS = {
    "int8": "WireReader.S8",
    "uint8": "WireReader.U8",
    "int16": "WireReader.I16",
    "uint16": "WireReader.U16",
    "int32": "WireReader.I32",
    "uint32": "WireReader.U32",
    "int64": "WireReader.I64",
    "uint64": "WireReader.U64",
    "float": "WireReader.F32",
    "double": "WireReader.F64",
    "bool": "WireReader.Bool",
    "string": "WireReader.Str",
}
assert set(_CSHARP_SCALAR_READERS) == set(CSHARP_SCALAR_TYPES) | {"string"}, (
    "C# 类型映射与读取器映射必须覆盖同一批标量"
)

#: C# 标量读取器（偏移版）：type_text → WireReader 的 *At 方法。
_CSHARP_AT_READERS = {
    "int8": "WireReader.S8At",
    "uint8": "WireReader.U8At",
    "int16": "WireReader.I16At",
    "uint16": "WireReader.U16At",
    "int32": "WireReader.I32At",
    "uint32": "WireReader.U32At",
    "int64": "WireReader.I64At",
    "uint64": "WireReader.U64At",
    "float": "WireReader.F32At",
    "double": "WireReader.F64At",
    "bool": "WireReader.BoolAt",
    "string": "WireReader.StrAt",
}

#: Lua 侧字段读绑定（原生 `gd` 模块）。
#: 12 种标量**全部有绑定**（原生 N9 补齐了 I16/U8/U16/U32/U64）。
#: 注意 `I8` 返回**有符号**，无符号字节要用 `U8`。
_LUA_SCALAR_READER = {
    "int8": "GD.I8",
    "uint8": "GD.U8",
    "int16": "GD.I16",
    "uint16": "GD.U16",
    "int32": "GD.I32",
    "uint32": "GD.U32",
    "int64": "GD.I64",
    "uint64": "GD.U64",
    "float": "GD.F32",
    "double": "GD.F64",
    "bool": "GD.I8",        # 按字节读再与 0 比较
    "string": "GD.Str",
}

#: 向量元素 tag（原生 `elem_from_tag` 认的写法）。
#: N9 之后 12 种标量元素全部可用；`elem_from_tag` 改为**完整字符串精确匹配**，
#: 认不出会报错（旧实现按字符猜，"i16" 会被静默当成 int32 读）。
#: ⚠️ 原生**不支持 record 元素**（无对应 tag）——`vector<Record>` 在 Lua 侧暂不可用。
_LUA_VECTOR_TAG = {
    "int8": "i8",
    "uint8": "u8",
    "int16": "i16",
    "uint16": "u16",
    "int32": "i32",
    "uint32": "u32",
    "int64": "i64",
    "uint64": "u64",
    "float": "f32",
    "double": "f64",
    "bool": "b",
    "string": "s",
}

#: 数组视图元表名（每张表共用一份，模块内是同一个 local）。
_LUA_ARRAY_META = "ArrayMeta"


def _lua_slot(field: AccessorField) -> int:
    """客户端字段序 → **vtable 字节偏移**（原生按字节偏移读，不是 0-based 序号）。"""
    return 4 + 2 * field.slot


def _lua_reader(field: AccessorField) -> str:
    """字段的标量读绑定名。"""
    if field.kind == "string":
        return "GD.Str"
    if field.kind == "enum":
        return "GD.I8"          # enum 的 wire 是 byte
    reader = _LUA_SCALAR_READER.get(field.type_text)
    if reader is None:
        # 不在这里抛错：一个标量类型不该阻断整张表的导出（C# 侧可能照常使用）。
        # 改为生成一个**明确报错**的 getter，问题在使用点暴露。
        return None
    return reader


def _lua_off_reader(field: AccessorField) -> str | None:
    """同一字段的**字面量偏移**读绑定名（`GD.I32` → `GD.I32Off`）。

    只对**定宽**表用：偏移在导出期算好，是表级常量，于是每次读可以省掉一次 vtable 走查
    （`obj - soffset` → 读 vtable 长度 → 越界判断 → 读槽位偏移）。
    实测（同 session 交替 A/B，6685 行表）：int32 字段 −5.6%、字符串 −5.7%、3 字段合计 −6.1%。
    """
    r = _lua_reader(field)
    return None if r is None else r + "Off"


def _lua_unsupported(field: AccessorField, why: str) -> str:
    return (
        f'error("[Config] Lua 不支持 {field.name}（{field.type_text}）：{why}")'
    )


def _lua_scalar_expr(field: AccessorField, off: int | None = None) -> str:
    """标量/枚举字段的读取表达式（值为**返回语句**：`return x` 或 `error(...)`）。

    `off` 非空 ⇒ 该表是定宽表，直接用字面量偏移读（省一次 vtable 走查）。
    """
    arg = off if off is not None else _lua_slot(field)
    reader = _lua_off_reader(field) if off is not None else _lua_reader(field)
    if reader is None:
        return _lua_unsupported(
            field, f"原生 gd 模块没有 {field.type_text} 的读取绑定"
        )
    # ⚠️ 判 bool 要用 **type_text**，不能用 `field.kind` —— 模型的 kind 只会是
    # vector/record/enum/string/scalar，从来没有 "bool"，所以原先 `kind == "bool"` 是**死代码**，
    # 于是 bool 标量一直返回数字 0/1。这在 Lua 里是个坑：**0 是真值**，
    # `if row.Stack then` 对 false 也成立。修成返回 boolean，与 bool **向量**（原生推 boolean）一致。
    if field.type_text == "bool":
        return f"return {reader}(s, {arg}) ~= 0"
    return f"return {reader}(s, {arg})"


def _lua_i18n_expr(field: AccessorField, i18n_index: int, off: int | None = None) -> str:
    """多语言字段：优先读当前语言的 i18n 表，缺失则回退主表原文。

    读取**按行下标**进行：`GD.I18nStr(i18nTbl, row, fieldSlot)` 用行 userdata 里记的
    0-based 行下标定位稀疏 i18n 表的同一行（导出器保证两表行序 1:1）。

    ⚠️ 不要退回「按主键二分」：i18n 表的 items 按**主表行序**排列，而导出器**不排序**，
    所以主表行序未必等于主键升序；在未排序的 items 上二分查不到任何译文，且**静默**
    回退成原文（实测把行序反过来后译文全部消失，无任何报错）。

    ⚠️ 最后一个参数是 **i18n 表里**该字段的 vtable 字节偏移（不是主表的）——所以稀疏
    i18n 表必须「主键在最前、i18n 字段按主表声明顺序」排列（导出器已保证）。
    """
    # 回退读主表原文：定宽表可以用字面量偏移。
    # ⚠️ i18n 表那次读**仍是槽位**：原生绑定 `GD.I18nStr` 只认槽位（没有 `I18nStrOff`），
    #    而它内部本来就只做一次定位 —— 换成字面量也没有可省的走查。C# 侧没有这个限制，
    #    `I18nStr` 的对应物是访问器自己发的 `WireReader.IndirectAt`，所以那边用的是偏移。
    main_arg = off if off is not None else _lua_slot(field)
    main_reader = "GD.StrOff" if off is not None else "GD.Str"
    i18n_slot = 4 + 2 * (1 + i18n_index)      # i18n 表：slot 4 = 主键
    return (
        f"local v = GD.I18nStr(i18n_table(), s, {i18n_slot}) "
        f"return v ~= nil and v or {main_reader}(s, {main_arg})"
    )


def _lua_vector_body(field: AccessorField, off: int | None = None) -> str:
    """向量：返回**惰性视图**（原生按数据指针缓存 userdata；不建 Lua 表、稳态零分配）。

    `off` 非空 ⇒ 用 `GD.ArrOff`（字面量偏移）。实测这一项**没有收益**（112.29 → 112.33 ns），
    因为 `GD.Arr` 的成本在缓存查找与 tag 解析上，不在 vtable 走查 —— 这里换算只为让
    「定宽表 = 全字面量偏移」这条规则**没有例外**，好读也好测。
    """
    if field.element_kind == "record":
        return _lua_unsupported(field, "原生 gd 模块没有 record 元素的 tag")
    tag = "i8" if field.element_kind == "enum" else _LUA_VECTOR_TAG.get(field.element_type)
    if tag is None:
        return _lua_unsupported(
            field, f"原生 gd 模块没有向量元素类型 {field.element_type} 的 tag"
        )
    if off is not None:
        return f"return GD.ArrOff(s, {off}, \"{tag}\", {_LUA_ARRAY_META})"
    return f"return GD.Arr(s, {_lua_slot(field)}, \"{tag}\", {_LUA_ARRAY_META})"


def _lua_record_expr(field: AccessorField, off: int | None = None) -> str:
    """嵌套 record：原生按数据指针缓存 userdata，并把 meta 挂上去。

    定宽表里「父行 → 嵌套表指针」那一步也能用字面量偏移（`StructOff`）；
    **record 自己内部**的字段仍是槽位读 —— record 不是定宽表，它的偏移不是常量。
    """
    if off is not None:
        return f"return GD.StructOff(s, {off}, {field.record_name}Meta)"
    return f"return GD.Struct(s, {_lua_slot(field)}, {field.record_name}Meta)"


def _lua_field_body(
    field: AccessorField, i18n_index: int, delegate_i18n: bool, off: int | None = None
) -> str:
    if field.kind == "vector":
        return _lua_vector_body(field, off)
    if field.kind == "record":
        return _lua_record_expr(field, off)
    # 只有**主表**的 accessor 才委托 i18n 表；生成 i18n 表自己的 accessor 时
    # 它的 i18n 字段就是普通字符串字段（否则会自我委托）。
    if field.i18n and delegate_i18n:
        return _lua_i18n_expr(field, i18n_index, off)
    return _lua_scalar_expr(field, off)


def _lua_member_lines(
    field: AccessorField,
    indent: str,
    i18n_index: int | None = None,
    delegate_i18n: bool = False,
    off: int | None = None,
) -> list[str]:
    """一个字段的 accessor 条目。

    跨表 ref 发两行：裸 id + 类型化访问（与 C# 对齐，裸 id 永不丢失）。
    类型化访问走 `Config.<RefTable>`（`Config/init.lua` 的懒加载注册表）。

    `off` 非空 ⇒ **定宽表**：这一条用字面量偏移读（含跨表 ref 里那一次读）。
    """
    lines: list[str] = []
    body = _lua_field_body(field, i18n_index or 0, delegate_i18n, off)
    lines.append(f"{indent}{field.name} = function(s) {body} end,")
    if field.ref_table:
        # 类型化跨表 ref：裸 id 已在上一行给出，这里再给行对象。
        # 只对能作为 id 读的标量类型发（bool/string 做 id 无意义）。
        arg = off if off is not None else _lua_slot(field)
        reader = _lua_off_reader(field) if off is not None else _lua_reader(field)
        if reader is not None and field.kind not in ("bool", "string"):
            lines.append(
                f"{indent}{field.ref_table} = function(s) "
                f"return Config.{field.ref_table}.ByID({reader}(s, {arg})) end,"
            )
    return lines


def _emit_lua_record_metas(model: CanonicalAccessorModel) -> list[str]:
    """每个被引用的 record 一份元表（字段名 → 读取函数）。"""
    lines: list[str] = []
    for record in referenced_records(model):
        fields = record_accessor_fields(record, model.records)
        lines.append(f"local {record.name}Meta = make_meta({{")
        for field in fields:
            # record 内部字段的 slot 是 record 自己的字段序
            lines.extend(_lua_member_lines(field, "    "))
        lines.append("})")
        lines.append("")
    return lines


def generate_lua_accessor(model: CanonicalAccessorModel) -> str:
    table = model.table.table
    delegate = bool(model.i18n_table)

    lines: list[str] = []
    lines.append(f"-- <auto-generated/> canonical Lua accessor for {table}")
    lines.append('local GD = require("gd")')
    lines.append("")
    lines.append("-- 表句柄：模块加载时取一次（原生固定槽位引用，跨加载有效）")
    lines.append(f'local _tbl = GD.FindTable("{table}")')
    if delegate:
        lines.append("-- 稀疏 i18n 表句柄：按 i18n 世代**记忆**。")
        lines.append("-- 用 GD.I18nGen() 而不是「nil 才重试」：切回主语言后句柄会重新变成")
        lines.append("-- 不可解析，只按 nil 重试会把失效句柄一直用下去（原生 check_tbl 直接报错）。")
        lines.append("local _i18nTbl, _i18nGen = nil, nil")
        lines.append("local function i18n_table()")
        lines.append("    local g = GD.I18nGen()")
        lines.append("    if g ~= _i18nGen then")
        lines.append(f'        _i18nTbl = GD.FindTableI18n("{model.i18n_table}")')
        lines.append("        _i18nGen = g")
        lines.append("    end")
        lines.append("    return _i18nTbl")
        lines.append("end")
    lines.append("")
    lines.append("-- 元表工厂：字段名 → 读取函数（分发表一次性构建，所有行共享同一元表）")
    lines.append("local function make_meta(readers)")
    lines.append("    return { __index = function(self, key)")
    lines.append("        local fn = readers[key]")
    lines.append("        if fn then return fn(self) end")
    lines.append("    end }")
    lines.append("end")
    lines.append("")
    lines.append("-- 数组视图元表（**惰性视图**：不建 Lua 表、稳态零分配）")
    lines.append(f"local {_LUA_ARRAY_META} = {{")
    lines.append("    __len   = function(v) return GD.ArrLen(v) end,")
    lines.append("    __index = function(v, i) return GD.ArrAt(v, i) end,")
    lines.append("    __pairs = ipairs,   -- 契约测试要求 for _, v in pairs(tags) 可用")
    lines.append("}")
    lines.append("")

    record_metas = _emit_lua_record_metas(model)
    if record_metas:
        lines.extend(record_metas)

    i18n_names = [f.name for f in model.client_fields if f.i18n]
    # 定宽表：槽位 → 行内偏移是**表级常量**（导出期算好，见 layout_manifests 的 slot_offsets）
    # ⇒ 发字面量偏移读，省掉每次读的 vtable 走查。非定宽表照旧走槽位。
    offsets = model.uniform_offsets if model.is_uniform else None
    if offsets is not None:
        lines.append("-- ⚠️ 本表是**定宽布局**：下面全是字面量偏移读（无 vtable 走查）。")
        lines.append("--    偏移由导出期 `probe_row_layout` 算出，是表级常量；改变 schema 必须重新导出。")
    lines.append("-- 行访问器元表（self = 行 userdata）")
    lines.append("local RowMeta = make_meta({")
    for field in model.client_fields:
        index = i18n_names.index(field.name) if field.i18n and field.name in i18n_names else None
        off = offsets.get(_lua_slot(field)) if offsets is not None else None
        lines.extend(
            _lua_member_lines(field, "    ", index, delegate_i18n=delegate, off=off)
        )
    lines.append("})")
    lines.append("")
    lines.append("-- 公开 API（纯函数，无状态）")
    lines.append("local M = {}")
    lines.append("function M.Count() return GD.Count(_tbl) end")
    lines.append("function M.ByID(id) return GD.ByID(_tbl, id, RowMeta) end")
    lines.append("function M.ByIndex(i) return GD.ByIndex(_tbl, i, RowMeta) end")
    for index in model.indexes:
        if index.kind == "codename":
            lines.append("-- 原生 codeName 查询：FNV-1a 64 桶表 + 按字段精确字符串确认")
            lines.append(
                f"function M.ByCodeName(codeName) "
                f"return GD.ByCodeName(_tbl, {index.slot}, codeName, RowMeta) end"
            )
    lines.append("return M")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- public render


def render_csharp_accessor(
    table,
    indexes,
    records=None,
    uniform_offsets=None,
    i18n_uniform_offsets=None,
) -> str:
    return generate_csharp_accessor(
        build_accessor_model(
            table,
            indexes,
            records=records,
            uniform_offsets=uniform_offsets,
            i18n_uniform_offsets=i18n_uniform_offsets,
        )
    )


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
        indexes = (QueryIndex(kind="codename"),)
    return render_csharp_accessor(table, indexes, records=records)


def golden_lua(table=None, indexes=None, records=None) -> str:
    if table is None:
        table = _table()
    if indexes is None:
        indexes = (QueryIndex(kind="codename"),)
    return render_lua_accessor(table, indexes, records=records)
