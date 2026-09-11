"""Canonical binary serialization round-trip tests (5.3).

A small manual wire reader (mirroring the generated-reader layout: slots
follow client-field order, strings/records/vectors are uoffset references)
verifies byte-level round trips for empty, partial and full groups.
"""

from __future__ import annotations

import struct

from flatbuffers import encode, number_types as ntypes
from flatbuffers.table import Table

from ct.export.canonical_binary import build_canonical_table_bytes
from ct.schema.resources import (
    EnumResource,
    FieldDef,
    RecordResource,
    TableResource,
)


def _records() -> dict[str, RecordResource]:
    return {
        "DropReward": RecordResource(
            name="DropReward",
            fields=[
                FieldDef(name="ItemId", type="int32"),
                FieldDef(name="Count", type="int32"),
            ],
        ),
    }


def _enums() -> dict[str, EnumResource]:
    return {"ItemRarity": EnumResource(name="ItemRarity", values=["Common", "Rare"])}


def _table() -> TableResource:
    return TableResource(
        table="Item",
        primary="Id",
        fields=[
            FieldDef(name="Id", type="int32"),
            FieldDef(name="Rarity", type="ItemRarity"),
            FieldDef(name="Tags", type="vector<int32>"),
            FieldDef(name="Rewards", type="vector<DropReward>"),
            FieldDef(name="Note", type="string"),
        ],
    )


class _WireReader:
    """Minimal canonical-buffer reader following the writer layout.

    Slots follow client-field order; strings/records/vectors are uoffset
    references stored at ``Pos + field_offset`` (mirrors generated readers).
    """

    U32 = ntypes.UOffsetTFlags.packer_type
    I32 = ntypes.Int32Flags.packer_type

    def __init__(self, data: bytes) -> None:
        self.buf = memoryview(data)
        root_uoff = encode.Get(self.U32, self.buf, 0)
        self.container = Table(self.buf, root_uoff)

    def rows(self) -> list[dict]:
        # 容器表字段 0 = items，字段在 vtable 里的字节偏移是 4 + 2*字段序。
        # 原先写 Offset(0) 是错的：它读的是 vtable 头部的 vtable_size，
        # 只因「2 字段时 vtable_size(8) == items 对象内偏移(8)」而侥幸成立；
        # 容器新增第 3 个字段（哈希索引）后该巧合消失，暴露出这个潜伏 bug。
        items_field = self.container.Offset(4)
        if items_field == 0:
            return []
        length = self.container.VectorLen(items_field)
        data_start = self.container.Vector(items_field)
        out: list[dict] = []
        for index in range(length):
            element = data_start + 4 * index
            row_pos = element + encode.Get(self.U32, self.buf, element)
            out.append(self._read_row(row_pos))
        return out

    def _read_row(self, pos: int) -> dict:
        row = Table(self.buf, pos)
        return {
            "Id": self._scalar(row, 0, ntypes.Int32Flags, 0),
            "Rarity": self._scalar(row, 1, ntypes.Int8Flags, 0),
            "Tags": self._vector_int32(row, 2),
            "Rewards": self._vector_records(row, 3),
            "Note": self._string(row, 4),
        }

    def _scalar(self, table: Table, index: int, flags, default):
        field_off = table.Offset(4 + 2 * index)
        if field_off == 0:
            return default
        return table.Get(flags, table.Pos + field_off)

    def _string(self, table: Table, index: int) -> str | None:
        field_off = table.Offset(4 + 2 * index)
        if field_off == 0:
            return None
        return table.String(table.Pos + field_off).decode("utf-8")

    def _vector_int32(self, table: Table, index: int) -> list[int]:
        field_off = table.Offset(4 + 2 * index)
        if field_off == 0:
            return []
        length = table.VectorLen(field_off)
        start = table.Vector(field_off)
        return [
            encode.Get(self.I32, self.buf, start + 4 * i)
            for i in range(length)
        ]

    def _vector_records(self, table: Table, index: int) -> list[dict]:
        field_off = table.Offset(4 + 2 * index)
        if field_off == 0:
            return []
        length = table.VectorLen(field_off)
        start = table.Vector(field_off)
        out: list[dict] = []
        for i in range(length):
            element = start + 4 * i
            child_pos = element + encode.Get(self.U32, self.buf, element)
            record = Table(self.buf, child_pos)
            out.append(
                {
                    "ItemId": self._scalar(record, 0, ntypes.Int32Flags, 0),
                    "Count": self._scalar(record, 1, ntypes.Int32Flags, 0),
                }
            )
        return out


