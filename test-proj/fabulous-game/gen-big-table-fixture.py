"""造一个 6685 行的表 + Lua 访问器，用来量 Lua userdata 缓存的实际驻留。"""
import os, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
CT = HERE.parents[1]
sys.path.insert(0, str(CT / "ct" / "src"))
sys.path.insert(0, str(CT / "test-proj" / "UniformE2EBench"))
from gen_our_item_bench import build                      # 同语料（6685 行 / 真实 Item 形状）
from ct.export.canonical_accessor import render_lua_accessor
from ct.export.canonical_binary import build_canonical_bundle, build_canonical_table_bytes

table, records, enums, rows = build()
data = build_canonical_table_bytes(rows, table, records=records, enums=enums, uniform=True)
Path("/tmp/weak/data.bin").write_bytes(build_canonical_bundle({table.table: data}))
Path("/tmp/weak/OurItemAccessor.lua").write_text(render_lua_accessor(table, ()), encoding="utf-8")
print(f"表 {table.table}: {len(rows)} 行, {len(data):,} B")
