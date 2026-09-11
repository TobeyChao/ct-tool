"""验证修法：让 uniform 模式下 **枚举槽位也无条件写出**，看是否得到单一 vtable 且读值正确。

修法就是把枚举分支也走「无条件写 + Slot(index)」：
    builder.PrependInt8(self._enum_index(...));  builder.Slot(index)
（flatbuffers 的 PrependInt8 是裸写，不带 default 语义，所以必然占位。）

用法：ct/.venv/bin/python <此脚本>
"""
from __future__ import annotations

import os

import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CT = HERE.parents[2]
sys.path.insert(0, str(CT / "ct" / "src"))
sys.path.insert(0, str(Path.home() / ".cache" / "dsh-patch"))

from uniform_enum_check import (  # noqa: E402
    PatchUniformBuilder,
    export_once,
    load_bundle_tables,
    probe_layout,
    row_vtables,
    i32,
    u16,
)


class FixedUniformBuilder(PatchUniformBuilder):
    """唯一区别：枚举槽位无条件写出。"""

    def _build_row(self, builder, row):
        if not self.uniform:
            return super()._build_row(builder, row)
        from ct.export.canonical_binary import _slot
        from ct.schema.type_expression import NamedType, ScalarType, VectorType

        fields = [f for f in self.table.fields if not f.server_only]
        offsets: dict[int, int] = {}
        for index, field in enumerate(fields):
            if self._is_offset_type(field.type_expr):
                off = self._build_offset(builder, field.type_expr, row.get(field.name), required=True)
                if off is not None:
                    offsets[index] = off
        builder.StartObject(len(fields))
        for index, field in enumerate(fields):
            t = field.type_expr
            if index in offsets:
                builder.PrependUOffsetTRelativeSlot(index, offsets[index], 0)
            elif isinstance(t, ScalarType):
                self._prepend_scalar_slot(builder, t, row.get(field.name), index)
            elif isinstance(t, NamedType):
                if self._named_kind(t) == "enum":
                    builder.PrependInt8(self._enum_index(t, row.get(field.name)))  # ← 裸写，必占位
                    builder.Slot(index)
                elif self._named_kind(t) == "record":
                    off = self._build_record(builder, self.records[t.name], row.get(field.name))
                    if off is not None:
                        builder.PrependUOffsetTRelativeSlot(_slot(index), off, 0)
        return builder.EndObject()

    def _build_record(self, builder, record, data):
        if not self.uniform:
            return super()._build_record(builder, record, data)
        from ct.export.canonical_binary import _slot
        from ct.schema.type_expression import NamedType, ScalarType

        fields = record.fields
        offsets: dict[int, int] = {}
        if data is None:
            data = {}
        for index, field in enumerate(fields):
            if self._is_offset_type(field.type_expr):
                off = self._build_offset(builder, field.type_expr, data.get(field.name), required=True)
                if off is not None:
                    offsets[index] = off
        builder.StartObject(len(fields))
        for index, field in enumerate(fields):
            t = field.type_expr
            if index in offsets:
                builder.PrependUOffsetTRelativeSlot(index, offsets[index], 0)
            elif isinstance(t, ScalarType):
                self._prepend_scalar_slot(builder, t, data.get(field.name), index)
            elif isinstance(t, NamedType) and self._named_kind(t) == "enum":
                builder.PrependInt8(self._enum_index(t, data.get(field.name)))
                builder.Slot(index)
        return builder.EndObject()


def export_with(dest: Path, builder_cls, uniform: bool | None):
    import shutil
    from ct.export import canonical_binary as cb
    from ct.app.canonical_export import run_canonical_export

    FIXTURE = CT / "ct/tests/fixtures/repository_cutover/workspace"
    if dest.exists():
        shutil.rmtree(dest)
    for section in ("config", "excel", "i18n"):
        shutil.copytree(FIXTURE / section, dest / section)
    original = cb._Builder
    if uniform is not None:
        cb._Builder = lambda t, r, e: builder_cls(t, r, e, uniform=uniform)
    try:
        run_canonical_export(dest)
    finally:
        cb._Builder = original


def main() -> None:
    import tempfile

    tmp = Path(tempfile.mkdtemp(prefix="uniformfix-"))
    print(f"[tmp] {tmp}\n")

    normal, patched, fixed = tmp / "normal", tmp / "patched", tmp / "fixed"
    export_with(normal, PatchUniformBuilder, None)
    export_with(patched, PatchUniformBuilder, True)
    export_with(fixed, FixedUniformBuilder, True)

    def bundle(d):
        return (d / "output" / "binary" / "data_zh.bin").read_bytes()

    nb, pb, fb = bundle(normal), bundle(patched), bundle(fixed)
    print(f"bundle: 常规 {len(nb):,} B   定宽(patch原样) {len(pb):,} B   定宽(枚举已修) {len(fb):,} B")
    print(f"        修正版膨胀 {len(fb)/len(nb):.3f}x\n")

    for label, raw in (("patch 原样", pb), ("枚举已修", fb)):
        print(f"===== {label} =====")
        print(f"{'表':<12}{'行数':>5}{'字节':>8}{'vt数':>6}   结论")
        for name, data in load_bundle_tables(raw).items():
            cnt, cont, _, _ = row_vtables(data)
            nvt = len(set(cont))
            v = "✅ 单 vtable" if nvt == 1 else f"❌ {nvt} 种"
            print(f"{name:<12}{cnt:>5}{len(data):>8,}{nvt:>6}   {v}")
        print()

    # 修正版：逐行验证字面量路径与 vtable 路径一致
    from ct.config import load_config
    from ct.schema.resource_repository import YamlResourceRepository
    from ct.schema.type_expression import NamedType

    cfg = load_config(fixed)
    res = YamlResourceRepository(cfg.resolve("schemas_dir"), cfg.resolve("types_dir")).load()
    records = {r.name: r for r in res.records}
    enums = {e.name: e for e in res.enums}

    print("===== 修正版：probe 字面量路径 vs 正确 vtable 路径 =====")
    for name, data in load_bundle_tables(fb).items():
        table = next((t for t in res.tables if t.table == name), None)
        if table is None:
            continue
        cl = [f for f in table.fields if not f.server_only]
        p = probe_layout(table, records, enums)
        cnt, _, _, slots = row_vtables(data)
        root = i32(data, 0)
        vt = root - i32(data, root)
        vtl = u16(data, vt)
        io = u16(data, vt + 4) if 4 < vtl else 0
        vec = root + io + i32(data, root + io)
        base = vec + 4
        bad = 0
        for i in range(cnt):
            e = base + i * 4
            row = e + i32(data, e)
            for index, f in enumerate(cl):
                slot = 4 + 2 * index
                toff = slots[i].get(slot, 0)
                tval = data[row + toff] if toff else 0
                lval = data[row + p.get(slot, 0)]
                if tval != lval:
                    bad += 1
        print(f"  {name:<12} {cnt} 行 × {len(cl)} 字段：{'✅ 全部一致' if bad==0 else f'❌ {bad} 处不一致'}")


if __name__ == "__main__":
    main()
