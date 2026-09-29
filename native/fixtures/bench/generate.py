"""S/M/L 基准夹具生成器（任务 1.2）——**可选的历史资料生成器**：
不在验收路径上（`xtask bench` 在 `ct/` 缺席时改用本机留档回归判定即可继续工作），
只有需要**重新造夹具**时才需要仓库内 Python。夹具本身一旦生成，测量与判定都不再碰解释器。

只写入 --out 指定的目录（默认 native/target/bench），绝不触碰真实 gd/。
固定随机种子，重复运行得到完全相同的输入；产物目录里的 output/cache/.ct
在最后一步被清空，因此两个引擎都从「零缓存冷启动」开始测量。

用法（在仓库根目录）：
    ct/.venv/Scripts/python.exe native/fixtures/bench/generate.py --size s
    ct/.venv/Scripts/python.exe native/fixtures/bench/generate.py --size m --out native/target/bench

这里调用 Python 只是「造输入数据」，不是把旧工具链当运行依赖。
"""

from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]  # native/fixtures/bench -> 仓库根
SIZES = {"s": (10, 100), "m": (50, 2000), "l": (100, 10000)}
SEED = 20260918
LANGS = ["en", "ja"]


def ct_exe() -> Path:
    candidates = [
        REPO / "ct/.venv/Scripts/ct.exe",
        REPO / "ct/.venv/bin/ct",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise SystemExit(f"找不到 Python 参照入口（用于造夹具）：{candidates}")


def scalar_fields(table: str, base: str, uniform: bool, index: int) -> list[dict]:
    """20 列：标量为主，even 表填满（uniform），odd 表带 vector/Record/ref 且留空（非 uniform）。"""
    fields = [
        {"name": "Id", "type": "int32"},
        {"name": "CodeName", "type": "string"},
        {"name": "Name", "type": "string", "i18n": True},
        {"name": "Desc", "type": "string", "i18n": True},
        {"name": "Tag", "type": "string"},
        {"name": "Level", "type": "int32"},
        {"name": "Exp", "type": "int32"},
        {"name": "Cost", "type": "int32"},
        {"name": "Weight", "type": "int32"},
        {"name": "Big", "type": "int64"},
        {"name": "Huge", "type": "uint64"},
        {"name": "Small", "type": "int16"},
        {"name": "Flag", "type": "bool"},
        {"name": "Rate", "type": "float"},
        {"name": "Ratio", "type": "double"},
        {"name": "Quality", "type": "Rarity"},
        {"name": "Mode", "type": "Kind"},
        {"name": "Owner", "type": "int32"},
        {"name": "Score", "type": "int32"},
        {"name": "Note", "type": "string"},
    ]
    if uniform:
        # 填满的表仍然覆盖 ref（Owner -> Base.Id）；ref 目标表自身不引用来避免自环
        if table != base:
            fields[17]["ref"] = f"{base}.Id"
        return fields
    # 非 uniform 表：追加 vector<Record> 与 vector<int32>，并故意留空一部分
    fields = fields[:-1]
    fields += [
        {"name": "Drops", "type": "vector<DropRule>", "excel_columns": 2},
        {"name": "Chain", "type": "vector<int32>", "excel_columns": 3},
    ]
    if table != base:
        fields[17]["ref"] = f"{base}.Id"
    return fields


def write_yaml(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def build_config(root: Path, tables: int) -> list[str]:
    """写 global.yaml / types / schemas，返回表名列表（Base 为 ref 目标，永远 uniform）。"""
    (root / "config").mkdir(parents=True, exist_ok=True)
    write_yaml(
        root / "config/global.yaml",
        "primary_lang: zh\nsecondary_langs:\n"
        + "".join(f"  - {lang}\n" for lang in LANGS),
    )
    write_yaml(
        root / "config/types/rarity.yaml",
        "kind: enum\nname: Rarity\nvalues:\n"
        + "".join(f"  - name: {name}\n" for name in ("Common", "Rare", "Epic", "Legend", "Mythic")),
    )
    write_yaml(
        root / "config/types/kind.yaml",
        "kind: enum\nname: Kind\nvalues:\n"
        + "".join(f"  - name: {name}\n" for name in ("None", "Active", "Passive", "Hidden")),
    )
    write_yaml(
        root / "config/types/drop_rule.yaml",
        "kind: record\nname: DropRule\nfields:\n  - name: Min\n    type: int32\n  - name: Max\n    type: int32\n",
    )
    names = ["Base"] + [f"T{i:03d}" for i in range(1, tables)]
    for index, table in enumerate(names):
        uniform = index % 2 == 0
        fields = scalar_fields(table, "Base", uniform, index)
        text = (
            f"table: {table}\nprimary: Id\nfields:\n"
            + "".join(
                "  - name: {name}\n    type: {type}{extra}\n".format(
                    name=field["name"],
                    type=field["type"],
                    extra="".join(
                        part
                        for part in (
                            "\n    i18n: true" if field.get("i18n") else "",
                            f"\n    excel_columns: {field['excel_columns']}"
                            if field.get("excel_columns")
                            else "",
                            f"\n    ref: {field['ref']}" if field.get("ref") else "",
                        )
                    ),
                )
                for field in fields
            )
            + "indexes:\n  - kind: codename\n"
        )
        write_yaml(root / f"config/schemas/{table.lower()}.yaml", text)
    return names


def row_for(
    rng: random.Random, table: str, row: int, fields: list[dict], blank: bool = False
) -> list[object]:
    values: list[object] = []
    for field in fields:
        name = field["name"]
        kind = field["type"]
        # 非 uniform 表：约 12% 的可选单元格留空（主键与 codename 索引列除外）
        if blank and name not in {"Id", "CodeName"} and rng.random() < 0.12:
            values.append(None)
            continue
        if name == "Id":
            values.append(row)
        elif name == "Owner":
            # ref 列：必须落在 Base.Id 的取值范围内（所有尺寸的 Base 表至少有 100 行）
            values.append((row % 100) + 1)
        elif name == "CodeName":
            values.append(f"{table}_{row}")
        elif kind == "string":
            values.append(f"{name}{row}")
        elif kind == "int16":
            values.append(rng.randrange(0, 32000))
        elif kind in {"int32", "int64", "uint64"}:
            values.append(rng.randrange(0, 100000))
        elif kind == "bool":
            values.append(bool(row % 2))
        elif kind in {"float", "double"}:
            values.append(round(rng.uniform(0, 1), 4))
        elif kind in {"Rarity", "Kind"}:
            values.append(rng.choice(["Common", "Rare", "Epic", "Legend", "Mythic"]) if kind == "Rarity" else rng.choice(["None", "Active", "Passive", "Hidden"]))
        else:
            values.append(None)
    return values


def fill_excels(root: Path, tables: list[str], rows: int, rng: random.Random) -> int:
    """把数据行追加进 gen-template 产出的工作簿，返回写入的单元格数。"""
    from openpyxl import load_workbook

    cells = 0
    for table in tables:
        path = root / "excel" / f"{table}.xlsx"
        workbook = load_workbook(path)
        worksheet = workbook[table]
        # 表头占据前若干行（2D 表头里字段名与类型各占一行），按主键定位名称行
        # 2D 表头是"富文本单格两行"：单元格文本形如 "Id\nint32"
        def cell_name(row: int, column: int) -> str:
            raw = str(worksheet.cell(row=row, column=column).value or "")
            return raw.split("\n", 1)[0].strip()

        name_row = next(
            row
            for row in range(1, worksheet.max_row + 1)
            if any(cell_name(row, column) == "Id" for column in range(1, worksheet.max_column + 1))
        )
        columns = [cell_name(name_row, index) for index in range(1, worksheet.max_column + 1)]
        types = schema_types(root, table)
        id_column = columns.index("Id") if "Id" in columns else 0
        # 偶数下标表填满（uniform），奇数下标表留空格并带 vector 列（非 uniform）
        blank_cells = tables.index(table) % 2 == 1
        for row in range(1, rows + 1):
            values: list[object] = []
            for name in columns:
                kind = types.get(name)
                if not name or kind is None or kind.startswith("vector<"):
                    # 续列与 vector/Record 列在基准夹具里保持默认空值
                    values.append(None)
                    continue
                values.append(
                    row_for(rng, table, row, [{"name": name, "type": kind}], blank_cells)[0]
                )
            values[id_column] = row
            worksheet.append(values)
            cells += sum(1 for value in values if value is not None)
        workbook.save(path)
    return cells


def schema_types(root: Path, table: str) -> dict[str, str]:
    text = (root / f"config/schemas/{table.lower()}.yaml").read_text(encoding="utf-8")
    out: dict[str, str] = {}
    current = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("- name:"):
            current = stripped.split(":", 1)[1].strip()
        elif stripped.startswith("type:") and current:
            out[current] = stripped.split(":", 1)[1].strip()
    return out


def run_ct(workdir: Path, *args: str) -> None:
    result = subprocess.run(
        [str(ct_exe()), *args],
        cwd=workdir,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stdout + result.stderr).decode("utf-8", "replace")
        raise SystemExit(f"ct {' '.join(args)} 失败（退出码 {result.returncode}）：\n{detail}")


def translations(root: Path, tables: list[str]) -> int:
    """用 i18n sync 生成骨架，再填两种语言的确定值（供「改译文」场景使用）。"""
    run_ct(root, "i18n", "sync")
    written = 0
    for lang in LANGS:
        for table in tables:
            path = root / "i18n" / lang / f"{table}.json"
            if not path.is_file():
                continue
            payload = json.loads(path.read_text(encoding="utf-8"))
            changed = False
            for key, entry in (payload.items() if isinstance(payload, dict) else []):
                if isinstance(entry, dict) and "source" in entry:
                    entry["text"] = f"[{lang}] {entry['source']}"
                    entry["confirmed"] = True
                    entry["status"] = "confirmed"
                    changed = True
                    written += 1
            if changed:
                path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return written


def mutations(root: Path, tables: list[str]) -> dict:
    """为「改单表」「改译文」场景准备可复制的替换文件（只改一个单元格/一个条目）。"""
    target = tables[1] if len(tables) > 1 else tables[0]
    out = root / "mutations"
    out.mkdir(exist_ok=True)
    source = root / "excel" / f"{target}.xlsx"
    from openpyxl import load_workbook

    workbook = load_workbook(source)
    worksheet = workbook[target]
    # 2D 表头是 "名字\n类型" 单格两行；挑一个 string 列改写，避免撞类型闸门
    def head(row: int, column: int) -> str:
        raw = str(worksheet.cell(row=row, column=column).value or "")
        return raw.split("\n", 1)[0].strip()

    name_row = next(
        row
        for row in range(1, worksheet.max_row + 1)
        if any(head(row, column) == "Id" for column in range(1, worksheet.max_column + 1))
    )
    column_for = next(
        column
        for column in range(1, worksheet.max_column + 1)
        if head(name_row, column) in {"Note", "Tag", "CodeName"}
    )
    data_row = next(
        row
        for row in range(1, worksheet.max_row + 1)
        if str(worksheet.cell(row=row, column=1).value or "").strip() == "1"
    )
    worksheet.cell(row=data_row, column=column_for).value = "bench-mutation";
    workbook.save(out / f"{target}.xlsx")
    i18n = root / "i18n" / LANGS[0] / f"{target}.json"
    payload = json.loads(i18n.read_text(encoding="utf-8"))
    for key, entry in payload.items():
        if isinstance(entry, dict) and "text" in entry:
            entry["text"] = f"{entry['text']}!"
            entry["confirmed"] = False
            entry["status"] = "pending"
            break
    (out / f"{target}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    meta = {"table": target, "tableSource": f"excel/{target}.xlsx", "i18nLang": LANGS[0], "i18nTarget": f"i18n/{LANGS[0]}/{target}.json"}
    (out / "mutations.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return meta


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--size", choices=sorted(SIZES), required=True)
    parser.add_argument("--out", default=str(REPO / "native/target/bench"))
    args = parser.parse_args()
    tables, rows = SIZES[args.size]
    root = Path(args.out).resolve() / f"bench-{args.size}"
    if root.exists():
        shutil.rmtree(root)
    (root / "excel").mkdir(parents=True)
    rng = random.Random(SEED)
    names = build_config(root, tables)
    run_ct(root, "gen-template", "--all")
    cells = fill_excels(root, names, rows, rng)
    run_ct(root, "validate")
    translated = translations(root, names)
    meta = mutations(root, names)
    for leftover in ("output", "cache", ".ct"):
        target = root / leftover
        if target.exists():
            shutil.rmtree(target)
    summary = {
        "schema": "ct-bench-fixture/1",
        "size": args.size,
        "seed": SEED,
        "tables": len(names),
        "rowsPerTable": rows,
        "columnsPerTable": 20,
        "dataCells": cells,
        "translatedEntries": translated,
        "languages": ["zh", *LANGS],
        "uniform": "偶数表填满、奇数表含 vector<Record>/vector<int32> 且约 12% 单元格留空",
        "mutation": meta,
        "root": str(root),
    }
    (root / "FIXTURE.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()