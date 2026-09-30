"""模板语义对照（rust-native-core 任务 1.6）。

用法（仓库根目录）::

    ct/.venv/Scripts/python.exe native/fixtures/template/compare_semantics.py <rust.xlsx> <expected.semantics.json>

用 openpyxl 语义转储 Rust 产出，与 Python golden 的转储逐项 diff。
列宽按 rust_xlsxwriter 的 Excel 内边距补偿归一（16 → 16.7109375 显示等价）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent.parent / "ct" / "src"))

from generate import dump_semantics  # noqa: E402


def _norm_width(v: float) -> float:
    """rust_xlsxwriter 补偿 Excel 单元格内边距（+0.7109375），显示等价。"""
    frac = v % 1
    if abs(frac - 0.7109375) < 0.01:
        return float(int(v))
    return v


def _norm_color(v):
    """颜色归一为 6 位 RRGGBB（openpyxl 前缀 00，rust_xlsxwriter 前缀 FF）。"""
    if isinstance(v, str) and len(v) == 8:
        return v[2:]
    return v


def normalize(doc: dict) -> dict:
    doc = dict(doc)
    doc["fills"] = {k: _norm_color(v) for k, v in doc["fills"].items()}
    doc["col_widths"] = {k: _norm_width(float(v)) for k, v in doc["col_widths"].items()}
    doc["row_heights"] = {k: round(float(v)) for k, v in doc["row_heights"].items()}
    return doc


def diff(a: dict, b: dict, path: str = "") -> list[str]:
    problems = []
    keys = set(a) | set(b)
    for key in sorted(keys):
        sub = f"{path}.{key}" if path else key
        va, vb = a.get(key), b.get(key)
        if isinstance(va, dict) and isinstance(vb, dict):
            problems.extend(diff(va, vb, sub))
        elif isinstance(va, list) and isinstance(vb, list):
            if va != vb:
                problems.append(f"{sub}: 列表不同\n  rust={va}\n  py  ={vb}")
        elif va != vb:
            problems.append(f"{sub}: rust={va!r} py={vb!r}")
    return problems


def main() -> int:
    rust_path, expected_path = Path(sys.argv[1]), Path(sys.argv[2])
    tmp = rust_path.with_suffix(".semantics.json")
    dump_semantics(rust_path, tmp)
    rust = normalize(json.loads(tmp.read_text(encoding="utf-8")))
    expected = normalize(json.loads(expected_path.read_text(encoding="utf-8")))
    tmp.unlink()

    problems = diff(rust, expected)
    if problems:
        print(f"{rust_path.name}: {len(problems)} 处差异")
        for p in problems:
            print("-", p)
        return 1
    print(f"{rust_path.name}: 语义一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())