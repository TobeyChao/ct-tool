"""Canonical C#/Lua accessor + CodeName API tests (ref-aligned, pointer-based row handle)."""

from __future__ import annotations

from ct.export.canonical_accessor import (
    generate_lua_accessor,
    golden_csharp,
    golden_lua,
    render_csharp_accessor,
    render_lua_accessor,
)
from ct.export.canonical_accessor_model import build_accessor_model
from ct.schema.indexes import QueryIndex
from ct.schema.type_expression import ScalarType, VectorType
from ct.schema.resources import (
    FieldDef,
    RecordResource,
    TableResource,
)


#: 与 `canonical_accessor._CSHARP_GUARD_COND` / `ConfigRuntime.cs::TableVersion.Check` 必须一致。
GUARD_COND = "CONFIG_DEBUG || UNITY_EDITOR || DEVELOPMENT_BUILD"


def assert_guarded_getters(text: str) -> None:
    """每个行 / record getter 都要带**源码级 `#if` 包住**的世代守卫。

    为什么必须是 `#if` 而不是「常驻调用 + 发布期空实现」：后者实测有热路径回归
    （`deployed-perf-bench` 同会话交替 A/B 五轮稳定复现：float32 字段读 +12.7%）。
    发布包里这些 getter 必须与「没有守卫」逐字节一致 ⇒ 调用点只能根本不存在。
    这条断言就是钉住这个形状，防止将来有人把它改回常驻调用。
    """
    lines = text.splitlines()
    guards = 0
    for i, line in enumerate(lines):
        s = line.strip()
        if s.startswith("#if ") and GUARD_COND in s:
            assert lines[i + 1].strip() == "TableVersion.Check(_version);", \
                f"#if 之后必须紧跟守卫调用，实际是 {lines[i + 1]!r}"
            assert lines[i + 2].strip() == "#endif", \
                f"守卫必须被 #endif 收口，实际是 {lines[i + 2]!r}"
            guards += 1
    assert guards > 0, "生成物里没有任何开发期世代守卫"
    # 反向：不允许出现没被 #if 包住的守卫调用（那就是常驻调用，发布期不再等价）
    bare = [i for i, l in enumerate(lines)
            if l.strip() == "TableVersion.Check(_version);"
            and lines[i - 1].strip() != f"#if {GUARD_COND}"]
    assert not bare, f"存在未包 #if 的守卫调用（行号 {bare[:5]}）"


def _table() -> TableResource:
    return TableResource(
        table="Item",
        primary="Id",
        fields=[
            FieldDef(name="Id", type="int32"),
            FieldDef(name="CodeName", type="string"),
            FieldDef(name="Category", type="int32"),
            FieldDef(name="Note", type="string", i18n=True),
            FieldDef(name="Secret", type="int32", server_only=True),
        ],
    )


def _item_with_records() -> tuple[TableResource, dict[str, RecordResource]]:
    drop = RecordResource(
        kind="record",
        name="ItemDropRange",
        fields=[
            FieldDef(name="Min", type="int32"),
            FieldDef(name="Max", type="int32"),
        ],
    )
    table = TableResource(
        table="Item",
        primary="Id",
        fields=[
            FieldDef(name="Id", type="int32"),
            FieldDef(name="Name", type="string", i18n=True),
            FieldDef(name="Rarity", type="ItemRarity"),
            FieldDef(name="DropRange", type="ItemDropRange"),
        FieldDef(name="Tags", type="vector<int32>"),
        ],
    )
    return table, {"ItemDropRange": drop}


def _chest_with_vector_records() -> tuple[TableResource, dict[str, RecordResource]]:
    drop = RecordResource(
        kind="record",
        name="DropReward",
        fields=[
            FieldDef(name="Min", type="int32"),
            FieldDef(name="Max", type="int32"),
        ],
    )
    table = TableResource(
        table="Chest",
        primary="Id",
        fields=[
            FieldDef(name="Id", type="int32"),
            FieldDef(name="Rewards", type="vector<DropReward>", excel_columns=3),
            FieldDef(name="Tags", type="vector<string>"),
            FieldDef(name="Types", type="vector<ItemRarity>"),
        ],
    )
    return table, {"DropReward": drop}


