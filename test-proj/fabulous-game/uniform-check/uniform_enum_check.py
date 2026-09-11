"""用 ct-tool 自己的代码，验证 patch 的 uniform（定宽）实现是否真正产出「单一 vtable」。

关键怀疑点：patch 的 uniform 逻辑只给 **标量** 加了无条件写槽位（`_prepend_scalar_slot`），
**枚举分支原样保留** `PrependInt8Slot(index, ..., 0)` —— 而 flatbuffers 的 `PrependXSlot(slot, v, default)`
在 `v == default` 时**不写槽位**。枚举的 default 是 0，也就是「第 0 个枚举值」。
⇒ 若成立，则：
   (a) 含枚举字段的表在 uniform 下仍然每行 vtable 不同 ⇒ 定宽前提失败；
   (b) `probe_row_layout`（用全 None 的空白行推导 offset）会把枚举槽位推成 0
       ⇒ 生成的字面量访问器读 `row + 0`（= vtable soffset 字节）⇒ 静默读错。

用法：ct/.venv/bin/python <此脚本>
"""
from __future__ import annotations

import os

import shutil
import struct
import sys
import tempfile
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
CT = HERE.parents[2]
sys.path.insert(0, str(CT / "ct" / "src"))

from ct.app.canonical_export import run_canonical_export  # noqa: E402
from ct.export import canonical_binary as cb  # noqa: E402
from ct.export.canonical_binary import _Builder, _slot  # noqa: E402
from ct.schema.resources import RecordResource, TableResource  # noqa: E402
from ct.schema.type_expression import (  # noqa: E402
    NamedType,
    ScalarType,
    VectorType,
    parse_type_expression,
)

FIXTURE = CT / "ct/tests/fixtures/repository_cutover/workspace"


# --------------------------------------------------------------------------
# 1) 逐字复刻 patch 的 uniform 实现（唯一区别：枚举分支按 patch 原样，不加 uniform 处理）
# --------------------------------------------------------------------------
class PatchUniformBuilder(_Builder):
    def __init__(self, table, records, enums, uniform: bool = False):
        super().__init__(table, records, enums)
        self.uniform = uniform

    def _prepend_scalar_slot(self, builder, type_expr, value, index) -> None:
        name = type_expr.name
        if name == "int32":
            builder.PrependInt32(int(value) if value is not None else 0)
        elif name == "int64":
            builder.PrependInt64(int(value) if value is not None else 0)
        elif name == "float":
            builder.PrependFloat32(float(value) if value is not None else 0.0)
        elif name == "double":
            builder.PrependFloat64(float(value) if value is not None else 0.0)
        elif name == "bool":
            builder.PrependBool(bool(value) if value is not None else False)
        else:
            raise ValueError(f"uniform 布局不支持标量 {name}")
        builder.Slot(index)

    def _build_record(self, builder, record, data):
        if data is None:
            if not self.uniform:
                return None
            data = {}
        fields = record.fields
        offsets: dict[int, int] = {}
        for index, field in enumerate(fields):
            if self._is_offset_type(field.type_expr):
                offsets[index] = self._build_offset(
                    builder, field.type_expr, data.get(field.name), required=self.uniform
                )
        builder.StartObject(len(fields))
        for index, field in enumerate(fields):
            if index in offsets and offsets[index] is not None:
                builder.PrependUOffsetTRelativeSlot(index, offsets[index], 0)
            elif self._is_offset_type(field.type_expr):
                continue
            elif isinstance(field.type_expr, ScalarType):
                if self.uniform:
                    self._prepend_scalar_slot(builder, field.type_expr, data.get(field.name), index)
                else:
                    self._prepend_scalar(builder, field.type_expr, data.get(field.name), index)
            elif isinstance(field.type_expr, NamedType) and self._named_kind(field.type_expr) == "enum":
                # ← patch 原样：没有 uniform 处理
                builder.PrependInt8Slot(index, self._enum_index(field.type_expr, data.get(field.name)), 0)
        return builder.EndObject()

    def _build_offset(self, builder, type_expr, value, required: bool = False):
        if isinstance(type_expr, ScalarType):
            if type_expr.name == "string":
                if value is None and not required:
                    return None
                return builder.CreateSharedString(str(value) if value is not None else "")
            return None
        if isinstance(type_expr, VectorType):
            return self._build_vector(builder, type_expr, value or [])
        if isinstance(type_expr, NamedType) and self._named_kind(type_expr) == "record":
            return self._build_record(builder, self.records[type_expr.name], value)
        return None

    def _build_row(self, builder, row):
        fields = [f for f in self.table.fields if not f.server_only]
        offsets: dict[int, int] = {}
        for index, field in enumerate(fields):
            if self._is_offset_type(field.type_expr):
                offset = self._build_offset(
                    builder, field.type_expr, row.get(field.name), required=self.uniform
                )
                if offset is not None:
                    offsets[index] = offset
        builder.StartObject(len(fields))
        for index, field in enumerate(fields):
            if index in offsets:
                builder.PrependUOffsetTRelativeSlot(index, offsets[index], 0)
            elif self._is_offset_type(field.type_expr):
                continue
            elif isinstance(field.type_expr, ScalarType):
                if self.uniform:
                    self._prepend_scalar_slot(builder, field.type_expr, row.get(field.name), index)
                else:
                    self._prepend_scalar(builder, field.type_expr, row.get(field.name), index)
            elif isinstance(field.type_expr, NamedType):
                if self._named_kind(field.type_expr) == "enum":
                    # ← patch 原样：没有 uniform 处理
                    builder.PrependInt8Slot(index, self._enum_index(field.type_expr, row.get(field.name)), 0)
                elif self._named_kind(field.type_expr) == "record":
                    offset = self._build_record(
                        builder, self.records[field.type_expr.name], row.get(field.name)
                    )
                    if offset is not None:
                        builder.PrependUOffsetTRelativeSlot(_slot(index), offset, 0)
        return builder.EndObject()