def _read(data: bytes) -> list[dict]:
    return _WireReader(data).rows()


def _build(rows: list[dict]) -> bytes:
    return build_canonical_table_bytes(
        rows, _table(), records=_records(), enums=_enums()
    )


def test_round_trip_full_groups() -> None:
    rows = [
        {
            "Id": 1,
            "Rarity": "Rare",
            "Tags": [1, 2, 5],
            "Rewards": [{"ItemId": 100, "Count": 2}, {"ItemId": 200, "Count": 3}],
            "Note": "主语言",
        },
        {
            "Id": 2,
            "Rarity": "Common",
            "Tags": [],
            "Rewards": [],
            "Note": None,
        },
    ]
    decoded = _read(_build(rows))
    assert decoded[0]["Id"] == 1
    assert decoded[0]["Rarity"] == 1  # Rare
    assert decoded[0]["Tags"] == [1, 2, 5]
    assert decoded[0]["Rewards"] == [{"ItemId": 100, "Count": 2}, {"ItemId": 200, "Count": 3}]
    assert decoded[0]["Note"] == "主语言"
    assert decoded[1]["Rewards"] == []
    assert decoded[1]["Tags"] == []
    assert decoded[1]["Note"] is None


def test_empty_and_partial_groups_round_trip() -> None:
    rows = [
        {"Id": 3, "Rarity": "Common", "Tags": [], "Rewards": [{"ItemId": 7, "Count": 1}], "Note": "x"},
    ]
    decoded = _read(_build(rows))
    assert decoded[0]["Rewards"] == [{"ItemId": 7, "Count": 1}]
    assert decoded[0]["Tags"] == []


def test_server_only_excluded() -> None:
    table = _table().model_copy(
        update={
            "fields": [
                *[f for f in _table().fields],
                FieldDef(name="Secret", type="int32", server_only=True),
            ]
        }
    )
    data = build_canonical_table_bytes(
        [{"Id": 1, "Rarity": "Common", "Tags": [], "Rewards": [], "Note": "", "Secret": 42}],
        table,
        records=_records(),
        enums=_enums(),
    )
    decoded = _read(data)
    assert "Secret" not in decoded[0]


# ---------------------------------------------------------------------------
# uniform（定宽）布局：同一张表的所有行必须共享同一个 vtable
#
# 背景：非 uniform 下，标量值为默认值、枚举为第 0 项、string/record 为 None 时
# flatbuffers 会**省略槽位**，导致同表出现多种 vtable。uniform=True 的目标就是
# 无条件写出每个槽位，使 slot→offset 成为**表级常量**（生成器据此发射字面量偏移）。
#
# 回归点：**枚举分支曾经漏了 uniform 处理**（仍是 PrependInt8Slot(.., 0)），
# 于是「值为第 0 个枚举项」的行仍然省略槽位 ⇒ 同表多种 vtable；
# 更糟的是 probe_row_layout 用空白行推导时会把该槽位推成 offset 0，
# 生成器据此发射的字面量偏移会读到 vtable soffset —— **静默读错整行**。
# 下面用「含默认枚举值的行」把这条钉死。
# ---------------------------------------------------------------------------


def _vtable_contents(data: bytes) -> list[bytes]:
    """返回每一行 vtable 的内容（去重后用于判断是否「单一 vtable」）。"""
    reader = _WireReader(data)
    out: list[bytes] = []
    items_field = reader.container.Offset(4)
    if items_field == 0:
        return out
    length = reader.container.VectorLen(items_field)
    start = reader.container.Vector(items_field)
    for index in range(length):
        element = start + 4 * index
        row_pos = element + encode.Get(reader.U32, reader.buf, element)
        vt = row_pos - encode.Get(reader.I32, reader.buf, row_pos)
        vt_len = encode.Get(ntypes.Uint16Flags.packer_type, reader.buf, vt)
        out.append(bytes(reader.buf[vt:vt + vt_len]))
    return out


