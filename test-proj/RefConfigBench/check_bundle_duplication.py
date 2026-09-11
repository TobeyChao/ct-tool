"""检查 canonical 各语言 bundle 的重复度：非 i18n 表是否被逐语言整份复制。"""
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ct" / "src"))


def u16(b, o):
    return struct.unpack_from("<H", b, o)[0]


def i32(b, o):
    return struct.unpack_from("<i", b, o)[0]


def field_offset(b, obj, slot):
    vt = obj - i32(b, obj)
    vl = u16(b, vt)
    return 0 if (slot < 0 or slot >= vl) else u16(b, vt + slot)


def indirect(b, obj, slot):
    o = field_offset(b, obj, slot)
    return None if o == 0 else obj + o + i32(b, obj + o)


def vector(b, obj, slot):
    p = indirect(b, obj, slot)
    return None if p is None else (p + 4, i32(b, p))


def tables(path):
    d = Path(path).read_bytes()
    root = i32(d, 0)
    base, n = vector(d, root, 4)
    out = {}
    for i in range(n):
        e = base + i * 4
        entry = e + i32(d, e)
        np = indirect(d, entry, 4)
        name = d[np + 4:np + 4 + i32(d, np)].decode()
        dv = indirect(d, entry, 6)
        length = i32(d, dv)
        out[name] = d[dv + 4:dv + 4 + length]
    return out


def main():
    langs = ["zh", "en", "ja"]
    paths = {l: ROOT / "gd" / "output" / "binary" / f"data_{l}.bin" for l in langs}
    bundles = {l: tables(p) for l, p in paths.items()}

    print("bundle 大小:", {l: paths[l].stat().st_size for l in langs})
    print()
    hdr = "{:20} {:>7} {:>7} {:>7}   {}".format("table", "zh", "en", "ja", "en/ja 与 zh 是否逐字节相同")
    print(hdr)
    print("-" * len(hdr))

    dup_same = 0
    dup_diff = 0
    for name in bundles["zh"]:
        z = bundles["zh"][name]
        sizes = [len(bundles[l].get(name, b"")) for l in langs]
        flags = []
        for l in langs[1:]:
            if bundles[l].get(name) == z:
                flags.append("相同")
                dup_same += 1
            else:
                flags.append("不同")
                dup_diff += 1
        print("{:20} {:7} {:7} {:7}   {}".format(name, sizes[0], sizes[1], sizes[2], " / ".join(flags)))

    total = sum(p.stat().st_size for p in paths.values())
    zh = paths["zh"].stat().st_size
    print()
    print(f"三语言 bundle 合计 {total:,} 字节；若只存 zh + i18n 侧表，主包 {zh:,} 字节不必重复。")
    print(f"非 i18n 表逐语言完全重复的份数: {dup_same}；内容不同的份数: {dup_diff}")
    print(f"当前膨胀系数 ≈ {total / zh:.2f}x（语言数 {len(langs)}）")


if __name__ == "__main__":
    main()