def test_accessor_model_shared_shape() -> None:
    model = build_accessor_model(_table(), (QueryIndex(kind="codename"),))
    assert [field.name for field in model.client_fields] == [
        "Id", "CodeName", "Category", "Note",
    ]
    assert model.primary.slot == 0
    assert model.indexes[0].kind == "codename"
    # codename 的槽位 = 约定字段 CodeName 在 client_fields 里的序号（不是索引上的字段名）
    assert model.indexes[0].slot == 1
    assert model.has_i18n is True


def test_csharp_pointer_row_and_query_api() -> None:
    text = golden_csharp()
    # 生成物整体包在命名空间里 ⇒ 行类型可以用裸名，不必靠 Row 后缀避开玩法类
    assert "namespace GameFramework.ConfigGen" in text
    # 行类型不再带 Row 后缀（`RowAt` 是运行时 API，不算）
    import re

    assert not re.search(r"\b\w+Row\b", text.replace("RowAt", "")), "不应再有 *Row 类型名"
    # 指针式行句柄 + 每表查询 API
    assert "public unsafe readonly struct Item" in text
    assert "internal Item(IntPtr row, int[] offsets, int version, int rowIndex)" in text
    assert "public static int Count => Table.Count;" in text
    assert "public static Item? ByID(int id)" in text
    assert "public static Item? ByIndex(int i)" in text
    assert "        if (p == IntPtr.Zero)" in text
    assert "            return null;" in text
    assert "            return new Item(p, t.OffsetsFor(p, MaxSlot), t.Version, idx);" in text
    # vtable slot = 4 + 2*字段序: Id=4, CodeName=6, Category=8
    assert "return WireReader.I32At(_row, _off[4]);" in text
    assert "            s = NStringCache.Decode((byte*)WireReader.IndirectAt(_row, _off[6]));" in text
    assert "return WireReader.I32At(_row, _off[8]);" in text
    assert_guarded_getters(text)
    assert "Secret" not in text  # server_only excluded


def test_csharp_exposes_bycodename() -> None:
    text = golden_csharp()
    assert "public static Item? ByCodeName(string codeName)" in text
    assert "Runtime.ByCodeName(TableName" in text
    # 行下标必须传给行句柄（per-field 字符串缓存按行下标索引）
    assert "return new Item(p, t.OffsetsFor(p, MaxSlot), t.Version, row);" in text
    # group 查询已砍：生成物里不该再出现
    assert "ByGroupKey" not in text
    assert "GroupKey" not in text


def test_lua_index_api_emits_real_codename_call() -> None:
    """codename 查询发**真实调用**（原生已有 `GD.ByCodeName` 绑定）。

    不做成「静默不生成」：调用方会拿到 `attempt to call a nil value`，比显式错误难排查。
    """
    text = golden_lua()
    # codename：真实调用（第 2 参 = CodeName 在**客户端字段序**里的下标，golden 表里 0-based=1）
    assert "function M.ByCodeName(codeName) return GD.ByCodeName(_tbl, 1, codeName, RowMeta) end" in text
    assert "ByGroupKey" not in text, "group 查询已砍"
    assert "function M.Count()" in text
    assert "function M.ByIndex(i)" in text
    assert "function M.ByID(id)" in text
    assert "Secret" not in text


def test_generation_is_deterministic() -> None:
    assert golden_csharp() == golden_csharp()
    assert golden_lua() == golden_lua()


def test_no_indexes_still_emits_query_api() -> None:
    csharp = golden_csharp(indexes=())
    lua = golden_lua(indexes=())
    assert "ByCodeName" not in csharp
    assert "function M.ByCodeName" not in lua
    assert "ByID" in csharp
    assert "ByID" in lua


# ---- record / vector / enum accessor resolution ----


def test_record_field_resolved_in_model() -> None:
    table, records = _item_with_records()
    model = build_accessor_model(table, (), records=records)
    drop = next(f for f in model.client_fields if f.name == "DropRange")
    assert drop.kind == "record"
    assert drop.record_name == "ItemDropRange"
    tags = next(f for f in model.client_fields if f.name == "Tags")
    assert tags.kind == "vector"
    assert tags.element_kind == "scalar"
    assert tags.element_type == "int32"


