"""扫 参考实现 生成代码，挑出适合做读取基准的表（行数 / 数组字段 / i18n 字段）。"""
import json
import os
import re

GEN = r"D:\dev_trunk_ref\client\Assets\Scripts\Frameworks\Configs\Runtime\Generate"
HERE = os.path.dirname(os.path.abspath(__file__))

tabs = json.load(open(os.path.join(HERE, "ref_tables.json"), encoding="utf-8"))

rows = []
for fn in os.listdir(GEN):
    if not fn.endswith(".cs"):
        continue
    src = open(os.path.join(GEN, fn), encoding="utf-8", errors="ignore").read()
    name = fn[:-3]
    info = tabs.get(name)
    if not info:
        continue
    rows.append(
        {
            "table": name,
            "rows": info["rows"],
            "index": info["index"],
            "int_arr": len(re.findall(r"NArray<int>", src)),
            "str_arr": len(re.findall(r"NStructArray<NString>", src)),
            "i18n": len(re.findall(r"I18NString", src)),
            "fields": len(re.findall(r"public [\w<>\[\]]+ \w+ \{ get\{", src)),
        }
    )

hdr = "{:34} {:>8} {:>6} {:>6} {:>5} {:>7}".format("table", "rows", "i32[]", "str[]", "i18n", "fields")
print(hdr)
print("-" * len(hdr))
for r in sorted(rows, key=lambda x: -x["rows"])[:18]:
    print(
        "{:34} {:8} {:6} {:6} {:5} {:7}".format(
            r["table"], r["rows"], r["int_arr"], r["str_arr"], r["i18n"], r["fields"]
        )
    )

print()
print("--- >=3 int arrays, by rows desc ---")
for r in sorted([x for x in rows if x["int_arr"] >= 3], key=lambda x: -x["rows"])[:12]:
    print(
        "{:34} rows={:8} i32[]={:3} str[]={:3} i18n={:3} fields={}".format(
            r["table"], r["rows"], r["int_arr"], r["str_arr"], r["i18n"], r["fields"]
        )
    )

json.dump(rows, open(os.path.join(HERE, "ref_table_shapes.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
print("\nwrote ref_table_shapes.json")
