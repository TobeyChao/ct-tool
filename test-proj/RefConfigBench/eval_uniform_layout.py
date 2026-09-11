"""评估「定宽布局」：代价（字节数）与收益（偏移成为表级常量）。

uniform=True 时每个槽位无条件写出 → 同表所有行共享同一 vtable
→ 字段行内偏移成为表级常量 → 生成器可发射字面量，彻底去掉偏移表间接层。

用法：
  cd ct && .venv\\Scripts\\python test-proj\\RefConfigBench\\eval_uniform_layout.py
"""
from __future__ import annotations

import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "ct", "src"))
sys.path.insert(0, HERE)

from ct.export.canonical_binary import build_canonical_table_bytes, probe_row_layout  # noqa: E402
from gen_ct_bench_tables import build_array_bench, build_item_bench  # noqa: E402


def u16(b, o):
    return struct.unpack_from("<H", b, o)[0]


def i32(b, o):
    return struct.unpack_from("<i", b, o)[0]


def vtable_stats(data: bytes) -> tuple[int, int]:
    root = i32(data, 0)
    p = root + struct.unpack_from("<i", data, root)[0]  # 占位，下面重算
    vt = root - i32(data, root)
    off = u16(data, vt + 4)
    vec = root + off + i32(data, root + off)
    base, count = vec + 4, i32(data, vec)
    addrs, contents = set(), set()
    for i in range(count):
        e = base + i * 4
        row = e + i32(data, e)
        v = row - i32(data, row)
        addrs.add(v)
        contents.add(data[v:v + u16(data, v)])
    return count, len(contents)


def main() -> None:
    for name, builder in (("ItemBench", build_item_bench), ("ArrayBench", build_array_bench)):
        table, records, enums, rows = builder()
        normal = build_canonical_table_bytes(rows, table, records=records, enums=enums)
        uniform = build_canonical_table_bytes(rows, table, records=records, enums=enums, uniform=True)
        n_count, n_vt = vtable_stats(normal)
        u_count, u_vt = vtable_stats(uniform)
        layout = probe_row_layout(table, records=records, enums=enums)

        print(f"\n=== {name}（{len(rows)} 行，{len(table.fields)} 字段）===")
        print(f"  常规布局: {len(normal):>10,} 字节，不同 vtable = {n_vt}")
        print(f"  定宽布局: {len(uniform):>10,} 字节，不同 vtable = {u_vt}   "
              f"膨胀 {len(uniform) / len(normal):.3f}x  (+{len(uniform) - len(normal):,} 字节)")
        print(f"  字节/行: {len(normal) / len(rows):.1f} → {len(uniform) / len(rows):.1f}")
        print("  slot → 行内偏移（定宽布局，表级常量）:")
        items = []
        for field in table.fields:
            slot = 4 + 2 * table.fields.index(field)
            items.append(f"{field.name}={layout.get(slot, 0)}")
        print("    " + ", ".join(items))


if __name__ == "__main__":
    main()