def _uniform_rows() -> list[dict]:
    """混合数据：第 0 个枚举值（Common，= 默认）、非默认枚举、None 字符串、空向量。"""
    return [
        {"Id": 1, "Rarity": "Common", "Tags": [], "Rewards": [], "Note": None},
        {"Id": 2, "Rarity": "Rare", "Tags": [7], "Rewards": [], "Note": None},
        {"Id": 0, "Rarity": "Common", "Tags": [], "Rewards": [], "Note": ""},
    ]


def test_uniform_yields_single_vtable_with_default_enum() -> None:
    """含「第 0 个枚举值」的行也必须占位 —— 否则同表出现多种 vtable。"""
    data = build_canonical_table_bytes(
        _uniform_rows(), _table(), records=_records(), enums=_enums(), uniform=True
    )
    contents = _vtable_contents(data)
    assert len(contents) == 3
    assert len(set(contents)) == 1, "uniform=True 下同表所有行必须共享同一个 vtable"


def test_non_uniform_may_vary_but_uniform_must_not() -> None:
    """对照：非 uniform 允许多种 vtable，uniform 不允许。"""
    rows = _uniform_rows()
    normal = _vtable_contents(
        build_canonical_table_bytes(rows, _table(), records=_records(), enums=_enums())
    )
    uniform = _vtable_contents(
        build_canonical_table_bytes(
            rows, _table(), records=_records(), enums=_enums(), uniform=True
        )
    )
    assert len(set(normal)) > 1, "这组数据本应触发多种 vtable（回归数据集失效了？）"
    assert len(set(uniform)) == 1


def test_uniform_probe_layout_matches_every_row() -> None:
    """probe_row_layout 的 slot→offset 必须对**每一行**成立，不能只对第一行成立。"""
    from ct.export.canonical_binary import probe_row_layout

    rows = _uniform_rows()
    data = build_canonical_table_bytes(
        rows, _table(), records=_records(), enums=_enums(), uniform=True
    )
    probe = probe_row_layout(_table(), records=_records(), enums=_enums())

    reader = _WireReader(data)
    items_field = reader.container.Offset(4)
    length = reader.container.VectorLen(items_field)
    start = reader.container.Vector(items_field)

    client = _table().fields
    for index in range(length):
        element = start + 4 * index
        row_pos = element + encode.Get(reader.U32, reader.buf, element)
        vt = row_pos - encode.Get(reader.I32, reader.buf, row_pos)
        for field_index in range(len(client)):
            slot = 4 + 2 * field_index
            real = encode.Get(ntypes.Uint16Flags.packer_type, reader.buf, vt + slot)
            assert real == probe.get(slot, 0), (
                f"第 {index} 行 slot {slot}：真实 offset={real}，probe 给的是 {probe.get(slot, 0)}"
            )


def test_uniform_enum_slot_is_never_absent() -> None:
    """枚举槽位在 uniform 下**永不为 0（缺失）**，这是上面两条的根因。"""
    data = build_canonical_table_bytes(
        _uniform_rows(), _table(), records=_records(), enums=_enums(), uniform=True
    )
    reader = _WireReader(data)
    items_field = reader.container.Offset(4)
    length = reader.container.VectorLen(items_field)
    start = reader.container.Vector(items_field)
    for index in range(length):
        element = start + 4 * index
        row_pos = element + encode.Get(reader.U32, reader.buf, element)
        vt = row_pos - encode.Get(reader.I32, reader.buf, row_pos)
        enum_slot = 4 + 2 * 1          # 字段序 1 = Rarity
        offset = encode.Get(ntypes.Uint16Flags.packer_type, reader.buf, vt + enum_slot)
        assert offset != 0, f"第 {index} 行的枚举槽位缺失（uniform 下不应发生）"


def test_uniform_default_enum_reads_as_first_value() -> None:
    """语义不变：缺省枚举（第 0 项）与非 uniform 下读到的默认值一致。"""
    rows = _uniform_rows()
    uniform = _read(
        build_canonical_table_bytes(
            rows, _table(), records=_records(), enums=_enums(), uniform=True
        )
    )
    assert [r["Rarity"] for r in uniform] == [0, 1, 0]


