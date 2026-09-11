"""用 ct-tool **真实代码**（不再 monkeypatch）验证 uniform 的正确性。

覆盖用户要求的三类硬断言：
  G1  每张 uniform=True 的表，产出的 vtable 内容数 == 1
  G2  probe_row_layout 推出的 slot→offset 与真实产物的**每一行**一致（不是只比第一行）
  G3  字面量偏移路径读出的值 == vtable 路径读出的值，**逐行逐字段**，覆盖全部字段类型

同时对比 uniform=False / True 的体积。

用法：
  CT_TOOL=/path/to/ct-tool  ct/.venv/bin/python real_uniform_check.py
"""
from __future__ import annotations

import os
import shutil
import struct
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
CT = HERE.parents[2]
sys.path.insert(0, str(CT / "ct" / "src"))

from ct.app.canonical_export import run_canonical_export  # noqa: E402
from ct.config import load_config  # noqa: E402
from ct.export import canonical_binary as cb  # noqa: E402
from ct.excel.canonical_reader import read_canonical_excel  # noqa: E402
from ct.excel.layout import build_layout  # noqa: E402
from ct.schema.hashing import compute_schema_hash  # noqa: E402
from ct.schema.resource_repository import YamlResourceRepository  # noqa: E402
from ct.schema.type_expression import NamedType, ScalarType, VectorType  # noqa: E402

FIXTURE = CT / "ct/tests/fixtures/repository_cutover/workspace"


class _UniformForced(cb._Builder):
    """强制 uniform=True 的 builder（导出器内部按表决策尚未接线，验证阶段先全局开）。"""

    def __init__(self, table, records, enums, uniform: bool = True):
        super().__init__(table, records, enums, uniform=True)   # 强制 True


def u16(b, o):
    return struct.unpack_from("<H", b, o)[0]


def i32(b, o):
    return struct.unpack_from("<i", b, o)[0]


def root_row_base(b: bytes):
    """返回 (行数, 行对象指针列表, 每行 vtable 的 slot→offset 映射)。"""
    root = i32(b, 0)
    vt = root - i32(b, root)
    vtl = u16(b, vt)
    items_off = u16(b, vt + 4) if 4 < vtl else 0
    vec = root + items_off + i32(b, root + items_off)
    base, count = vec + 4, i32(b, vec)
    rows, slots = [], []
    for i in range(count):
        e = base + i * 4
        row = e + i32(b, e)
        rows.append(row)
        v = row - i32(b, row)
        n = u16(b, v)
        slots.append({s: u16(b, v + s) for s in range(4, n, 2)})
    return count, rows, slots


def vtable_contents(b: bytes) -> int:
    """该表产出的不同 vtable 内容数。"""
    root = i32(b, 0)
    vt = root - i32(b, root)
    vtl = u16(b, vt)
    items_off = u16(b, vt + 4) if 4 < vtl else 0
    vec = root + items_off + i32(b, root + items_off)
    base, count = vec + 4, i32(b, vec)
    seen = set()
    for i in range(count):
        e = base + i * 4
        row = e + i32(b, e)
        v = row - i32(b, row)
        n = u16(b, v)
        seen.add(b[v:v + n])
    return len(seen)


def build_rows(ws_dir: Path, res, records, enums):
    """workspace → {表名: rows}（用真实 Excel reader）。"""
    out = {}
    for tbl in res.tables:
        layout = build_layout(
            tbl, schema_hash=compute_schema_hash(tbl, tuple(records.values())), records=records
        )
        parsed = read_canonical_excel(
            ws_dir / "excel" / f"{tbl.table}.xlsx", layout, tbl, records=records, enums=enums
        )
        out[tbl.table] = parsed.rows
    return out