def test_csharp_record_accessor() -> None:
    table, records = _item_with_records()
    text = golden_csharp(table=table, indexes=(), records=records)
    # 嵌套 record 子行（指针式行句柄） + 类型化 enum + 向量容器
    # DropRange 表达式超 100 列 → 展开为 block body
    assert "public ItemAccessor.ItemDropRange DropRange" in text
    assert "            return new ItemAccessor.ItemDropRange((IntPtr)WireReader.IndirectAt(_row, _off[10]), _version);" in text
    assert "public unsafe readonly struct ItemDropRange" in text
    assert "return WireReader.I32(_row, 4);" in text
    assert "return WireReader.I32(_row, 6);" in text
    # enum 类型化（值 wire 是 byte）
    assert "return (ItemRarity)WireReader.I8At(_row, _off[8]);" in text
    assert_guarded_getters(text)
    # vector<int32> → NArray 单容器
    assert "            return new NArray<int>((byte*)WireReader.IndirectAt(_row, _off[12]), _version);" in text


def test_lua_record_accessor() -> None:
    table, records = _item_with_records()
    text = golden_lua(table=table, indexes=(), records=records)
    assert "local ItemDropRangeMeta = make_meta({" in text
    # record 内字段：slot 是**字节偏移**（4 + 2*字段序）
    assert "Min = function(s) return GD.I32(s, 4) end," in text
    # 嵌套 record 走原生 GD.Struct（meta 交给原生挂到 userdata 上）
    assert "GD.Struct(s, 10, ItemDropRangeMeta)" in text   # 外层 record 字段的字节偏移
    # 向量走惰性视图（不是逐元素建表）
    assert 'GD.Arr(s, 12, "i32", ArrayMeta)' in text
    assert "local out = {}" not in text


def test_lua_ref_keeps_bare_id_line() -> None:
    """跨表 ref 字段在 Lua 中必须同时保留裸 id 与类型化访问（与 C# 一致）。"""
    table = TableResource(
        table="Quest",
        primary="Id",
        fields=[
            FieldDef(name="Id", type="int32"),
            FieldDef(name="RewardItemId", type="int32", ref="Item.Id"),
        ],
    )
    text = golden_lua(table=table, indexes=())
    # 裸 id
    assert "RewardItemId = function(s) return GD.I32(s, 6) end," in text
    # 类型化访问：走 Config 懒加载注册表
    assert "Item = function(s) return Config.Item.ByID(GD.I32(s, 6)) end," in text


def test_csharp_vector_of_record() -> None:
    table, records = _chest_with_vector_records()
    text = golden_csharp(table=table, indexes=(), records=records)
    # vector<Record> → NStructArray 单容器；Rewards 表达式超 100 列 → block body
    assert "public NStructArray<ChestAccessor.DropReward> Rewards" in text
    assert "            return new NStructArray<ChestAccessor.DropReward>((byte*)WireReader.IndirectAt(_row, _off[6]), _version);" in text
    assert "            return new NStructArray<NString>((byte*)WireReader.IndirectAt(_row, _off[8]), _version);" in text
    assert "            return new NArray<ItemRarity>((byte*)WireReader.IndirectAt(_row, _off[10]), _version);" in text


def test_lua_vector_of_record_errors_at_use_not_at_build() -> None:
    """原生没有 record 元素的 tag ⇒ vector<record> 在 Lua 不可用。

    **不阻断导出**（C# 侧照常支持该字段）：生成一个明确报错的 getter，
    问题只在真正从 Lua 读该字段时暴露。
    """
    table, records = _chest_with_vector_records()
    text = golden_lua(table=table, indexes=(), records=records)
    assert "原生 gd 模块没有 record 元素的 tag" in text
    # 同一张表里**支持**的类型仍正常生成
    assert 'GD.Arr(s, 8, "s", ArrayMeta)' in text       # vector<string> → tag "s"
    assert 'GD.Arr(s, 10, "i8", ArrayMeta)' in text     # vector<enum> → tag "i8"
    assert "local out = {}" not in text


