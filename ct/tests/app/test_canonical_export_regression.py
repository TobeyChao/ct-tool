"""canonical 导出回归：P1 清理时序、P2 空表导出。

这三个问题来自对待 push 提交的复查；修复集中在 ``canonical_export.py``：

- P1 ``run_canonical_export`` 的 B4 output/ 清理曾在校验**之前**执行，
  校验失败会把上次成功产物一并删掉；
- P2 空表（模板只有表头）被判为定宽，但 0 行 ⇒ 0 种 vtable，
  硬断言「恰好 1 种」直接失败。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from openpyxl import Workbook

from _helpers import build_project
from ct.app.canonical_commands import CanonicalValidationError
from ct.app.canonical_export import run_canonical_export


def _item_project(root: Path) -> Path:
    return build_project(
        root,
        schemas=[
            {
                "table": "Item",
                "primary": "Id",
                "fields": [
                    {"name": "Id", "type": "int32"},
                    {"name": "Name", "type": "string"},
                ],
            }
        ],
    )


def _write_excel(root: Path, rows: list[list]) -> None:
    (root / "excel").mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.append(["Id", "Name"])
    ws.append(["主键", "名称"])
    for row in rows:
        ws.append(row)
    wb.save(str(root / "excel" / "Item.xlsx"))


def test_export_failure_preserves_previous_artifacts(tmp_path: Path) -> None:
    """P1：output/ 清理必须发生在**校验通过之后** —— 失败导出不得吃掉上次成功产物。

    修复前 B4 清理在校验前执行：重复主键导致校验失败时，上次的
    output/binary 已被 rmtree。
    """
    root = _item_project(tmp_path / "gd")
    _write_excel(root, [[1, "铁剑"], [2, "木剑"]])

    sentinel = root / "output" / "binary" / "data_zh.bin"
    sentinel.parent.mkdir(parents=True, exist_ok=True)
    sentinel.write_bytes(b"LAST-GOOD-BUNDLE")

    # 引入重复主键 → 校验失败
    _write_excel(root, [[1, "铁剑"], [1, "重复主键"]])

    with pytest.raises(CanonicalValidationError):
        run_canonical_export(root)

    assert sentinel.read_bytes() == b"LAST-GOOD-BUNDLE", (
        "校验失败后上次成功产物必须原样保留"
    )
    # 失败导出也不得残留半成品目录
    assert not (root / "output" / "json").exists() or not any(
        (root / "output" / "json").glob("*.json")
    )


def test_export_empty_table(tmp_path: Path) -> None:
    """P2：空表（模板只有表头，0 行）必须能导出。

    修复前空表被判定宽（无行 ⇒ 填充率 1.0），但 0 行 ⇒ 0 种 vtable，
    ``_assert_single_vtable`` 的「恰好 1 种」断言直接失败。
    空表的 i18n 侧表同样走该断言（0 行），一并覆盖。
    """
    root = build_project(
        tmp_path / "gd",
        schemas=[
            {
                "table": "Item",
                "primary": "Id",
                "fields": [
                    {"name": "Id", "type": "int32"},
                    {"name": "Name", "type": "string", "i18n": True},
                ],
            }
        ],
    )
    (root / "excel").mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.append(["Id", "Name"])
    ws.append(["主键", "名称"])
    wb.save(str(root / "excel" / "Item.xlsx"))  # 只有表头

    run_canonical_export(root)

    assert (root / "output" / "binary" / "data_zh.bin").exists()
    assert (root / "output" / "binary" / "data_en.bin").exists()
    assert (root / "output" / "generated" / "lua" / "ItemAccessor.lua").exists()
    assert (root / "output" / "generated" / "csharp" / "ItemAccessor.cs").exists()
    assert (root / "output" / "json" / "Item_zh.json").exists()


def test_export_uniform_double_with_i18n_and_reuse(tmp_path: Path) -> None:
    root = build_project(tmp_path / 'gd', schemas=[{
        'table': 'Item', 'primary': 'Id', 'fields': [
            {'name': 'Id', 'type': 'int32'},
            {'name': 'Value', 'type': 'double'},
            {'name': 'Name', 'type': 'string', 'i18n': True},
        ],
    }])
    (root / 'excel').mkdir()
    wb = Workbook()
    ws = wb.active
    ws.append(['主键', '数值', '名称'])
    ws.append(['Id', 'Value', 'Name'])
    for i in range(1, 20):
        ws.append([i, i + .125, '字' * i])
    wb.save(root / 'excel' / 'Item.xlsx')
    run_canonical_export(root)
    outputs = {p: p.read_bytes() for p in (root / 'output').rglob('*') if p.is_file()}
    assert (root / 'output' / 'binary' / 'data_zh.bin') in outputs
    assert (root / 'output' / 'binary' / 'data_en.bin') in outputs
    run_canonical_export(root)
    assert all(p.read_bytes() == value for p, value in outputs.items())
