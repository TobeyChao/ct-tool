"""Canonical C#/Lua accessor + Code/Group API tests (harmony-aligned, pointer-based row handle)."""

from __future__ import annotations

from ct.export.canonical_accessor import golden_csharp, golden_lua
from ct.export.canonical_accessor_model import build_accessor_model
from ct.schema.indexes import QueryIndex
from ct.schema.resources import (
    FieldDef,
    RecordResource,
    TableResource,
)


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
            FieldDef(name="Tags", type="vector<int32>", separator=","),
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
    model = build_accessor_model(
        _table(),
        (QueryIndex("code", "CodeName"), QueryIndex("group", "Category")),
    )
    assert [field.name for field in model.client_fields] == [
        "Id", "CodeName", "Category", "Note",
    ]
    assert model.primary.slot == 0
    assert model.indexes[0].kind == "code"
    assert model.indexes[0].field == "CodeName"
    assert model.indexes[0].slot == 1
    assert model.has_i18n is True


def test_csharp_pointer_row_and_query_api() -> None:
    text = golden_csharp()
    # 指针式行句柄 + 每表查询 API
    assert "public unsafe readonly struct ItemRow" in text
    assert "internal ItemRow(IntPtr row, int version)" in text
    assert "public static int Count => Runtime.Count(TableName);" in text
    assert "public static ItemRow? ByID(int id)" in text
    assert "public static ItemRow? ByIndex(int i)" in text
    assert "return p == IntPtr.Zero ? (ItemRow?)null : new ItemRow(p, Runtime.Version(TableName));" in text
    # vtable slot = 4 + 2*字段序: Id=4, CodeName=6, Category=8
    assert "public int Id => WireReader.I32(_row, 4);" in text
    assert "public string CodeName => new NString((byte*)WireReader.Indirect(_row, 6), _version);" in text
    assert "public int Category => WireReader.I32(_row, 8);" in text
    assert "Secret" not in text  # server_only excluded


def test_csharp_exposes_bycode_and_bygroupkey() -> None:
    text = golden_csharp()
    assert "public static ItemRow? ByCode(string code)" in text
    assert "IReadOnlyList<ItemRow> ByGroupKey(int value)" in text
    assert "Runtime.ByCode(TableName" in text
    assert "Runtime.GroupKey(TableName" in text


def test_lua_exposes_bycode_and_bygroupkey() -> None:
    text = golden_lua()
    assert "function M.ByCode(code)" in text
    assert "function M.ByGroupKey(value)" in text
    assert "function M.Count()" in text
    assert "function M.ByIndex(i)" in text
    assert "function M.ByID(id)" in text
    assert "GD.IndexCode" in text
    assert "GD.IndexGroup" in text
    assert "Secret" not in text


def test_generation_is_deterministic() -> None:
    assert golden_csharp() == golden_csharp()
    assert golden_lua() == golden_lua()


def test_no_indexes_still_emits_query_api() -> None:
    csharp = golden_csharp(indexes=())
    lua = golden_lua(indexes=())
    assert "ByCode" not in csharp
    assert "ByGroupKey" not in csharp
    assert "function M.ByCode" not in lua
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
    assert "ItemAccessor.ItemDropRangeRow DropRange => new ItemAccessor.ItemDropRangeRow(WireReader.Indirect(_row, 10), _version);" in text
    assert "public unsafe readonly struct ItemDropRangeRow" in text
    assert "public int Min => WireReader.I32(_row, 4);" in text
    assert "public int Max => WireReader.I32(_row, 6);" in text
    # enum 类型化（值 wire 是 byte）
    assert "public ItemRarity Rarity => (ItemRarity)WireReader.I8(_row, 8);" in text
    # vector<int32> → NArray 单容器
    assert "public NArray<int> Tags => new NArray<int>(_row, 12, _version);" in text


def test_lua_record_accessor() -> None:
    table, records = _item_with_records()
    text = golden_lua(table=table, indexes=(), records=records)
    assert "local ItemDropRangeMeta = {" in text
    assert "Min = function(s) return GD.I32(_tbl, 0, s) end," in text
    assert "setmetatable({_row = GD.Rec(_tbl, 3, s)}, ItemDropRangeMeta)" in text
    assert "GD.VecI32(_tbl, 4, s, i - 1)" in text


def test_csharp_vector_of_record() -> None:
    table, records = _chest_with_vector_records()
    text = golden_csharp(table=table, indexes=(), records=records)
    # vector<Record> → NStructArray 单容器
    assert "public NStructArray<ChestAccessor.DropRewardRow> Rewards => new NStructArray<ChestAccessor.DropRewardRow>(_row, 6, _version);" in text
    assert "public NStructArray<NString> Tags => new NStructArray<NString>(_row, 8, _version);" in text
    assert "public NArray<ItemRarity> Types => new NArray<ItemRarity>(_row, 10, _version);" in text


def test_lua_vector_of_record() -> None:
    table, records = _chest_with_vector_records()
    text = golden_lua(table=table, indexes=(), records=records)
    assert "setmetatable({_row = GD.RecVec(_tbl, 1, s, i - 1)}, DropRewardMeta)" in text
    assert "GD.VecStr(_tbl, 2, s, i - 1)" in text
    assert "GD.VecI8(_tbl, 3, s, i - 1)" in text