# ---------------------------------------------------------------------------
# 定宽布局（uniform）：行句柄不发偏移表，字段读用**字面量常量偏移**
#
# 前置：导出期按填充率决定该表是否定宽，并把 probe_row_layout 的 slot→offset
# 写进 layout manifest（表级常量）。生成器拿到 uniform_offsets 后走这条路径。
# ---------------------------------------------------------------------------


# _table() 的客户端字段（跳过 server_only 的 Secret）：
#   slot 4 = Id(int32) / slot 6 = CodeName(string) / slot 8 = Category(int32) / slot 10 = Note(string, i18n)
_OFFSETS = {4: 20, 6: 16, 8: 12, 10: 8}


def _uniform_csharp(offsets: dict[int, int] | None = None) -> str:
    from ct.export.canonical_accessor import render_csharp_accessor

    return render_csharp_accessor(_table(), (), uniform_offsets=offsets or _OFFSETS)


def test_uniform_row_has_no_offset_table() -> None:
    text = _uniform_csharp()
    assert "private readonly int[] _off;" not in text, "定宽行句柄不应携带偏移表"
    assert "OffsetsFor" not in text, "定宽表不应调用 ConfigTable.OffsetsFor"
    assert "MaxSlot" not in text, "定宽表不需要 MaxSlot"
    assert "internal Item(IntPtr row, int version, int rowIndex)" in text


def test_uniform_emits_literal_offsets() -> None:
    text = _uniform_csharp()
    assert "WireReader.I32At(_row, 20)" in text, "int32 字段应发射字面量偏移"
    assert "WireReader.IndirectAt(_row, 16)" in text, "字符串字段应发射字面量偏移"
    assert "_off[" not in text, "定宽下不应再出现偏移表下标"


def test_uniform_keeps_per_field_string_cache() -> None:
    """定宽只换偏移来源，per-field 行下标字符串缓存必须保留。"""
    text = _uniform_csharp()
    assert "NStringCache.Decode" in text
    assert "c[_index] = s;" in text


def test_uniform_query_api_passes_row_index_without_offsets() -> None:
    text = _uniform_csharp()
    assert "new Item(p, t.Version, idx)" in text
    assert "new Item(p, t.Version, i)" in text


def test_non_uniform_still_uses_offset_table() -> None:
    """对照：不传 uniform_offsets 时保持原样，避免影响未定宽的表。"""
    text = render_csharp_accessor(_table(), ())
    assert "private readonly int[] _off;" in text
    assert "_off[4]" in text
    assert "OffsetsFor" in text


def test_uniform_missing_offset_raises() -> None:
    """字段缺字面量偏移必须**报错**，不能默默发射 0（否则读到 vtable soffset）。"""
    import pytest

    with pytest.raises(ValueError, match="缺字面量偏移"):
        _uniform_csharp({4: 20})


# ---------------------------------------------------------------------------
# 枚举类型声明（生成物里的 (Enum)WireReader.I8At(...) cast 需要它才能编译）
# ---------------------------------------------------------------------------


def test_csharp_enum_declaration_matches_wire_ordinals() -> None:
    from ct.export.canonical_accessor import generate_csharp_enums
    from ct.schema.resources import EnumResource

    enums = {
        "ItemRarity": EnumResource(
            name="ItemRarity", values=[{"name": "common"}, {"name": "rare"}, {"name": "epic"}]
        )
    }
    text = generate_csharp_enums(enums)
    assert "namespace GameFramework.ConfigGen" in text
    assert "public enum ItemRarity : byte" in text
    assert "common = 0," in text
    assert "rare = 1," in text
    assert "epic = 2," in text


def test_lua_enum_table_matches_wire_ordinals() -> None:
    from ct.export.canonical_accessor import generate_lua_enums
    from ct.schema.resources import EnumResource

    enums = {"ItemRarity": EnumResource(name="ItemRarity", values=[{"name": "common"}, {"name": "rare"}])}
    text = generate_lua_enums(enums)
    assert "Enums.ItemRarity = {" in text
    assert "common = 0," in text
    assert "rare = 1," in text


