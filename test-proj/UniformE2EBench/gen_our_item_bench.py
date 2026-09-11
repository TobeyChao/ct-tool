"""生成「本项目真实表形状」的基准：OurItem（7 字段，含枚举），6685 行。

为什么要单独造：patch 的 ItemBench 是 15 字段、**16 种 vtable**，
而本项目真实表只有 7 字段、**2–3 种 vtable** ——
`OffsetsFor` 的线性扫描长度不同，用 ItemBench 会**高估**定宽布局的收益。

形状严格对齐本项目 `Config/gd` 的 Item 表（迁移后方言）：
  Id:int32 / Name:string(i18n) / Price:float / Rarity:ItemRarity(enum) /
  ItemTypeId:int32 / DropRange:ItemDropRange(record{Min,Max}) / Tags:vector<int32>

产出：
  fixtures/OurItem.bundle.bin / OurItemUniform.bundle.bin
  OurItemAccessor.g.cs / OurItemLiteral.g.cs

用法：
  CT_TOOL=/path/to/ct-tool  ct/.venv/bin/python gen_our_item_bench.py
"""
from __future__ import annotations

import os
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CT = Path(os.environ.get("CT_TOOL", "/Users/tobeychao/Documents/Projects/ct-tool"))
sys.path.insert(0, str(CT / "ct" / "src"))
sys.path.insert(0, str(CT / "test-proj" / "RefConfigBench"))

from ct.export.canonical_accessor import render_csharp_accessor  # noqa: E402
from ct.export.canonical_binary import (  # noqa: E402
    build_canonical_bundle,
    build_canonical_table_bytes,
    probe_row_layout,
)
from ct.schema.resources import (  # noqa: E402
    EnumResource,
    FieldDef,
    RecordResource,
    TableResource,
)
from ct.schema.type_expression import NamedType, ScalarType, VectorType  # noqa: E402
from gen_literal_accessor import emit  # noqa: E402

ROWS = 6685
FIX = HERE / "fixtures"
CJK = "翻牌次数周年庆奖券印花解码弹时装面饰背饰球员立绘印城飞将保罗乔治专属墨镜瞅你咋地碰杠胡了印花工坊活动抽奖获得通过点券购买所需参加"

rng = random.Random(20260911)


def cjk(n: int) -> str:
    return "".join(rng.choice(CJK) for _ in range(n))


def build() -> tuple[TableResource, dict[str, RecordResource], dict[str, EnumResource], list[dict]]:
    records = {
        "ItemDropRange": RecordResource(
            name="ItemDropRange",
            fields=[
                FieldDef(name="Min", type=ScalarType(name="int32")),
                FieldDef(name="Max", type=ScalarType(name="int32")),
            ],
        )
    }
    enums = {"ItemRarity": EnumResource(name="ItemRarity", values=["common", "rare", "epic"])}
    table = TableResource(
        table="OurItem",
        primary="Id",
        fields=[
            FieldDef(name="Id", type=ScalarType(name="int32")),
            FieldDef(name="Name", type=ScalarType(name="string"), i18n=True),
            FieldDef(name="Price", type=ScalarType(name="float")),
            FieldDef(name="Rarity", type=NamedType(resource_id="ItemRarity", expected_kind="enum")),
            FieldDef(name="ItemTypeId", type=ScalarType(name="int32")),
            FieldDef(
                name="DropRange", type=NamedType(resource_id="ItemDropRange", expected_kind="record")
            ),
            FieldDef(name="Tags", type=VectorType(element=ScalarType(name="int32"))),
        ],
    )
    rows = []
    for i in range(ROWS):
        # 本项目 Item 的真实填充特征：Rarity 只有 50%（common 是第 0 项 ⇒ 省略槽位）
        rarity = "common" if i % 2 == 0 else rng.choice(["rare", "epic"])
        rows.append(
            {
                "Id": 1000 + i,
                "Name": cjk(rng.randint(2, 8)),
                "Price": float(rng.randint(1, 500)),
                "Rarity": rarity,
                "ItemTypeId": rng.randint(1, 5),
                "DropRange": {"Min": rng.randint(0, 3), "Max": rng.randint(3, 20)},
                "Tags": [rng.randint(100, 999) for _ in range(rng.randint(0, 3))],
            }
        )
    return table, records, enums, rows


def fill_rate(table, rows, enums) -> float:
    """按导出器「写不写槽位」的规则算填充率。"""
    total = written = 0
    for row in rows:
        for f in table.fields:
            t = f.type_expr
            v = row.get(f.name)
            total += 1
            if isinstance(t, ScalarType):
                if t.name == "string":
                    written += 1 if v is not None else 0
                elif t.name in ("int32", "int64"):
                    written += 1 if int(v or 0) != 0 else 0
                elif t.name in ("float", "double"):
                    written += 1 if float(v or 0.0) != 0.0 else 0
                elif t.name == "bool":
                    written += 1 if bool(v) else 0
            elif isinstance(t, VectorType):
                written += 1                     # 永远写
            elif isinstance(t, NamedType) and t.expected_kind == "enum":
                names = [x.name for x in enums[t.name].values]
                written += 1 if (names.index(v) if v in names else 0) != 0 else 0
            elif isinstance(t, NamedType) and t.expected_kind == "record":
                written += 1 if v is not None else 0
    return written / total


def vtable_count(data: bytes) -> int:
    import struct

    def u16(d, o):
        return struct.unpack_from("<H", d, o)[0]

    def i32(d, o):
        return struct.unpack_from("<i", d, o)[0]

    root = i32(data, 0)
    vt = root - i32(data, root)
    io = u16(data, vt + 4)
    vec = root + io + i32(data, root + io)
    base, n = vec + 4, i32(data, vec)
    seen = set()
    for i in range(n):
        e = base + i * 4
        row = e + i32(data, e)
        v = row - i32(data, row)
        seen.add(data[v:v + u16(data, v)])
    return len(seen)


def main() -> None:
    FIX.mkdir(parents=True, exist_ok=True)
    table, records, enums, rows = build()
    rate = fill_rate(table, rows, enums)
    print(f"OurItem: {len(rows)} 行 / {len(table.fields)} 字段   填充率 = {rate:.1%}")

    normal = build_canonical_table_bytes(rows, table, records=records, enums=enums)
    uniform = build_canonical_table_bytes(rows, table, records=records, enums=enums, uniform=True)
    print(f"  常规 {len(normal):,} B（vtable={vtable_count(normal)}）  "
          f"定宽 {len(uniform):,} B（vtable={vtable_count(uniform)}）  膨胀 {len(uniform)/len(normal):.3f}x")

    (FIX / "OurItem.bundle.bin").write_bytes(build_canonical_bundle({table.table: normal}))
    (FIX / "OurItemUniform.bundle.bin").write_bytes(build_canonical_bundle({table.table: uniform}))

    (HERE / "OurItemAccessor.g.cs").write_text(
        render_csharp_accessor(table, (), records), encoding="utf-8"
    )
    layout = probe_row_layout(table, records=records, enums=enums)
    (HERE / "OurItemLiteral.g.cs").write_text(
        emit(table, layout, "OurItemLiteralAccessor"), encoding="utf-8"
    )
    print("  layout:", {f.name: layout[4 + 2 * i] for i, f in enumerate(table.fields)})


if __name__ == "__main__":
    main()