# --------------------------------------------------------------------------
# 2) 读产物
# --------------------------------------------------------------------------
def u16(b, o):
    return struct.unpack_from("<H", b, o)[0]


def i32(b, o):
    return struct.unpack_from("<i", b, o)[0]


def row_vtables(b: bytes):
    """返回 (行数, [vtable 内容 bytes...], [每行 vtable 地址])"""
    root = i32(b, 0)
    vt = root - i32(b, root)
    vtl = u16(b, vt)
    items_off = u16(b, vt + 4) if 4 < vtl else 0
    vec = root + items_off + i32(b, root + items_off)
    base, count = vec + 4, i32(b, vec)
    contents, addrs, slot_maps = [], [], []
    for i in range(count):
        e = base + i * 4
        row = e + i32(b, e)
        v = row - i32(b, row)
        n = u16(b, v)
        contents.append(b[v:v + n])
        addrs.append(v)
        slot_maps.append({s: u16(b, v + s) for s in range(4, n, 2)})
    return count, contents, addrs, slot_maps


def probe_layout(table, records, enums) -> dict[int, int]:
    """patch 的 probe_row_layout：用全 None 的空白行 + uniform 推导 slot→offset。"""
    blank = {f.name: None for f in table.fields if not f.server_only}
    data = PatchUniformBuilder(table, records, enums, uniform=True).build([blank])
    client = [f for f in table.fields if not f.server_only]
    root = i32(data, 0)
    vt = root - i32(data, root)
    vtl = u16(data, vt)
    items_off = u16(data, vt + 4) if 4 < vtl else 0
    vec = root + items_off + i32(data, root + items_off)
    first = vec + 4
    row = first + i32(data, first)
    rv = row - i32(data, row)
    rvl = u16(data, rv)
    out = {}
    for index in range(len(client)):
        slot = 4 + 2 * index
        out[slot] = u16(data, rv + slot) if slot < rvl else 0
    return out