def test_enum_declarations_are_deterministic() -> None:
    """枚举顺序 = wire 序号，输出必须对同一输入稳定（否则每次导出都改文件）。"""
    from ct.export.canonical_accessor import generate_csharp_enums, generate_lua_enums
    from ct.schema.resources import EnumResource

    enums = {
        "B": EnumResource(name="B", values=[{"name": "x"}, {"name": "y"}]),
        "A": EnumResource(name="A", values=[{"name": "p"}]),
    }
    assert generate_csharp_enums(enums) == generate_csharp_enums(enums)
    assert generate_lua_enums(enums) == generate_lua_enums(enums)
    # 按名字排序，与 dict 插入顺序无关
    assert generate_csharp_enums(enums).index("enum A") < generate_csharp_enums(enums).index("enum B")


# ---------------------------------------------------------------------------
# N5 验收：Lua accessor 必须符合**原生 gd 契约**
#
# 起因：新生成器此前引用了 10 个原生不存在的绑定、slot 用 0-based 序号、
# 并把容器包成 Lua 表（eager）。详见《Lua非标量访问开销实测.md》。
# 权威功能验收在游戏仓库：Client/Assets/Scripts/Lua/Tests/ConfigTest.lua。
# 下面是**生成物形态**的断言，防止回归。
# ---------------------------------------------------------------------------


def test_lua_uses_vtable_byte_offsets_not_field_indices() -> None:
    """原生按 **vtable 字节偏移**读（`4 + 2*字段序`），不是 0-based 字段序。"""
    text = golden_lua()
    assert "Id = function(s) return GD.I32(s, 4) end," in text
    assert "CodeName = function(s) return GD.Str(s, 6) end," in text
    # 旧的错误形态：把 0-based 序号当偏移传
    assert "GD.I32(_tbl, 0, s)" not in text


def test_lua_scalar_calls_use_two_args() -> None:
    """原生签名是 `GD.I32(row, slot)`；`(_tbl, slot, row)` 是错的。"""
    text = golden_lua()
    assert "_tbl, 0, s" not in text and "_tbl, 1, s" not in text
    assert "GD.I32(s," in text


def test_lua_has_no_eager_vector_table() -> None:
    """向量必须是惰性视图：**不得**逐次建 Lua 表（实测 568 B/次 + GC 67 ns/次）。"""
    table, records = _item_with_records()
    text = golden_lua(table=table, indexes=(), records=records)
    assert "local out = {}" not in text
    assert "GD.VecLen" not in text and "GD.VecI32" not in text
    assert 'GD.Arr(s, 12, "i32", ArrayMeta)' in text


def test_lua_array_metatable_has_pairs() -> None:
    """契约测试要求 `for _, v in pairs(tags)` 可用 ⇒ 需要 `__pairs`。"""
    text = golden_lua()
    assert "__pairs = ipairs" in text
    assert "__len" in text and "__index" in text


def test_lua_meta_is_attached_by_native_not_wrapper_table() -> None:
    """meta 交给原生挂到 userdata 上；**不得** `setmetatable({_row = ...}, Meta)` 包一层。"""
    table, records = _item_with_records()
    text = golden_lua(table=table, indexes=(), records=records)
    assert "setmetatable({_row" not in text
    assert "GD.Rec(" not in text          # 不存在这个绑定
    assert "function make_meta(readers)" in text
    assert "return { __index = function(self, key)" in text


def test_lua_table_handles_are_module_level() -> None:
    """表句柄在模块加载时取一次（原生固定槽位引用，跨加载有效）。"""
    text = golden_lua()
    assert 'local _tbl = GD.FindTable("Item")' in text


def test_lua_i18n_resolves_lazily_and_falls_back() -> None:
    """i18n 表句柄按 i18n 世代解析：主语言包里没有 i18n 表，解析结果必然是 nil。"""
    table = TableResource(
        table="Item",
        primary="Id",
        fields=[
            FieldDef(name="Id", type="int32"),
            FieldDef(name="Name", type="string", i18n=True),
        ],
    )
    text = render_lua_accessor(table, ())
    assert "local function i18n_table()" in text
    assert 'GD.FindTableI18n("Item_i18n")' in text
    assert "_i18nTbl = GD.FindTableI18n" in text       # 记忆（按世代）
    # i18n 表里的字段 slot=6；**按行下标**读取（3 参，无主键 slot）；缺失时回退主表原文
    assert "GD.I18nStr(i18n_table(), s, 6)" in text
    assert "or GD.Str(s, 6)" in text