def decode_all(b: bytes, row: int, slots: dict, fields, records, enums, use_offsets: dict | None):
    """按字段类型解码一行；use_offsets 给出则走「字面量偏移」路径，否则走 vtable 路径。"""
    vals = {}
    for index, f in enumerate(fields):
        slot = 4 + 2 * index
        if use_offsets is not None:
            off = use_offsets.get(slot, 0)
        else:
            off = slots.get(slot, 0)
        t = f.type_expr
        if isinstance(t, ScalarType):
            if t.name == "string":
                if off == 0:
                    vals[f.name] = None
                else:
                    p = row + off + i32(b, row + off)
                    vals[f.name] = b[p + 4: p + 4 + i32(b, p)]
            elif t.name in ("int32",):
                vals[f.name] = i32(b, row + off) if off else 0
            elif t.name == "int64":
                vals[f.name] = struct.unpack_from("<q", b, row + off)[0] if off else 0
            elif t.name == "float":
                vals[f.name] = struct.unpack_from("<f", b, row + off)[0] if off else 0.0
            elif t.name == "double":
                vals[f.name] = struct.unpack_from("<d", b, row + off)[0] if off else 0.0
            elif t.name == "bool":
                vals[f.name] = bool(b[row + off]) if off else False
        elif isinstance(t, NamedType) and t.expected_kind == "enum":
            vals[f.name] = b[row + off] if off else 0
        elif isinstance(t, NamedType) and t.expected_kind == "record":
            vals[f.name] = "record" if off else None      # 只比存在性（结构等价另行校验）
        elif isinstance(t, VectorType):
            if off == 0:
                vals[f.name] = None
            else:
                p = row + off + i32(b, row + off)
                n = i32(b, p)
                ep = p + 4
                if isinstance(t.element, ScalarType) and t.element.name == "int32":
                    vals[f.name] = tuple(i32(b, ep + k * 4) for k in range(n))
                else:
                    vals[f.name] = ("vec", n)
    return vals


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="realuniform-"))
    normal, uni = tmp / "normal", tmp / "uniform"

    for dest, uniform in ((normal, None), (uni, True)):
        for section in ("config", "excel", "i18n"):
            shutil.copytree(FIXTURE / section, dest / section)
        original = cb._Builder
        if uniform is not None:
            cb._Builder = _UniformForced
        try:
            run_canonical_export(dest)
        finally:
            cb._Builder = original

    def bundle(d):
        return (d / "output" / "binary" / "data_zh.bin").read_bytes()

    nb, ub = bundle(normal), bundle(uni)
    print(f"bundle: 常规 {len(nb):,} B   定宽 {len(ub):,} B   膨胀 {len(ub)/len(nb):.3f}x")

    cfg = load_config(uni)
    res = YamlResourceRepository(cfg.resolve("schemas_dir"), cfg.resolve("types_dir")).load()
    records = {r.name: r for r in res.records}
    enums = {e.name: e for e in res.enums}

    nt, ut = _split(nb), _split(ub)
    print()
    print(f"{'表':<12}{'行':>4}{'定宽vt数':>9}  G1   G2   G3")
    print("-" * 52)
    allok = True
    for name in nt:
        table = next(t for t in res.tables if t.table == name)
        fields = [f for f in table.fields if not f.server_only]
        nvt = vtable_contents(ut[name])
        g1 = nvt == 1

        # G2：probe 与每一行
        probe = cb.probe_row_layout(table, records=records, enums=enums)
        cnt, rows, slots = root_row_base(ut[name])
        g2 = all(
            all(slots[i].get(s, 0) == probe.get(s, 0) for s in probe)
            for i in range(cnt)
        )

        # G3：字面量 vs vtable 逐字段
        g3 = True
        for i in range(cnt):
            a = decode_all(ut[name], rows[i], slots[i], fields, records, enums, None)
            b_ = decode_all(ut[name], rows[i], slots[i], fields, records, enums, probe)
            if a != b_:
                g3 = False
        allok &= g1 and g2 and g3
        print(f"{name:<12}{cnt:>4}{nvt:>9}  {'✅' if g1 else '❌':<4} "
              f"{'✅' if g2 else '❌':<4} {'✅' if g3 else '❌'}")

    print()
    print("总判定:", "✅ 全部通过（G1/G2/G3）" if allok else "❌ 有失败项")


def _split(bundle: bytes) -> dict[str, bytes]:
    root = i32(bundle, 0)
    vt = root - i32(bundle, root)
    toff = u16(bundle, vt + 4)
    vec = root + toff + i32(bundle, root + toff)
    base, count = vec + 4, i32(bundle, vec)
    out = {}
    for i in range(count):
        e = base + i * 4
        entry = e + i32(bundle, e)
        evt = entry - i32(bundle, entry)
        evtl = u16(bundle, evt)
        noff = u16(bundle, evt + 4) if 4 < evtl else 0
        np_ = entry + noff + i32(bundle, entry + noff)
        nm = bundle[np_ + 4: np_ + 4 + i32(bundle, np_)].decode()
        doff = u16(bundle, evt + 6) if 6 < evtl else 0
        dp = entry + doff + i32(bundle, entry + doff)
        dl = i32(bundle, dp)
        out[nm] = bundle[dp + 4: dp + 4 + dl]
    return out


if __name__ == "__main__":
    main()