def load_bundle_tables(bundle: bytes) -> dict[str, bytes]:
    root = i32(bundle, 0)
    vt = root - i32(bundle, root)
    tables_off = u16(bundle, vt + 4)
    vec = root + tables_off + i32(bundle, root + tables_off)
    base, count = vec + 4, i32(bundle, vec)
    out = {}
    for i in range(count):
        e = base + i * 4
        entry = e + i32(bundle, e)
        evt = entry - i32(bundle, entry)
        evtl = u16(bundle, evt)
        noff = u16(bundle, evt + 4) if 4 < evtl else 0
        np = entry + noff + i32(bundle, entry + noff)
        name = bundle[np + 4:np + 4 + i32(bundle, np)].decode()
        doff = u16(bundle, evt + 6) if 6 < evtl else 0
        dp = entry + doff + i32(bundle, entry + doff)
        dlen = i32(bundle, dp)
        out[name] = bundle[dp + 4:dp + 4 + dlen]
    return out


# --------------------------------------------------------------------------
# 3) 主流程
# --------------------------------------------------------------------------
def export_once(dest: Path, uniform: bool | None) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    for section in ("config", "excel", "i18n"):
        shutil.copytree(FIXTURE / section, dest / section)
    original = cb._Builder
    if uniform is not None:
        cb._Builder = lambda t, r, e: PatchUniformBuilder(t, r, e, uniform=uniform)
    try:
        run_canonical_export(dest)
    finally:
        cb._Builder = original


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="uniformchk-"))
    normal_dir, uni_dir = tmp / "normal", tmp / "uniform"
    print(f"[tmp] {tmp}\n")

    export_once(normal_dir, None)
    export_once(uni_dir, True)

    nb = (normal_dir / "output" / "binary" / "data_zh.bin").read_bytes()
    ub = (uni_dir / "output" / "binary" / "data_zh.bin").read_bytes()
    print(f"bundle 大小: 常规 {len(nb):>7,} B   定宽 {len(ub):>7,} B   "
          f"膨胀 {len(ub)/len(nb):.3f}x\n")

    nt, ut = load_bundle_tables(nb), load_bundle_tables(ub)
    print(f"{'表':<14}{'行数':>5}{'常规 B':>9}{'定宽 B':>9}{'膨胀':>8}"
          f"{'常规vt数':>10}{'定宽vt数':>10}   结论")
    print("-" * 88)
    for name in nt:
        n, u = nt[name], ut[name]
        nc, ncont, _, nslots = row_vtables(n)
        uc, ucont, _, uslots = row_vtables(u)
        nvt, uvt = len(set(ncont)), len(set(ucont))
        verdict = "✅ 单 vtable" if uvt == 1 else f"❌ 仍 {uvt} 种 vtable！"
        print(f"{name:<14}{nc:>5}{len(n):>9,}{len(u):>9,}{len(u)/len(n):>7.2f}x"
              f"{nvt:>10}{uvt:>10}   {verdict}")
        if uvt > 1:
            # 找出哪些槽位在行间变化
            vary = {}
            for sm in uslots:
                for s, off in sm.items():
                    vary.setdefault(s, set()).add(off)
            bad = {s: sorted(v) for s, v in vary.items() if len(v) > 1}
            print(f"                ↳ 行间变化的槽位: {bad}")

    # ---- 关键验证：probe 推出的 offset 与真实行是否一致（枚举字段最可疑）----
    print("\n=== probe_row_layout（空白行推导）vs 真实行 offset ===")
    ws_sys_path = str(CT / "ct" / "src")
    from ct.schema.resource_repository import YamlResourceRepository
    from ct.config import load_config

    cfg = load_config(normal_dir)
    repo = YamlResourceRepository(cfg.resolve("schemas_dir"), cfg.resolve("types_dir"))
    res = repo.load()
    records = {r.name: r for r in res.records}
    enums = {e.name: e for e in res.enums}

    for name, data in ut.items():
        table = next((t for t in res.tables if t.table == name), None)
        if table is None:
            continue
        cl = [f for f in table.fields if not f.server_only]
        p = probe_layout(table, records, enums)
        _, _, _, uslots = row_vtables(data)
        real_first = uslots[0]
        diffs = [
            (s, p.get(s), real_first.get(s))
            for s in sorted(p)
            if p.get(s) != real_first.get(s)
        ]
        enum_slots = [
            (4 + 2 * i, f.name)
            for i, f in enumerate(cl)
            if isinstance(f.type_expr, NamedType) and f.type_expr.expected_kind == "enum"
        ]
        print(f"\n[{name}]  枚举字段槽位: {enum_slots}")
        if diffs:
            print("  ❌ probe 与真实行不一致:")
            for s, a, b in diffs:
                mark = ""
                if any(s == es for es, _ in enum_slots):
                    mark = "   ← 枚举槽位！"
                print(f"     slot {s:>3} (字段序 {(s-4)//2}): probe={a:<4} 真实={b}{mark}")
        else:
            print("  ✅ probe 与真实行一致")


