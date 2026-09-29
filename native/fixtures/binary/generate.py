"""生成 FlatBuffers 二进制对照夹具（rust-native-core 任务 1.7）。

运行方式（仓库根目录）::

    ct/.venv/Scripts/python.exe native/fixtures/binary/generate.py

直接调用 canonical 生成器（不经过 Excel），输入（Schema/行数据）与产出
（golden .bin）都落盘：Rust 原型读取 input/*.json 重建字节并与
golden/*.bin 逐字节对照。

类型表达式线格式：{"scalar": "int32"} / {"named": "ItemRarity"} /
{"vector": {"element": {...}}}。
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent.parent.parent / "ct" / "src"))

from ct.export.canonical_binary import (  # noqa: E402
    build_canonical_bundle,
    build_canonical_table_bytes,
    count_vtables,
)
from ct.schema.resources import (  # noqa: E402
    EnumResource,
    FieldDef,
    QueryIndex,
    RecordResource,
    TableResource,
)

INPUT = HERE / "input"
GOLDEN = HERE / "golden"


def _type(expr: dict):
    from ct.schema.type_expression import parse_type_expression

    if "scalar" in expr:
        return parse_type_expression(expr["scalar"])
    if "named" in expr:
        return parse_type_expression(expr["named"])
    if "vector" in expr:
        inner = expr["vector"]["element"]
        inner_text = inner.get("scalar") or inner.get("named")
        if inner_text is None:
            raise AssertionError(f"嵌套 vector 元素暂不支持: {expr}")
        length = expr["vector"].get("length")
        text = f"vector<{inner_text}>" if length is None else f"vector<{inner_text},{length}>"
        return parse_type_expression(text)
    raise AssertionError(f"未知类型表达式: {expr}")


def _build_resources(doc: dict):
    records = {
        name: RecordResource(
            name=name,
            fields=[FieldDef(name=f["name"], type=_type(f["type"])) for f in spec["fields"]],
        )
        for name, spec in doc.get("records", {}).items()
    }
    enums = {
        name: EnumResource(name=name, values=values)
        for name, values in doc.get("enums", {}).items()
    }
    return records, enums


def _build_table(spec: dict) -> TableResource:
    return TableResource(
        table=spec["name"],
        primary=spec.get("primary", ""),
        fields=[
            FieldDef(
                name=f["name"],
                type=_type(f["type"]),
                server_only=f.get("server_only", False),
            )
            for f in spec["fields"]
        ],
        indexes=tuple(QueryIndex(kind=k) for k in spec.get("indexes", [])),
        uniform=spec.get("uniform", True),
    )


def run_case(path: Path) -> None:
    doc = json.loads(path.read_text(encoding="utf-8"))
    records, enums = _build_resources(doc)
    table = _build_table(doc["table"])
    rows = doc["rows"]

    start = time.perf_counter()
    for _ in range(50):
        data = build_canonical_table_bytes(
            rows, table, records=records, enums=enums, uniform=table.uniform
        )
    elapsed_ms = (time.perf_counter() - start) / 50 * 1000

    stem = path.stem
    (GOLDEN / f"{stem}.bin").write_bytes(data)
    vtables = count_vtables(data)
    print(f"{stem}: {len(data)} bytes, vtables={vtables}, {elapsed_ms:.3f} ms/次")

    if "bundle" in doc:
        parts = {}
        for entry in doc["bundle"]:
            sub_records, sub_enums = _build_resources(doc)
            sub_table = _build_table(entry["table"])
            parts[entry["table"]["name"]] = build_canonical_table_bytes(
                entry["rows"], sub_table, records=sub_records, enums=sub_enums,
                uniform=sub_table.uniform,
            )
        bundle = build_canonical_bundle(parts)
        (GOLDEN / f"{stem}_bundle.bin").write_bytes(bundle)
        print(f"{stem}_bundle: {len(bundle)} bytes")


def main() -> None:
    INPUT.mkdir(exist_ok=True)
    GOLDEN.mkdir(exist_ok=True)
    for path in sorted(INPUT.glob("*.json")):
        run_case(path)


if __name__ == "__main__":
    main()