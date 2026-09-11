"""生成 ct 侧基准表（.bin + 生成器产出的 .g.cs），形状对齐 参考实现 的真实表。

对照关系：
  ItemBench (6685 行)  <->  参考实现 `Item`   (6685 行, 36 字段, 3 个 i18n 串, 1 个 vector<string>)
  ArrayBench (6048 行) <->  参考实现 `Skill`  (6048 行, 10 个 Array<int>)

用真实生成器 `ct.export.canonical_accessor.render_csharp_accessor` 产出 accessor，
保证被基准的读取代码与线上生成物同构。

用法：
  cd ct && .venv\\Scripts\\python test-proj\\RefConfigBench\\gen_ct_bench_tables.py
"""
from __future__ import annotations

import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
FIX = os.path.join(HERE, "fixtures")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "ct", "src"))

from ct.export.canonical_accessor import render_csharp_accessor  # noqa: E402
from ct.export.canonical_binary import (  # noqa: E402
    build_canonical_bundle,
    build_canonical_table_bytes,
)
from ct.schema.resources import (  # noqa: E402
    EnumResource,
    FieldDef,
    RecordResource,
    TableResource,
)
from ct.schema.type_expression import NamedType, ScalarType, VectorType  # noqa: E402

ITEM_ROWS = 6685
ARRAY_ROWS = 6048

# CJK 池：与 参考实现 真实配置串同为 3 字节/字符的 UTF-8
CJK = "翻牌次数周年庆奖券印花解码弹时装面饰背饰球员立绘印城飞将保罗乔治专属墨镜瞅你咋地碰杠胡了印花工坊活动抽奖获得通过点券购买所需参加"

rng = random.Random(20240517)


def cjk(n: int) -> str:
    return "".join(rng.choice(CJK) for _ in range(n))


def int32(name: str) -> FieldDef:
    return FieldDef(name=name, type=ScalarType(name="int32"))


def build_item_bench() -> tuple[TableResource, dict[str, RecordResource], dict[str, EnumResource], list[dict]]:
    drop = RecordResource(
        name="DropRange",
        fields=[int32("Min"), int32("Max")],
    )
    table = TableResource(
        table="ItemBench",
        primary="Id",
        fields=[
            int32("Id"),
            FieldDef(name="DesignName", type=ScalarType(name="string"), i18n=True),
            int32("Type"),
            int32("Quality"),
            int32("IconRes"),
            int32("PileCount"),
            int32("SellPrice"),
            FieldDef(name="PriceChecker", type=ScalarType(name="float")),
            int32("IsPut"),
            FieldDef(name="Hidden", type=ScalarType(name="bool")),
            FieldDef(name="Description", type=ScalarType(name="string")),
            FieldDef(name="BpDescription", type=ScalarType(name="string")),
            FieldDef(name="StringParams", type=VectorType(element=ScalarType(name="string"))),
            FieldDef(name="Tags", type=VectorType(element=ScalarType(name="int32"))),
            FieldDef(name="Drop", type=NamedType(resource_id="DropRange", expected_kind="record")),
        ],
    )

    rows = []
    # id 稀疏递增（对齐 参考实现 Item 的 700150001 / 700020140 风格：乱序源数据 + 升序索引）
    ids = sorted(700000000 + i * 7 + (i % 13) * 11 for i in range(ITEM_ROWS))
    for i, rid in enumerate(ids):
        rows.append(
            {
                "Id": rid,
                "DesignName": cjk(rng.randint(4, 22)),
                "Type": rng.randint(0, 120),
                "Quality": rng.randint(0, 5),
                "IconRes": 200000000 + rng.randint(0, 2_000_000),
                "PileCount": rng.choice([1, 1, 10, 100, 999]),
                "SellPrice": rng.choice([-1, 0, 100, 500, 2000]),
                "PriceChecker": float(rng.randint(1, 3000)),
                "IsPut": 1600000 + i * 20,
                "Hidden": (i % 7) == 0,
                "Description": cjk(rng.randint(8, 40)),
                "BpDescription": cjk(rng.randint(0, 22)),
                "StringParams": [cjk(rng.randint(2, 12)) for _ in range(rng.randint(0, 3))],
                "Tags": [rng.randint(0, 1000) for _ in range(rng.randint(1, 5))],
                "Drop": {"Min": rng.randint(0, 50), "Max": rng.randint(50, 200)},
            }
        )
    return table, {"DropRange": drop}, {}, rows