if __name__ == "__main__":
    main()


def proof_read_mismatch() -> None:
    """决定性验证：用 probe 推出的字面量 offset 去读枚举字段，逐行与正确路径对比。"""
    import shutil, tempfile
    from pathlib import Path as _P
    tmp = _P(tempfile.mkdtemp(prefix="uniformproof-"))
    export_once(tmp, True)
    ub = (tmp / "output" / "binary" / "data_zh.bin").read_bytes()
    tables = load_bundle_tables(ub)

    from ct.schema.resource_repository import YamlResourceRepository
    from ct.config import load_config
    cfg = load_config(tmp)
    repo = YamlResourceRepository(cfg.resolve("schemas_dir"), cfg.resolve("types_dir"))
    res = repo.load()
    records = {r.name: r for r in res.records}
    enums = {e.name: e for e in res.enums}

    print("\n\n=== 决定性验证：probe 字面量 offset 读枚举字段 vs 正确 vtable 路径 ===")
    for name, data in tables.items():
        table = next((t for t in res.tables if t.table == name), None)
        if table is None:
            continue
        cl = [f for f in table.fields if not f.server_only]
        enum_idx = [
            (i, 4 + 2 * i, f.name)
            for i, f in enumerate(cl)
            if isinstance(f.type_expr, NamedType) and f.type_expr.expected_kind == "enum"
        ]
        if not enum_idx:
            continue
        p = probe_layout(table, records, enums)
        cnt, _, _, slots = row_vtables(data)

        # 行对象地址
        root = i32(data, 0)
        vt = root - i32(data, root)
        vtl = u16(data, vt)
        items_off = u16(data, vt + 4) if 4 < vtl else 0
        vec = root + items_off + i32(data, root + items_off)
        base = vec + 4

        print(f"\n[{name}]")
        for fi, slot, fname in enum_idx:
            print(f"  字段 {fname}（slot {slot}）: probe offset = {p.get(slot)}")
            bad = 0
            for i in range(cnt):
                e = base + i * 4
                row = e + i32(data, e)
                true_off = slots[i].get(slot, 0)
                # 正确路径：有 offset 才读，否则视为默认（第 0 项）
                true_val = data[row + true_off] if true_off else 0
                # probe 字面量路径：无条件按 probe offset 读
                probe_off = p.get(slot, 0)
                lit_val = data[row + probe_off]
                if true_val != lit_val:
                    bad += 1
                    if bad <= 3:
                        print(f"    行 {i}: 正确={true_val}  字面量offset读到={lit_val}  "
                              f"（真实offset={true_off}，probe给的是{probe_off}）")
            if bad:
                print(f"    ❌ {bad}/{cnt} 行读错（静默，不崩）")
            else:
                print(f"    ✅ {cnt} 行全部一致")


if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] == "proof":
    proof_read_mismatch()