def test_uniform_absent_string_reads_as_empty_not_none() -> None:
    """**语义变更（有意）**：uniform 下「缺失的 string」变成空串，不再返回 None。"""
    rows = _uniform_rows()
    normal = _read(build_canonical_table_bytes(rows, _table(), records=_records(), enums=_enums()))
    uniform = _read(
        build_canonical_table_bytes(
            rows, _table(), records=_records(), enums=_enums(), uniform=True
        )
    )
    assert normal[0]["Note"] is None          # 非 uniform：槽位缺失 → None
    assert uniform[0]["Note"] == ""           # uniform：写空串 → ""
    assert uniform[2]["Note"] == ""           # 本来就写了空串，两边一致
    # 语义变更只影响「缺失 → 空串」，数值/枚举/向量不受影响
    assert [r["Id"] for r in normal] == [r["Id"] for r in uniform]
    assert [r["Tags"] for r in normal] == [r["Tags"] for r in uniform]


# ---------------------------------------------------------------------------
# 定宽布局的填充率统计与 vtable 计数（导出期决策 + 硬断言的基础）
# ---------------------------------------------------------------------------


def test_count_vtables_one_when_uniform() -> None:
    from ct.export.canonical_binary import count_vtables

    rows = _uniform_rows()
    normal = build_canonical_table_bytes(rows, _table(), records=_records(), enums=_enums())
    uniform = build_canonical_table_bytes(
        rows, _table(), records=_records(), enums=_enums(), uniform=True
    )
    assert count_vtables(normal) > 1     # 这组数据本应产生多种 vtable
    assert count_vtables(uniform) == 1


def test_written_slot_ratio_is_one_when_every_slot_present() -> None:
    from ct.export.canonical_binary import written_slot_ratio

    # 全部字段都有非默认值 → 填充率 100%
    rows = [
        {"Id": 1, "Rarity": "Rare", "Tags": [1], "Rewards": [{"ItemId": 1, "Count": 1}], "Note": "x"}
    ]
    data = build_canonical_table_bytes(rows, _table(), records=_records(), enums=_enums())
    assert written_slot_ratio(data, len(_table().fields)) == 1.0


def test_written_slot_ratio_counts_defaults_as_absent() -> None:
    from ct.export.canonical_binary import written_slot_ratio

    # Id=0（标量默认）、Rarity=第 0 项、Note=None → 都省略；
    # Tags / Rewards 是向量，**永远写出**（含空向量）
    rows = [{"Id": 0, "Rarity": "Common", "Tags": [], "Rewards": [], "Note": None}]
    data = build_canonical_table_bytes(rows, _table(), records=_records(), enums=_enums())
    assert written_slot_ratio(data, 5) == 2 / 5


def test_uniform_raises_written_slot_ratio_to_full() -> None:
    from ct.export.canonical_binary import written_slot_ratio

    rows = _uniform_rows()
    normal = written_slot_ratio(
        build_canonical_table_bytes(rows, _table(), records=_records(), enums=_enums()),
        len(_table().fields),
    )
    uniform = written_slot_ratio(
        build_canonical_table_bytes(
            rows, _table(), records=_records(), enums=_enums(), uniform=True
        ),
        len(_table().fields),
    )
    assert normal < 1.0
    assert uniform == 1.0


def test_probe_row_layout_returns_nonzero_offsets_for_all_uniform_slots() -> None:
    """定宽下每个槽位都必须有非 0 偏移 —— 0 会让字面量访问器读到 vtable soffset。"""
    from ct.export.canonical_binary import probe_row_layout

    layout = probe_row_layout(_table(), records=_records(), enums=_enums())
    assert layout, "probe_row_layout 不应为空"
    zero = {slot: off for slot, off in layout.items() if off == 0}
    assert not zero, f"这些槽位在定宽下仍缺偏移: {zero}"


# ---------------------------------------------------------------------------
# 二级查询索引（Code / Group）：容器 slot 3 / 4
# ---------------------------------------------------------------------------


def _indexed_table() -> tuple[TableResource, dict, dict]:
    from ct.schema.resources import QueryIndex

    table = TableResource(
        table="Item",
        primary="Id",
        fields=[
            FieldDef(name="Id", type="int32"),
            FieldDef(name="CodeName", type="string"),
            FieldDef(name="Category", type="int32"),
        ],
        indexes=(
            QueryIndex(kind="codename"),
            QueryIndex(kind="group", field="Category"),
        ),
    )
    return table, {}, {}