def build_array_bench() -> tuple[TableResource, dict[str, RecordResource], dict[str, EnumResource], list[dict]]:
    table = TableResource(
        table="ArrayBench",
        primary="Id",
        fields=[
            int32("Id"),
            int32("Type"),
            int32("Group"),
            FieldDef(name="Areas", type=VectorType(element=ScalarType(name="int32"))),
            FieldDef(name="TargetAreas", type=VectorType(element=ScalarType(name="int32"))),
            FieldDef(name="PopAreas", type=VectorType(element=ScalarType(name="int32"))),
            FieldDef(name="Forbidden", type=VectorType(element=ScalarType(name="int32"))),
            FieldDef(name="Connections", type=VectorType(element=ScalarType(name="int32"))),
        ],
    )
    rows = []
    for i in range(ARRAY_ROWS):
        rows.append(
            {
                "Id": 300000000 + i * 3 + (i % 7),
                "Type": rng.randint(0, 200),
                "Group": rng.randint(0, 40),
                # 长度分布对齐 参考实现 Skill.areas（实测平均 1.2 个元素），
                # 否则向量场景会变成 12 元素 vs 1.2 元素的不公平比较
                "Areas": [rng.randint(0, 5000) for _ in range(rng.choices([1, 2, 3], weights=[80, 15, 5])[0])],
                "TargetAreas": [rng.randint(0, 5000) for _ in range(6)],
                "PopAreas": [rng.randint(0, 5000) for _ in range(4)],
                "Forbidden": [rng.randint(0, 5000) for _ in range(3)],
                "Connections": [rng.randint(0, 5000) for _ in range(5)],
            }
        )
    return table, {}, {}, rows


def main() -> None:
    os.makedirs(FIX, exist_ok=True)
    meta: dict[str, object] = {}
    bundle_parts: dict[str, bytes] = {}

    for name, builder in (("ItemBench", build_item_bench), ("ArrayBench", build_array_bench)):
        table, records, enums, rows = builder()
        data = build_canonical_table_bytes(rows, table, records=records, enums=enums)
        bin_path = os.path.join(FIX, f"{name}.bin")
        with open(bin_path, "wb") as fh:
            fh.write(data)

        cs = render_csharp_accessor(table, (), records)
        with open(os.path.join(HERE, f"{name}Accessor.g.cs"), "w", encoding="utf-8") as fh:
            fh.write(cs)

        bundle_parts[name] = data
        meta[name] = {
            "rows": len(rows),
            "bytes": len(data),
            "ids": [int(r[table.primary]) for r in rows],
            "primary": table.primary,
            "fields": [f.name for f in table.fields],
        }
        print(f"{name}: rows={len(rows)} bin={len(data):,} bytes  cs={len(cs):,} chars")

    # 组合 bundle（用于 LoadBundle 计时）。
    # 注意：必须复用上面已经写盘的那份 bytes —— 早期版本在这里重新调了一次 builder，
    # 而模块级 rng 是共享推进的，导致「单表 .bin」与「bundle 内的同名表」数据不同，
    # 使「视图 vs 单表」一致性校验误报。
    bundle = build_canonical_bundle(bundle_parts)
    with open(os.path.join(FIX, "bench_bundle.bin"), "wb") as fh:
        fh.write(bundle)
    meta["bundle_bytes"] = len(bundle)
    print(f"bench_bundle.bin: {len(bundle):,} bytes")

    with open(os.path.join(FIX, "bench_meta.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=1)
    print(f"wrote {FIX}\\bench_meta.json")


if __name__ == "__main__":
    main()