def test_lua_i18n_read_is_by_row_index_not_primary_key() -> None:
    """i18n 读取必须按**行下标**，不能按主键二分。

    i18n 表 items 按主表行序排列，而导出器不排序 ⇒ 主表行序未必等于主键升序。
    在未排序的 items 上二分会静默查不到译文（实测：把行序反过来后译文全部回退成原文）。
    """
    table = TableResource(
        table="Item",
        primary="Id",
        fields=[
            FieldDef(name="Id", type="int32"),
            FieldDef(name="Name", type="string", i18n=True),
            FieldDef(name="Desc", type="string", i18n=True),
        ],
    )
    text = render_lua_accessor(table, ())
    # 3 参形态：不再传 pkSlot / i18nPkSlot
    assert "GD.I18nStr(i18n_table(), s, 6)" in text      # Name → i18n 字段序 0
    assert "GD.I18nStr(i18n_table(), s, 8)" in text      # Desc → i18n 字段序 1
    assert "GD.I18nStr(i18n_table(), s, 4, 4," not in text
    # 主表原文回退仍按主表槽位
    assert "or GD.Str(s, 6)" in text
    assert "or GD.Str(s, 8)" in text


def test_lua_i18n_memo_is_generation_keyed_not_nil_retry() -> None:
    """i18n 句柄记忆必须由世代驱动。

    只按「nil 才重试」记忆的写法在 zh → en → zh 这种来回切换下会把**已失效**的
    句柄一直用下去（原生 check_tbl 判断 data==NULL 就直接报错），必须每次比对世代。
    """
    table = TableResource(
        table="Item",
        primary="Id",
        fields=[
            FieldDef(name="Id", type="int32"),
            FieldDef(name="Name", type="string", i18n=True),
        ],
    )
    text = render_lua_accessor(table, ())
    assert "local _i18nTbl, _i18nGen = nil, nil" in text
    assert "local g = GD.I18nGen()" in text
    assert "if g ~= _i18nGen then" in text
    assert "_i18nGen = g" in text


def test_no_standalone_i18n_accessor_is_emitted() -> None:
    """稀疏 i18n 表**不再**单独产出一份 accessor —— 读路径已内联进主 accessor。

    Lua 侧从来没有 require 过那份模块（主 accessor 自己内联 `GD.I18nStr`），
    C# 侧它的唯一消费者就是主表的 getter ⇒ 对外没有任何用途，且会带出一个
    `Item_i18n` 这样的公开行类型。表本身照旧存在，只是不再有专属包装。
    """
    table = TableResource(
        table="Item",
        primary="Id",
        fields=[
            FieldDef(name="Id", type="int32"),
            FieldDef(name="Name", type="string", i18n=True),
        ],
    )
    for text in (render_csharp_accessor(table, ()), render_lua_accessor(table, ())):
        assert "Item_i18nAccessor" not in text
        assert "Item_i18nRow" not in text
    # C#：i18n 表句柄改用 Runtime.TryTable（该表只在加载了对应语言包时存在）
    cs = render_csharp_accessor(table, ())
    assert "Runtime.TryTable(I18nTableName)" in cs
    assert 'private const string I18nTableName = "Item_i18n";' in cs
    # 且公开 API 只有主表那一套（不再有第二套 Count/ByID/ByIndex）
    assert cs.count("public static int Count") == 1


def test_csharp_i18n_support_uses_i18n_epoch_and_null_tolerant_handle() -> None:
    """i18n 句柄用 **i18n 世代**守卫，而且**表缺席时也要认这个世代**。

    只判 `t != null` 的话，主语言（默认发布形态，根本不加载 i18n 包）每读一个多语言
    字段都要重走一遍 TryTable（字典查找 + 字符串哈希）。
    """
    table = TableResource(
        table="Item",
        primary="Id",
        fields=[
            FieldDef(name="Id", type="int32"),
            FieldDef(name="Name", type="string", i18n=True),
        ],
    )
    text = render_csharp_accessor(table, ())
    assert "_i18nTableVersion = TableVersion.I18nCurrent;" in text
    assert "_i18nTableVersion == TableVersion.I18nCurrent" in text
    assert "_i18nStrCacheVersion = TableVersion.I18nCurrent;" in text
    # 缺席时读回 null ⇒ 调用方回退主表原文
    assert "if (t == null)" in text
    # 主表自己的缓存世代仍是 Current（缓存的是主表原文，与语言无关）
    assert "_strCacheVersion = TableVersion.Current;" in text


