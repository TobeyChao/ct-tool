"""生成与 参考实现 同规模的 ct bundle，用于加载耗时对标。

对标基准（实测 参考实现 原生 TableInit）：
  Main.bytes 68.4 MB + 9 个语言包 ~85 MB，2012 张表 / 691,518 行 → 216 ms

本脚本按 参考实现 的行形态（大量 int32 槽 + 少量短串）合成 ~2000 张表 / ~69 万行，
使字节量级与行数都可直接对比。

用法：
  cd ct && .venv\\Scripts\\python test-proj\\RefConfigBench\\gen_scale_corpus.py
"""
from __future__ import annotations

import json
import os
import random
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
FIX = os.path.join(HERE, "fixtures")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "ct", "src"))

from ct.export.canonical_binary import build_canonical_bundle, build_canonical_table_bytes  # noqa: E402
from ct.schema.resources import FieldDef, TableResource  # noqa: E402
from ct.schema.type_expression import ScalarType, VectorType  # noqa: E402

TABLES = 2000
AVG_ROWS = 346          # 2000 x 346 ≈ 692,000 行
INT_FIELDS = 20
CJK = "翻牌次数周年庆奖券印花解码弹时装面饰背饰球员立绘印城飞将保罗乔治专属"

rng = random.Random(777)


def make_table(index: int) -> TableResource:
    fields = [FieldDef(name="Id", type=ScalarType(name="int32"))]
    fields.append(FieldDef(name="Name", type=ScalarType(name="string")))
    for k in range(INT_FIELDS):
        fields.append(FieldDef(name=f"V{k:02d}", type=ScalarType(name="int32")))
    fields.append(FieldDef(name="Tags", type=VectorType(element=ScalarType(name="int32"))))
    return TableResource(table=f"Scale{index:04d}", primary="Id", fields=fields)


def main() -> None:
    os.makedirs(FIX, exist_ok=True)
    parts: dict[str, bytes] = {}
    total_rows = 0
    t0 = time.time()

    for i in range(TABLES):
        table = make_table(i)
        n = max(1, int(rng.gauss(AVG_ROWS, AVG_ROWS * 0.4)))
        base = 100_000_000 + i * 1_000_000
        rows = []
        for r in range(n):
            row = {
                "Id": base + r * 3,
                "Name": "".join(rng.choice(CJK) for _ in range(8)),
                "Tags": [rng.randint(0, 1000) for _ in range(4)],
            }
            for k in range(INT_FIELDS):
                row[f"V{k:02d}"] = rng.randint(0, 100000)
            rows.append(row)
        parts[table.table] = build_canonical_table_bytes(rows, table, records={}, enums={})
        total_rows += n
        if (i + 1) % 250 == 0:
            print(f"  ... {i + 1}/{TABLES} tables, {total_rows:,} rows, "
                  f"{sum(len(v) for v in parts.values()):,} bytes, {time.time() - t0:.0f}s", flush=True)

    bundle = build_canonical_bundle(parts)
    out = os.path.join(FIX, "scale_corpus.bundle.bin")
    with open(out, "wb") as fh:
        fh.write(bundle)

    # 拆出单表也能直接跑（便于按表加载对比）
    meta = {"tables": len(parts), "rows": total_rows, "bytes": len(bundle)}
    with open(os.path.join(FIX, "scale_meta.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=1)

    print(f"DONE tables={len(parts)} rows={total_rows:,} bytes={len(bundle):,} "
          f"({len(bundle) / 1048576:.1f} MB) in {time.time() - t0:.0f}s")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
