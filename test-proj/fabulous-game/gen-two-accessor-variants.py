"""同一份定宽数据 + 两个访问器变体：字面量偏移 vs 槽位。用于端到端 A/B。"""
import sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
CT = HERE.parents[1]
sys.path.insert(0, str(CT / "ct" / "src"))
sys.path.insert(0, str(CT / "test-proj" / "UniformE2EBench"))
from gen_our_item_bench import build
from ct.export.canonical_accessor import generate_lua_accessor
from ct.export.canonical_accessor_model import build_accessor_model
from ct.export.canonical_binary import build_canonical_bundle, build_canonical_table_bytes, probe_row_layout

table, records, enums, rows = build()
data = build_canonical_table_bytes(rows, table, records=records, enums=enums, uniform=True)
Path("/tmp/weak/data.bin").write_bytes(build_canonical_bundle({table.table: data}))
layout = probe_row_layout(table, records=records, enums=enums)

for tag, offs in (("off", layout), ("slot", None)):
    d = Path(f"/tmp/weak/{tag}"); d.mkdir(exist_ok=True)
    model = build_accessor_model(table, (), records=records, uniform_offsets=offs)
    d.joinpath("Acc.lua").write_text(generate_lua_accessor(model), encoding="utf-8")
    print(f"  {tag}: slot_offsets={'有' if offs else '无'}")
