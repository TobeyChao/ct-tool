"""为 N1 生成「12 种标量」的验证数据 + C# accessor（不经过 Excel）。

用法：CT_TOOL=/path/to/ct-tool ct/.venv/bin/python gen_scalars_bench.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CT = Path(os.environ.get("CT_TOOL", "/Users/tobeychao/Documents/Projects/ct-tool"))
sys.path.insert(0, str(CT / "ct" / "src"))

from ct.export.canonical_accessor import render_csharp_accessor  # noqa: E402
from ct.export.canonical_binary import (  # noqa: E402
    build_canonical_bundle,
    build_canonical_table_bytes,
    probe_row_layout,
)
from ct.schema.resources import FieldDef, TableResource  # noqa: E402
from ct.schema.type_expression import SCALAR_TYPE_NAMES  # noqa: E402

# 每种标量取**非默认值**（默认值会被省略槽位，那是另一条规则，见 ct-tool 单测）
VALUES = {
    "int8": -128,
    "uint8": 255,
    "int16": -32768,
    "uint16": 65535,
    "int32": -2147483648,
    "uint32": 4294967295,
    "int64": -9223372036854775808,
    "uint64": 18446744073709551615,
    "float": 1.5,
    "double": -2.5e10,
    "bool": True,
    "string": "配置",
}


def main() -> None:
    names = sorted(SCALAR_TYPE_NAMES - {"int32"})
    table = TableResource(
        table="Scalars",
        primary="Id",
        fields=[FieldDef(name="Id", type="int32")]
        + [FieldDef(name=f"V{n}", type=n) for n in names],
    )
    row = {"Id": 7, **{f"V{n}": VALUES[n] for n in names}}
    data = build_canonical_table_bytes([row], table, records={}, enums={})
    layout = probe_row_layout(table, records={}, enums={})

    (HERE / "fixtures").mkdir(parents=True, exist_ok=True)
    (HERE / "fixtures" / "scalars.bin").write_bytes(
        build_canonical_bundle({table.table: data})
    )
    (HERE / "fixtures" / "scalars.json").write_text(
        json.dumps({"Id": 7, **{f"V{n}": VALUES[n] for n in names}}, indent=1),
        encoding="utf-8",
    )
    # 非 uniform（偏移表）形态即可——本验证只关心标量类型能不能正确读写
    (HERE / "generated" / "ScalarsAccessor.cs").write_text(
        render_csharp_accessor(table, ()), encoding="utf-8"
    )
    print("Scalars 表:", ", ".join(f"V{n}" for n in names))
    print("slot→offset:", {k: v for k, v in sorted(layout.items())})


if __name__ == "__main__":
    main()