def test_csharp_i18n_field_falls_back_when_translation_missing() -> None:
    """i18n 行在、但该字段**没有译文**时也要回退主表原文。

    原先 C# 是 `if (i18n.HasValue) return i18n.Value.Name;` —— 行在就无条件返回，
    哪怕返回 null 也不回退；Lua 却是 `v ~= nil and v or 原文`。两边语义不一致。
    """
    table = TableResource(
        table="Item",
        primary="Id",
        fields=[
            FieldDef(name="Id", type="int32"),
            FieldDef(name="Name", type="string", i18n=True),
        ],
    )
    text = render_csharp_accessor(table, ())
    assert "string v = ItemAccessor.I18nName(_index);" in text
    assert "if (v != null)" in text
    # 回退分支紧随其后（同一 getter 内）
    assert "string[] c = ItemAccessor.NameCache;" in text


def test_csharp_i18n_read_uses_i18n_table_literal_offsets() -> None:
    """定宽 i18n 表要用**它自己的** slot_offsets 发字面量偏移（与主表是两份常量）。"""
    table = TableResource(
        table="Item",
        primary="Id",
        fields=[
            FieldDef(name="Id", type="int32"),
            FieldDef(name="Name", type="string", i18n=True),
            FieldDef(name="Desc", type="string", i18n=True),
        ],
    )
    # i18n 表字段序 = [Id(主键), Name, Desc] ⇒ slot 4 / 6 / 8
    model = build_accessor_model(
        table, (), uniform_offsets={4: 28, 6: 24, 8: 20}, i18n_uniform_offsets={4: 12, 6: 8, 8: 4}
    )
    from ct.export.canonical_accessor import generate_csharp_accessor

    text = generate_csharp_accessor(model)
    assert "NStringCache.Decode((byte*)WireReader.IndirectAt(p, 8));" in text   # Name
    assert "NStringCache.Decode((byte*)WireReader.IndirectAt(p, 4));" in text   # Desc
    # 无偏移时退回槽位读（i18n 表不是定宽）
    slot_text = render_csharp_accessor(table, ())
    assert "NStringCache.Decode((byte*)WireReader.Indirect(p, 6));" in slot_text
    assert "NStringCache.Decode((byte*)WireReader.Indirect(p, 8));" in slot_text


def test_csharp_i18n_fallback_uses_per_field_row_index_cache() -> None:
    """多语言字段的**回退分支**必须走 per-field 行下标缓存。

    起因（性能实测）：主语言（`primary_lang=zh`，**不加载 i18n 包**，也就是默认发布状态）
    走的正是回退路径。此前它直接 `NStringCache.Decode` ⇒ 每次读都 UTF-8 解码 + 新建 string，
    实测 **59.4 ns + 59.4 字节/次**；而同样形状的非 i18n 字符串字段早就有这份缓存。
    """
    table = TableResource(
        table="Item",
        primary="Id",
        fields=[
            FieldDef(name="Id", type="int32"),
            FieldDef(name="Name", type="string", i18n=True),
        ],
    )
    text = render_csharp_accessor(table, ())
    # 回退分支要有缓存三件套
    assert "string[] c = ItemAccessor.NameCache;" in text
    assert "string s = c[_index];" in text
    assert "c[_index] = s;" in text
    # 缓存字段本身要被产出
    assert "internal static string[] NameCache" in text
    assert "private static string[] _nameCache;" in text
    # 且缓存世代是**主表**世代（缓存的是主表原文，与语言无关）
    assert "_strCacheVersion = TableVersion.Current;" in text


def test_csharp_non_i18n_string_field_still_cached() -> None:
    """回归：非 i18n 字符串字段的缓存不能被这次改动弄丢。"""
    table = TableResource(
        table="Item",
        primary="Id",
        fields=[
            FieldDef(name="Id", type="int32"),
            FieldDef(name="Code", type="string"),
        ],
    )
    text = render_csharp_accessor(table, ())
    assert "string[] c = ItemAccessor.CodeCache;" in text
    assert "internal static string[] CodeCache" in text


