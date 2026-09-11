"""为「参考实现 对标」生成 ItemBench / ArrayBench 的**部署形态**访问器与定宽 bundle。

为什么需要：那次 参考实现 A/B 的 ct 侧编的是 `ConfigAccessorBench/{WireReader,Runtime}.cs`
（patch 的参考实现），访问器也是基准自己的 `emit`（裸指针）。本脚本用**当前真实生成器**
+ **定宽参数**重生成同一形状（同 `gen_ct_bench_tables.py` 的 builder、同随机种子），
这样就能在同一台机器、同一形状上量出「部署 vs 参考实现」的逐项比值。

自检：非定宽产物应与既有 `fixtures/{ItemBench,ArrayBench}.bin` **逐字节一致**
（证明语料与那次 A/B 完全相同）。

用法： CT_TOOL=/path/to/ct-tool python3 gen_bench_fixtures.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent          # ct-tool/test-proj/fabulous-game
CT = HERE.parents[1]                            # ct-tool 仓库根
BENCH = CT / "test-proj" / "RefConfigBench"

sys.path.insert(0, str(CT / "ct" / "src"))
sys.path.insert(0, str(BENCH))

from gen_ct_bench_tables import build_array_bench, build_item_bench  # noqa: E402

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
from ct.schema.resources import TableResource  # noqa: E402

# ---- 输出目标（**显式传入**：tool 产出 → 工程消费，方向单向）----
# 指向 fabulous-game 的 Docs/TODO/scripts/deployed-perf-bench/
OUT = Path(os.environ.get("GAME_BENCH_DIR", "")).expanduser()
if not OUT.is_dir():
    raise SystemExit(
        "请指定输出目录：GAME_BENCH_DIR=<fabulous-game>/Docs/TODO/scripts/deployed-perf-bench "
        f"（当前 {OUT or '未设置'}）")
FIX = OUT / "fixtures"


def i18n_table_of(table: TableResource) -> TableResource:
    i18n_fields = [f for f in table.fields if f.i18n and not f.server_only]
    primary = next(f for f in table.fields if f.name == table.primary)
    return TableResource(
        table=f"{table.table}_i18n", primary=table.primary, fields=[primary, *i18n_fields]
    )


def main() -> None:
    FIX.mkdir(parents=True, exist_ok=True)
    # 与 gen_ct_bench_tables.py 同样的调用顺序 ⇒ 同样的 rng 推进 ⇒ 同样的语料
    item = build_item_bench()
    array = build_array_bench()

    for (table, records, enums, rows) in (item, array):
        name = table.table
        normal = build_canonical_table_bytes(rows, table, records=records, enums=enums)

        # 自检：与那次 A/B 用的 fixture 必须逐字节一致
        ref = BENCH / "fixtures" / f"{name}.bin"
        if ref.exists():
            same = ref.read_bytes() == normal
            print(f"  {name}: 语料自检 vs 既有 fixture = {'一致 ✅' if same else '**不一致** ❌'}")
            assert same, "语料与那次 A/B 不同，比值不可比"

        uniform = build_canonical_table_bytes(
            rows, table, records=records, enums=enums, uniform=True
        )
        (FIX / f"{name}.uniform.bundle.bin").write_bytes(
            build_canonical_bundle({name: uniform})
        )

        layout = probe_row_layout(table, records=records, enums=enums)
        # 有 i18n 字段的表：i18n 表**自己的**定宽偏移也要交给生成器（它内联在主访问器里）
        it = i18n_table_of(table) if any(f.i18n for f in table.fields) else None
        il = probe_row_layout(it, records=records, enums=enums) if it is not None else None
        (OUT / f"{name}Deployed.g.cs").write_text(
            generate_csharp_accessor(
                build_accessor_model(
                    table,
                    (),
                    records=records,
                    uniform_offsets=layout,
                    i18n_table=it.table if it is not None else None,
                    i18n_uniform_offsets=il,
                )
            ),
            encoding="utf-8",
        )

        # 同一形状的**偏移表**变体（换个表名，类名才不撞）。
        # 文档里 float/bool/字符串热读 那几个数字是偏移表口径，要同口径才能算比值。
        from ct.schema.resources import FieldDef as _FD
        ot_table = TableResource(
            table=f"{name}OT", primary=table.primary,
            fields=[_FD(name=f.name, type=f.type_expr, i18n=False, comment=f.comment,
                        ref=f.ref, server_only=f.server_only) for f in table.fields],
        )
        ot_normal = build_canonical_table_bytes(rows, ot_table, records=records, enums=enums)
        (FIX / f"{name}OT.bundle.bin").write_bytes(build_canonical_bundle({ot_table.table: ot_normal}))
        (OUT / f"{name}OT.g.cs").write_text(
            render_csharp_accessor(ot_table, (), records), encoding="utf-8"
        )

        # 稀疏 i18n 表**不再**单独产出访问器：读路径内联在主访问器里（见上）
        if it is not None:
            print(f"  {name}: 定宽 {len(uniform):,} B（常规 {len(normal):,} B，"
                  f"膨胀 {len(uniform)/len(normal):.3f}x）+ 内联 i18n（{it.table}）")
        else:
            print(f"  {name}: 定宽 {len(uniform):,} B（常规 {len(normal):,} B，"
                  f"膨胀 {len(uniform)/len(normal):.3f}x）")


if __name__ == "__main__":
    main()
