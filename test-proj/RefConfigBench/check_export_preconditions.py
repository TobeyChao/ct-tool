"""验证 fabulous-game 新读取方案对我方导出器的两个前提是否成立。

前提 P8（Config系统优化方案 §P8）：
  「同一张表的所有行 SHALL 共享同一个 vtable（导出器不得按行裁剪缺省字段）」
  —— 若不成立，把 slot→offset 解析一次存成 int[] 会静默读错字段。

前提 C8（Config系统实现分析 §C8）：
  「i18n entries 与 items 同序等长」，且 i18n entry 与主表用相同槽位号
  —— 若不成立，RowAt(i18nBase, idx) 的平行定位会取错行。

用法：
  cd ct && .venv\\Scripts\\python test-proj\\RefConfigBench\\check_export_preconditions.py
"""
from __future__ import annotations

import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "ct", "src"))

GD = os.path.join(ROOT, "gd")


def u16(b: bytes, o: int) -> int:
    return struct.unpack_from("<H", b, o)[0]


def i32(b: bytes, o: int) -> int:
    return struct.unpack_from("<i", b, o)[0]


def field_offset(b: bytes, obj: int, slot: int) -> int:
    vt = obj - i32(b, obj)
    vt_len = u16(b, vt)
    if slot < 0 or slot >= vt_len:
        return 0
    return u16(b, vt + slot)


def indirect(b: bytes, obj: int, slot: int) -> int | None:
    off = field_offset(b, obj, slot)
    if off == 0:
        return None
    return obj + off + i32(b, obj + off)


def root_table(b: bytes) -> int:
    return i32(b, 0)


def vector(b: bytes, obj: int, slot: int) -> tuple[int, int] | None:
    """返回 (元素区起点, 元素个数)。"""
    p = indirect(b, obj, slot)
    if p is None:
        return None
    return p + 4, i32(b, p)


def row_vtables(b: bytes) -> tuple[int, list[tuple[int, bytes]]]:
    """返回 (行数, [(vtable地址, vtable内容)...])，按行序。"""
    root = root_table(b)
    vec = vector(b, root, 4)
    if vec is None:
        return 0, []
    base, count = vec
    out = []
    for i in range(count):
        e = base + i * 4
        row = e + i32(b, e)
        vt = row - i32(b, row)
        vt_len = u16(b, vt)
        out.append((vt, b[vt:vt + vt_len]))
    return count, out


def describe(name: str, b: bytes) -> None:
    root = root_table(b)
    vec = vector(b, root, 4)
    if vec is None:
        print(f"{name}: 无 items 向量")
        return
    base, count = vec
    nd, rows = row_vtables(b)
    addrs = {a for a, _ in rows}
    contents = {c for _, c in rows}

    # 行首字段相对该行 vtable 的偏移分布（用来判断"哪些槽位按行裁剪"）
    slot_variants: dict[int, set[int]] = {}
    for vt_addr, vt_bytes in rows:
        for slot in range(4, max(4, u16(b, vt_addr)), 2):
            slot_variants.setdefault(slot, set()).add(u16(b, vt_addr + slot))

    row_bytes = [i32(b, base + i * 4) for i in range(count)]
    stride = None
    if count >= 2 and row_bytes[1] != row_bytes[0]:
        stride = row_bytes[1] - row_bytes[0]

    print(f"\n--- {name} ---")
    print(f"  items: {count} 行, 缓冲 {len(b):,} 字节, 行距={'恒定 ' + str(stride) if stride else '变长'}")
    print(f"  不同 vtable 地址数: {len(addrs)}   不同 vtable 内容数: {len(contents)}")
    print(f"  P8 前提（所有行共享同一 vtable）: {'成立' if len(contents) == 1 else '不成立 <<<'}")
    if len(contents) > 1:
        varying = {s: v for s, v in slot_variants.items() if len(v) > 1}
        if varying:
            print("  按行变化的槽位（slot -> 出现过的 offset）:")
            for s in sorted(varying):
                vals = sorted(varying[s])
                print(f"    slot {s:3d} (字段序 {(s - 4) // 2:2d}): {vals}")


def main() -> None:
    # 1) ct-tool 自身工作区的导出物
    for rel in ("output/binary/data_zh.bin", "output/binary/data_en.bin"):
        p = os.path.join(GD, rel)
        if os.path.exists(p):
            print(f"\n[gd] {rel}")
            from ct.export.canonical_binary import build_canonical_bundle  # noqa: F401

            data = open(p, "rb").read()
            # DataBundle: root -> tables 向量
            root = root_table(data)
            tables = vector(data, root, 4)
            if tables is None:
                print("  bundle 无 tables 向量")
                continue
            tbase, tcount = tables
            for i in range(tcount):
                e = tbase + i * 4
                entry = e + i32(data, e)
                name_p = indirect(data, entry, 4)
                name = data[name_p + 4:name_p + 4 + i32(data, name_p)].decode("utf-8")
                data_vec = indirect(data, entry, 6)
                if data_vec is None:
                    continue
                dlen = i32(data, data_vec)
                describe(f"{rel} :: {name}", data[data_vec + 4:data_vec + 4 + dlen])

    # 2) 基准复刻表
    fix = os.path.join(HERE, "fixtures")
    for name in ("ItemBench.bin", "ArrayBench.bin"):
        p = os.path.join(fix, name)
        if os.path.exists(p):
            describe(name, open(p, "rb").read())


if __name__ == "__main__":
    main()