def _uniform_fixture_table() -> TableResource:
    return TableResource(
        table="Item",
        primary="Id",
        fields=[
            FieldDef(name="Id", type=ScalarType(name="int32")),
            FieldDef(name="Name", type=ScalarType(name="string")),
            FieldDef(name="Price", type=ScalarType(name="float")),
            FieldDef(name="Cnt", type=ScalarType(name="int16")),
            FieldDef(name="On", type=ScalarType(name="bool")),
            FieldDef(name="Tags", type=VectorType(element=ScalarType(name="int32"))),
        ],
    )


# slot = 4 + 2*字段序 → 这里给的偏移是任取的常量，只为断言发射形态
_UNIFORM_OFFSETS = {4: 28, 6: 24, 8: 20, 10: 19, 12: 18, 14: 4}


def test_lua_uniform_table_uses_literal_offsets() -> None:
    """定宽表的 Lua 访问器必须发**字面量偏移**读（省掉每次读的 vtable 走查）。

    实测（同 session 交替 A/B，6685 行表）：int32 字段 **−5.6%**、字符串 **−5.7%**、
    3 字段合计 **−6.1%**；`Arr` 取视图**无收益**（成本在缓存查找与 tag 解析上）——
    换算只为让「定宽表 = 全字面量偏移」这条规则没有例外，好读也好测。
    """
    model = build_accessor_model(_uniform_fixture_table(), (), uniform_offsets=_UNIFORM_OFFSETS)
    text = generate_lua_accessor(model)
    assert "Id = function(s) return GD.I32Off(s, 28) end," in text
    assert "Name = function(s) return GD.StrOff(s, 24) end," in text
    assert "Price = function(s) return GD.F32Off(s, 20) end," in text
    assert "Cnt = function(s) return GD.I16Off(s, 19) end," in text
    assert "On = function(s) return GD.I8Off(s, 18) ~= 0 end," in text
    assert 'Tags = function(s) return GD.ArrOff(s, 4, "i32", ArrayMeta) end,' in text
    assert "GD.I32(s," not in text          # 槽位形态不该再出现
    assert "定宽布局" in text                # 生成物里点明这条规则


def test_lua_non_uniform_table_keeps_slot_reads() -> None:
    """非定宽表**必须**继续走槽位读 —— 偏移不是表级常量，字面量化会读错。"""
    model = build_accessor_model(_uniform_fixture_table(), ())
    text = generate_lua_accessor(model)
    assert "Id = function(s) return GD.I32(s, 4) end," in text
    assert "Off(s," not in text
    assert "定宽布局" not in text


def test_lua_bool_scalar_returns_boolean_not_number() -> None:
    """Lua 侧 bool **标量**必须返回 boolean，不能返回 0/1。

    起因：`_lua_scalar_expr` 里判的是 `field.kind == "bool"`，而模型的 kind 只会是
    vector/record/enum/string/scalar —— **从来没有 "bool"**，于是那是死代码，
    bool 一直返回数字。这在 Lua 里是坑：**0 是真值**，`if row.Stack then` 对 false 也成立。
    （bool **向量**走原生的 `GD_T_BOOL`，本来就推 boolean ⇒ 两条路径还不一致。）
    """
    table = TableResource(
        table="UIConfig",
        primary="Id",
        fields=[
            FieldDef(name="Id", type="int32"),
            FieldDef(name="Stack", type="bool"),
        ],
    )
    text = render_lua_accessor(table, ())
    assert "Stack = function(s) return GD.I8(s, 6) ~= 0 end," in text
    assert "return GD.I8(s, 6) end," not in text


def test_lua_record_slot_is_its_own_field_index() -> None:
    """嵌套 record 的字段槽位是 **record 自己**的字段序（原生 GD.Struct 返回子表 userdata）。"""
    table, records = _item_with_records()
    text = golden_lua(table=table, indexes=(), records=records)
    assert "Min = function(s) return GD.I32(s, 4) end," in text
    assert "Max = function(s) return GD.I32(s, 6) end," in text
