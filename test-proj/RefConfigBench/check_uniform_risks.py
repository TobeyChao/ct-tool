"""定宽布局的风险核查。

用户提出的担心：定宽会不会和 flatbuffers 规则相撞（例如必须用 array 而不是 vector）？

本脚本核查三件事：
  R1  行内布局是否与「单行探针」一致 —— probe_row_layout 用一个 1 行的空白表推导偏移，
      但真实产物是同一个 builder 里写 6685 行 + index 向量。flatbuffers 的对齐 padding
      取决于绝对缓冲位置，所以「探针布局 == 真实布局」不是自明的，必须实测。
  R2  稀疏数据下的体积代价 —— ItemBench 是稠密数据（默认值少），膨胀只有 1.6%。
      全是 0/空值的表才是最坏情况。
  R3  真实 gd 表的膨胀 —— 用 ct 自己的 5 张表量一遍。

用法：
  cd ct && .venv\\Scripts\\python test-proj\\RefConfigBench\\check_uniform_risks.py
"""
from __future__ import annotations

import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "ct", "src"))
sys.path.insert(0, HERE)

from ct.app.canonical_workspace import CanonicalWorkspace  # noqa: E402
from ct.export.canonical_binary import (  # noqa: E402
    build_canonical_table_bytes,
    probe_row_layout,
)
from gen_ct_bench_tables import build_array_bench, build_item_bench  # noqa: E402


def u16(b, o):
    return struct.unpack_from("<H", b, o)[0]


def i32(b, o):
    return struct.unpack_from("<i", b, o)[0]


def real_layout(data: bytes) -> dict[int, int]:
    """从真实产物里读第 0 行的 slot→offset，并报告全表 vtable 数。"""
    container = i32(data, 0)
    cvt = container - i32(data, container)
    cvt_len = u16(data, cvt)
    items_off = u16(data, cvt + 4) if 4 < cvt_len else 0
    items = container + items_off + i32(data, container + items_off)
    count = i32(data, items)
    vt_len = u16(data, container - i32(data, container))
    del vt_len
    out = {}
    vts = set()
    first_slots = None
    for i in range(count):
        e = items + 4 + i * 4
        row = e + i32(data, e)
        vt = row - i32(data, row)
        n = u16(data, vt)
        vts.add(data[vt:vt + n])
        slots = tuple(u16(data, vt + s) for s in range(4, n, 2))
        if first_slots is None:
            first_slots = slots
        elif slots != first_slots:
            raise AssertionError("行布局不一致！")
    out["__n_rows"] = count
    out["__n_vtables"] = len(vts)
    for j, v in enumerate(first_slots or ()):
        out[4 + 2 * j] = v
    del out["__n_rows"], out["__n_vtables"]
    return out


def probe(data: bytes) -> dict[int, int]:
    container = i32(data, 0)
    cvt = container - i32(data, container)
    n = u16(data, cvt)
    out = {}
    for j, s in enumerate(range(4, n, 2)):
        out[s] = u16(data, cvt + s)
    return out


def check_r1() -> None:
    print("=== R1  探针布局 vs 真实产物布局 ===")
    for name, builder in (("ItemBench", build_item_bench), ("ArrayBench", build_array_bench)):
        table, records, enums, rows = builder()
        data = build_canonical_table_bytes(rows, table, records=records, enums=enums, uniform=True)
        p = probe_row_layout(table, records=records, enums=enums)
        # 真实布局从产物里取（容器 → items → 第 0 行）
        container = i32(data, 0)
        cvt = container - i32(data, container)
        cvt_len = u16(data, cvt)
        items_off = u16(data, cvt + 4)
        items = container + items_off + i32(data, container + items_off)
        e = items + 4
        row = e + i32(data, e)
        vt = row - i32(data, row)
        n = u16(data, vt)
        real = {s: u16(data, vt + s) for s in range(4, n, 2)}

        same = real == p
        print(f"  {name}: 探针 == 真实 ? {'一致' if same else '不一致 <<<'}")
        if not same:
            for s in sorted(set(real) | set(p)):
                if real.get(s) != p.get(s):
                    print(f"    slot {s:3d}: 探针={p.get(s)}  真实={real.get(s)}")


def check_r2() -> None:
    print("\n=== R2  体积代价 vs 字段填充率（决定性的那张表）===")
    from ct.schema.resources import FieldDef, TableResource
    from ct.schema.type_expression import ScalarType, VectorType

    NF = 22
    table = TableResource(
        table="FillBench",
        primary="Id",
        fields=[FieldDef(name="Id", type=ScalarType(name="int32"))]
        + [FieldDef(name=f"V{i:02d}", type=ScalarType(name="int32")) for i in range(NF - 3)]
        + [FieldDef(name="VName", type=ScalarType(name="string"))]
        + [FieldDef(name="Tags", type=VectorType(element=ScalarType(name="int32")))],
    )
    rows_n = 5000
    print(f"  {NF} 字段 / {rows_n} 行；定宽把「缺省=不占字节」变成「每字段恒占 4 字节」")
    print(f"  {'填充率':>8} {'常规 B/行':>10} {'定宽 B/行':>10} {'膨胀':>8}")
    for pct in (5, 25, 50, 75, 100):
        rows = []
        for i in range(rows_n):
            r = {"Id": i}
            for k in range(NF - 3):
                if (i * 31 + k * 17) % 100 < pct:
                    r[f"V{k:02d}"] = i + k + 1
            if (i * 7) % 100 < pct:
                r["VName"] = f"n{i}"
            if (i * 11) % 100 < pct:
                r["Tags"] = [1, 2, 3]
            rows.append(r)
        normal = build_canonical_table_bytes(rows, table, records={}, enums={})
        uni = build_canonical_table_bytes(rows, table, records={}, enums={}, uniform=True)
        print(f"  {pct:>7}% {len(normal) / rows_n:>10.1f} {len(uni) / rows_n:>10.1f} "
              f"{len(uni) / len(normal):>7.2f}x")


if __name__ == "__main__":
    check_r1()
    check_r2()