def _container_slots(data: bytes) -> list[int]:
    """返回容器 vtable 里非 0 的 slot 编号。"""
    root = struct.unpack_from("<i", data, 0)[0]
    vt = root - struct.unpack_from("<i", data, root)[0]
    vt_len = struct.unpack_from("<H", data, vt)[0]
    return [n for n in range((vt_len - 4) // 2) if struct.unpack_from("<H", data, vt + 4 + 2 * n)[0]]


def test_no_indexes_means_no_extra_container_slots() -> None:
    table = TableResource(
        table="Item",
        primary="Id",
        fields=[FieldDef(name="Id", type="int32")],
    )
    data = build_canonical_table_bytes([{"Id": 1}], table, records={}, enums={})
    assert _container_slots(data) == [0, 1, 2]      # items / index / hash


def test_codename_and_group_indexes_add_container_slots() -> None:
    """Group 现在占**两个**槽：4 = 排序对（行来源），5 = 区间哈希（O(1) 定位，取代二分）。"""
    table, records, enums = _indexed_table()
    rows = [{"Id": 1, "CodeName": "a", "Category": 7}]
    data = build_canonical_table_bytes(rows, table, records=records, enums=enums)
    assert _container_slots(data) == [0, 1, 2, 3, 4, 5]


def test_group_only_index_still_declares_slot_five() -> None:
    """只声明 Group（无 Code）时，vtable 槽位数仍要覆盖 slot 5（Group 排序对 + 区间哈希）。"""
    from ct.schema.resources import QueryIndex

    table = TableResource(
        table="Item",
        primary="Id",
        fields=[FieldDef(name="Id", type="int32"), FieldDef(name="Category", type="int32")],
        indexes=(QueryIndex(kind="group", field="Category"),),
    )
    data = build_canonical_table_bytes(
        [{"Id": 1, "Category": 7}], table, records={}, enums={}
    )
    assert _container_slots(data) == [0, 1, 2, 4, 5]


def test_codename_buckets_are_fnv1a_keyed_and_point_at_rows() -> None:
    from ct.export.index_query import fnv1a_64

    table, records, enums = _indexed_table()
    rows = [
        {"Id": 1, "CodeName": "consumable", "Category": 1},
        {"Id": 2, "CodeName": "equipment", "Category": 2},
    ]
    data = build_canonical_table_bytes(rows, table, records=records, enums=enums)
    # 容器 slot 3 = CodeName 索引
    root = struct.unpack_from("<i", data, 0)[0]
    vt = root - struct.unpack_from("<i", data, root)[0]
    code_off = struct.unpack_from("<H", data, vt + 10)[0]
    vec = root + code_off + struct.unpack_from("<i", data, root + code_off)[0]
    count = struct.unpack_from("<i", data, vec)[0]
    buckets = [
        struct.unpack_from("<i", data, vec + 4 + i * 4)[0] for i in range(count)
    ]
    mask = count - 1
    # 桶里存 rowIndex + 1
    assert buckets[fnv1a_64("consumable") & mask] == 1
    assert buckets[fnv1a_64("equipment") & mask] == 2
    assert buckets.count(0) == count - 2      # 其余为空


def test_group_entries_are_sorted_by_key() -> None:
    table, records, enums = _indexed_table()
    rows = [
        {"Id": 1, "CodeName": "a", "Category": 9},
        {"Id": 2, "CodeName": "b", "Category": 3},
        {"Id": 3, "CodeName": "c", "Category": 9},
    ]
    data = build_canonical_table_bytes(rows, table, records=records, enums=enums)
    root = struct.unpack_from("<i", data, 0)[0]
    vt = root - struct.unpack_from("<i", data, root)[0]
    group_off = struct.unpack_from("<H", data, vt + 12)[0]
    vec = root + group_off + struct.unpack_from("<i", data, root + group_off)[0]
    # 向量是**扁平 int32 对** key,row,… ⇒ 长度 = 条目数 * 2
    length = struct.unpack_from("<i", data, vec)[0]
    entries = [
        (
            struct.unpack_from("<i", data, vec + 4 + i * 8)[0],
            struct.unpack_from("<i", data, vec + 4 + i * 8 + 4)[0],
        )
        for i in range(length // 2)
    ]
    assert entries == [(3, 1), (9, 0), (9, 2)]     # 按 key 升序，行序确定


# ---------------------------------------------------------------------------
# N1：补齐标量类型（int8/uint8/int16/uint16/uint32/uint64）
# ---------------------------------------------------------------------------


def _all_scalars_table() -> TableResource:
    from ct.schema.type_expression import SCALAR_TYPE_NAMES

    names = sorted(SCALAR_TYPE_NAMES)
    return TableResource(
        table="Scalars",
        primary="Id",
        fields=[FieldDef(name="Id", type="int32")]
        + [FieldDef(name=f"V{n.upper()}", type=n) for n in names if n != "int32"],
    )


def test_all_scalar_types_round_trip() -> None:
    """12 种标量都能写能读，且**极值**不丢位（含无符号与窄整数的边界）。"""
    from ct.schema.type_expression import SCALAR_TYPE_NAMES

    table = _all_scalars_table()
    row = {"Id": 1}
    expected: dict[str, object] = {}
    extremes = {
        "int8": (-128, 127),
        "uint8": (0, 255),
        "int16": (-32768, 32767),
        "uint16": (0, 65535),
        "int32": (-2147483648, 2147483647),
        "uint32": (0, 4294967295),
        "int64": (-9223372036854775808, 9223372036854775807),
        "uint64": (0, 18446744073709551615),
        "float": (-1.5, 3.25),
        "double": (-2.5, 1e300),
        "bool": (True, True),          # False 是默认值 ⇒ 槽位不写，见下一个测试
        "string": ("", "配置"),
    }
    # 全部用**非默认值**：值 == 默认时 flatbuffers 不写槽位（那条规则单独测）
    for n in sorted(SCALAR_TYPE_NAMES):
        if n == "int32":
            continue
        row[f"V{n.upper()}"] = extremes[n][1]
        expected[f"V{n.upper()}"] = extremes[n][1]
    data = build_canonical_table_bytes([row], table, records={}, enums={})

    import struct as _struct

    def u16(b, o):
        return _struct.unpack_from("<H", b, o)[0]

    def i32(b, o):
        return _struct.unpack_from("<i", b, o)[0]

    root = i32(data, 0)
    vt = root - i32(data, root)
    items_off = u16(data, vt + 4)
    vec = root + items_off + i32(data, root + items_off)
    first = vec + 4
    rowptr = first + i32(data, first)
    rv = rowptr - i32(data, rowptr)
    rv_len = u16(data, rv)

    def field_off(slot):
        return u16(data, rv + slot) if slot < rv_len else 0

    read = {}
    for index, field in enumerate(table.fields):
        slot = 4 + 2 * index
        off = field_off(slot)
        name = field.type_expr.name
        if off == 0:
            read[field.name] = None
            continue
        if name == "string":
            p = rowptr + off + i32(data, rowptr + off)
            read[field.name] = data[p + 4:p + 4 + i32(data, p)].decode()
        elif name == "bool":
            read[field.name] = data[rowptr + off] != 0
        elif name in ("int8",):
            read[field.name] = _struct.unpack_from("<b", data, rowptr + off)[0]
        elif name in ("uint8",):
            read[field.name] = data[rowptr + off]
        elif name == "int16":
            read[field.name] = _struct.unpack_from("<h", data, rowptr + off)[0]
        elif name == "uint16":
            read[field.name] = _struct.unpack_from("<H", data, rowptr + off)[0]
        elif name == "int32":
            read[field.name] = _struct.unpack_from("<i", data, rowptr + off)[0]
        elif name == "uint32":
            read[field.name] = _struct.unpack_from("<I", data, rowptr + off)[0]
        elif name == "int64":
            read[field.name] = _struct.unpack_from("<q", data, rowptr + off)[0]
        elif name == "uint64":
            read[field.name] = _struct.unpack_from("<Q", data, rowptr + off)[0]
        elif name == "float":
            read[field.name] = _struct.unpack_from("<f", data, rowptr + off)[0]
        elif name == "double":
            read[field.name] = _struct.unpack_from("<d", data, rowptr + off)[0]

    for key, want in expected.items():
        got = read[key]
        if isinstance(want, float):
            assert abs(got - want) < 1e-4, f"{key}: got={got} want={want}"
        else:
            assert got == want, f"{key}: got={got} want={want}"


def test_all_scalars_work_in_vectors() -> None:
    from ct.schema.type_expression import SCALAR_TYPE_NAMES

    for name in sorted(SCALAR_TYPE_NAMES):
        if name == "string":
            continue
        table = TableResource(
            table="V",
            primary="Id",
            fields=[
                FieldDef(name="Id", type="int32"),
                FieldDef(name="Xs", type=f"vector<{name}>"),
            ],
        )
        value = [1, 2] if name not in ("bool",) else [True, False]
        data = build_canonical_table_bytes(
            [{"Id": 1, "Xs": value}], table, records={}, enums={}
        )
        assert data, name  # 构建不抛错即可（元素写入走同一张标量表）


def test_new_scalars_generate_fbs_standard_names() -> None:
    from ct.export.canonical_fbs import table_fbs_text

    table = _all_scalars_table()
    text = table_fbs_text(table)
    assert "VINT8: byte;" in text
    assert "VUINT8: ubyte;" in text
    assert "VINT16: short;" in text
    assert "VUINT16: ushort;" in text
    assert "VUINT32: uint;" in text
    assert "VUINT64: ulong;" in text


def test_integer_scalars_allowed_as_primary_key() -> None:
    """主键以前只允许 int32/int64；现在 8 种整数标量都可以。"""
    from ct.schema.type_expression import INTEGER_SCALAR_NAMES

    for name in sorted(INTEGER_SCALAR_NAMES):
        table = TableResource(
            table="K", primary="Id", fields=[FieldDef(name="Id", type=name)]
        )
        assert table.primary == "Id"


def test_scalar_defaults_are_flatbuffers_defaults() -> None:
    """默认值表与「值 == 默认则不写槽位」的规则一致（unsigned/float/bool 各不同）。"""
    from ct.schema.type_expression import SCALAR_DEFAULTS

    assert SCALAR_DEFAULTS["int8"] == 0
    assert SCALAR_DEFAULTS["uint64"] == 0
    assert SCALAR_DEFAULTS["float"] == 0.0
    assert SCALAR_DEFAULTS["bool"] is False
    assert SCALAR_DEFAULTS["string"] == ""


def test_default_scalar_values_omit_their_slot() -> None:
    """值 == flatbuffers 默认值时**不写槽位**（offset 为 0）。

    这条规则是**定宽布局存在的理由**：正因为默认值被省略，同一张表才会出现多种
    vtable、字段偏移才不是表级常量。这里把规则钉住，避免将来改动悄悄破坏它。
    """
    import struct as _struct

    from ct.schema.type_expression import SCALAR_DEFAULTS

    table = _all_scalars_table()
    row = {"Id": 1}
    for n in sorted(SCALAR_DEFAULTS):
        if n != "int32":
            row[f"V{n.upper()}"] = SCALAR_DEFAULTS[n]
    data = build_canonical_table_bytes([row], table, records={}, enums={})

    def u16(b, o):
        return _struct.unpack_from("<H", b, o)[0]

    def i32(b, o):
        return _struct.unpack_from("<i", b, o)[0]

    root = i32(data, 0)
    vt = root - i32(data, root)
    vec = root + u16(data, vt + 4)
    vec += i32(data, vec)
    first = vec + 4
    rowptr = first + i32(data, first)
    rv = rowptr - i32(data, rowptr)
    rv_len = u16(data, rv)

    absent = []
    for index, field in enumerate(table.fields):
        slot = 4 + 2 * index
        off = u16(data, rv + slot) if slot < rv_len else 0
        if field.name == "Id":
            continue          # 主键非默认，当有槽位
        if off == 0:
            absent.append(field.name)
    # 除 string（默认 "" 会被写出，因为 string 是 uoffset）之外，其余默认值都应缺槽位
    assert len(absent) >= 8, f"默认值应缺槽位，实际缺 {absent}"


# ---------------------------------------------------------------------------
# Group 区间哈希：字节级正确性（取代了运行期的两次二分）
# ---------------------------------------------------------------------------


def _indirect(data: bytes, obj: int, slot: int) -> int | None:
    """取 obj 的第 slot 个字段（uoffset）；缺失返回 None。"""
    vt = obj - struct.unpack_from("<i", data, obj)[0]
    vt_len = struct.unpack_from("<H", data, vt)[0]
    if 4 + 2 * slot >= vt_len:
        return None
    off = struct.unpack_from("<H", data, vt + 4 + 2 * slot)[0]
    if off == 0:
        return None
    return obj + off + struct.unpack_from("<I", data, obj + off)[0]


def _i32_vec(data: bytes, vec: int) -> list[int]:
    n = struct.unpack_from("<I", data, vec)[0]
    return list(struct.unpack_from(f"<{n}i", data, vec + 4))


def _group_lookup(data: bytes, value: int) -> list[int]:
    """按运行期（C#/原生）的算法做一次 group 查询，返回行下标列表。

    刻意**不用**任何导出期的 Python 辅助函数 —— 这里验的是「导出器写出的字节，
    用运行期那套规则能查对」。
    """
    root = struct.unpack_from("<i", data, 0)[0]
    pairs_vec = _indirect(data, root, 4)
    hash_vec = _indirect(data, root, 5)
    assert pairs_vec is not None and hash_vec is not None
    pairs = _i32_vec(data, pairs_vec)          # [key, row, key, row, ...]
    slots = _i32_vec(data, hash_vec)           # [start, count, start, count, ...]
    mask = len(slots) // 2 - 1
    b = ((value * 2654435761) & 0xFFFFFFFF) & mask
    while True:
        start, count = slots[b * 2], slots[b * 2 + 1]
        if count == 0:
            return []
        if pairs[start * 2] == value:
            return [pairs[(start + i) * 2 + 1] for i in range(count)]
        b = (b + 1) & mask


def _group_table() -> TableResource:
    from ct.schema.indexes import QueryIndex

    return TableResource(
        table="Item",
        primary="Id",
        fields=[
            FieldDef(name="Id", type="int32"),
            FieldDef(name="Category", type="int32"),
        ],
        indexes=(QueryIndex(kind="group", field="Category"),),
    )


def test_group_hash_locates_every_key_without_binary_search() -> None:
    """空槽用 `count == 0` 表示 ⇒ 每个 key 的区间都能一次探测拿到。

    注意 **key 可以是 0**（区间哈希的"空"由 count 而非 key 表示），
    这正是它比「桶存 key」更稳的地方。
    """
    table = _group_table()
    rows = [
        {"Id": 1, "Category": 7},
        {"Id": 2, "Category": 0},          # key = 0 必须可用
        {"Id": 3, "Category": 7},
        {"Id": 4, "Category": 9},
        {"Id": 5, "Category": 7},
        {"Id": 6, "Category": 0},
    ]
    data = build_canonical_table_bytes(rows, table, records={}, enums={})

    assert _group_lookup(data, 7) == [0, 2, 4]
    assert _group_lookup(data, 0) == [1, 5]
    assert _group_lookup(data, 9) == [3]
    # 不存在的 key ⇒ 空列表（走到 count == 0 的空桶）
    for missing in (1, 8, 12345, -1):
        assert _group_lookup(data, missing) == [], f"key {missing} 应查不到"


def test_group_hash_survives_collisions_and_scale() -> None:
    """撞桶时靠 `pairs[start*2] == value` 确认 —— 换一批 key 密集的数据再验一遍。"""
    table = _group_table()
    # 故意用连续的 key 制造大量相邻桶占用
    rows = [{"Id": i + 1, "Category": i % 17} for i in range(400)]
    data = build_canonical_table_bytes(rows, table, records={}, enums={})
    for key in range(17):
        assert _group_lookup(data, key) == list(range(key, 400, 17))
    assert _group_lookup(data, 17) == []


def test_group_hash_vector_is_a_power_of_two() -> None:
    """运行期靠 `& (slots-1)` 定位 ⇒ 桶数必须是 2 的幂（否则掩码是错的）。"""
    table = _group_table()
    rows = [{"Id": i + 1, "Category": i % 50} for i in range(500)]
    data = build_canonical_table_bytes(rows, table, records={}, enums={})
    root = struct.unpack_from("<i", data, 0)[0]
    slots = _i32_vec(data, _indirect(data, root, 5))
    n = len(slots) // 2
    assert n & (n - 1) == 0, f"桶数 {n} 不是 2 的幂"
    assert n >= 8
