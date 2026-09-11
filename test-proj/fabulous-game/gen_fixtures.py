"""为「部署运行时基准」生成 fixture 与访问器。

与 ct-tool 里既有的 `UniformE2EBench/gen_our_item_bench.py` 的区别（关键）：

| | 既有基准 | 本脚本 |
|---|---|---|
| 运行时 | 基准工程自带的 `WireReader.cs`/`Runtime.cs`（= patch 的参考实现） | **游戏里实际部署的** `Client/Assets/Scripts/Config/Native/{WireReader,ConfigRuntime}.cs` |
| 访问器 | `gen_literal_accessor.emit`（raw 指针读 `*(int*)(P+28)`） | **真实生成器** `render_csharp_accessor(..., uniform_offsets=...)` ⇒ `WireReader.I32At(_row, 28)` / `NStringCache` / `NArray<T>` / `Runtime.Table` |
| 语料 | 同（复用它的 `build()`，同随机种子） | 同 |
| i18n | 无 | **有**：额外产出 `OurItem_i18n` 稀疏表，量新的「按行下标读 i18n」路径 |

所以本基准回答的是：**部署的代码是否真的达到了文档里承诺的数字**，
而不是「参考实现能达到多少」。

两张表、两个 bundle、两个访问器类：

| 表名 | 布局 | 用途 |
|---|---|---|
| `OurItem` | **定宽**（字面量偏移）= 部署形态 | 绝对性能 + i18n 路径 + 向量/字符串 |
| `OurItemOT` | 常规（偏移表） | 定宽 A/B 的对照；**不带 i18n 委托**，把「定宽」与「i18n 委托」两个变量分开 |

> 为什么对照表要去掉 i18n：生成器的类名由**表名**派生，两张表必须不同名才能共存；
> 而 i18n 委托会让 `Name` 走 `{Table}_i18n`，把「定宽」的差异和「i18n」的差异混在一起。
> A/B 场景只用 `Id/Price/Rarity/ItemTypeId/DropRange`，两张表在这些字段上完全同构。

用法：
  CT_TOOL=/path/to/ct-tool python3 gen_fixtures.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent          # ct-tool/test-proj/fabulous-game
CT = HERE.parents[1]                            # ct-tool 仓库根

sys.path.insert(0, str(CT / "ct" / "src"))
sys.path.insert(0, str(CT / "test-proj" / "RefConfigBench"))
sys.path.insert(0, str(CT / "test-proj" / "UniformE2EBench"))

# 复用既有的语料定义（同随机种子），保证与历史测量可比
from gen_our_item_bench import build  # noqa: E402

from ct.export.canonical_accessor import (  # noqa: E402
    generate_csharp_accessor,
    render_csharp_accessor,
)
from ct.export.canonical_accessor_model import build_accessor_model  # noqa: E402
from ct.export.canonical_binary import (  # noqa: E402
    build_canonical_bundle,
    build_canonical_table_bytes,
    probe_row_layout,
)
from ct.schema.resources import FieldDef, TableResource  # noqa: E402

# ---- 输出目标（**显式传入**：tool 产出 → 工程消费，方向单向）----
# 指向 fabulous-game 的 Docs/TODO/scripts/deployed-perf-bench/
OUT = Path(os.environ.get("GAME_BENCH_DIR", "")).expanduser()
if not OUT.is_dir():
    raise SystemExit(
        "请指定输出目录：GAME_BENCH_DIR=<fabulous-game>/Docs/TODO/scripts/deployed-perf-bench "
        f"（当前 {OUT or '未设置'}）")
FIX = OUT / "fixtures"


def rename(table: TableResource, name: str, drop_i18n: bool) -> TableResource:
    """换表名（顺带可选去掉 i18n 标记）—— 生成器类名由表名派生，两张变体必须不同名。"""
    return TableResource(
        table=name,
        primary=table.primary,
        fields=[
            FieldDef(
                name=f.name,
                type=f.type_expr,
                i18n=False if drop_i18n else f.i18n,
                comment=f.comment,
                ref=f.ref,
                server_only=f.server_only,
            )
            for f in table.fields
        ],
    )


def i18n_table_of(table: TableResource) -> TableResource:
    """稀疏 i18n 表：主键 + i18n 字段（与导出器 `_i18n_table` 同构）。"""
    i18n_fields = [f for f in table.fields if f.i18n and not f.server_only]
    primary = next(f for f in table.fields if f.name == table.primary)
    return TableResource(
        table=f"{table.table}_i18n", primary=table.primary, fields=[primary, *i18n_fields]
    )


def main() -> None:
    FIX.mkdir(parents=True, exist_ok=True)
    base, records, enums, rows = build()

    deployed = base                                     # 表名 OurItem，带 i18n
    ot = rename(base, "OurItemOT", drop_i18n=True)       # 对照：不带 i18n

    dep_normal = build_canonical_table_bytes(rows, deployed, records=records, enums=enums)
    dep_uniform = build_canonical_table_bytes(
        rows, deployed, records=records, enums=enums, uniform=True
    )
    ot_normal = build_canonical_table_bytes(rows, ot, records=records, enums=enums)

    # i18n 稀疏表：行序与主表 1:1（导出器保证）；值故意与主表不同，顺手可验正确性
    i18n_rows = [
        {deployed.primary: r[deployed.primary], "Name": "EN" + r["Name"][:6]} for r in rows
    ]
    itable = i18n_table_of(deployed)
    i18n_uniform = build_canonical_table_bytes(
        i18n_rows, itable, records=records, enums=enums, uniform=True
    )

    (FIX / "OurItem.bundle.bin").write_bytes(build_canonical_bundle({deployed.table: dep_uniform}))
    (FIX / "OurItemOT.bundle.bin").write_bytes(build_canonical_bundle({ot.table: ot_normal}))
    (FIX / "OurItem_i18n.bundle.bin").write_bytes(
        build_canonical_bundle({itable.table: i18n_uniform})
    )

    dep_layout = probe_row_layout(deployed, records=records, enums=enums)
    i18n_layout = probe_row_layout(itable, records=records, enums=enums)

    # 部署形态：定宽 + 字面量偏移（与 E3 落地的生成物同构）。
    # ⚠️ 稀疏 i18n 表**不再**单独产出访问器：读路径已内联进主访问器
    #    （`i18n_uniform_offsets` 就是**它自己的**那份表级偏移）。
    (OUT / "OurItemDeployed.g.cs").write_text(
        generate_csharp_accessor(
            build_accessor_model(
                deployed,
                (),
                records=records,
                uniform_offsets=dep_layout,
                i18n_table=itable.table,
                i18n_uniform_offsets=i18n_layout,
            )
        ),
        encoding="utf-8",
    )
    # 对照：常规布局（偏移表）
    (OUT / "OurItemOTAccessor.g.cs").write_text(
        render_csharp_accessor(ot, (), records), encoding="utf-8"
    )

    print(f"OurItem（定宽/部署）: {len(rows)} 行 / {len(deployed.fields)} 字段")
    print(f"  常规 {len(dep_normal):,} B   定宽 {len(dep_uniform):,} B   "
          f"膨胀 {len(dep_uniform)/len(dep_normal):.3f}x")
    print(f"  slot→offset: {dep_layout}")
    print(f"OurItemOT（常规/对照）: {len(ot_normal):,} B")
    print(f"OurItem_i18n: {len(i18n_rows)} 行（1:1）  {len(i18n_uniform):,} B")
    print(f"  slot→offset: {i18n_layout}")


if __name__ == "__main__":
    main()
