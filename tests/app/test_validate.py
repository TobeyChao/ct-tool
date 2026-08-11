"""parse_and_validate：reader issues 与校验结果合并、无双报。"""

from __future__ import annotations

from pathlib import Path

import yaml
from openpyxl import Workbook

from ct.app.validate import parse_and_validate
from ct.app.workspace import Workspace
from ct.cache.state import CacheState


def _build_project(root: Path) -> None:
    (root / "config" / "schemas").mkdir(parents=True)
    (root / "excel").mkdir()
    (root / "i18n").mkdir()
    (root / "cache").mkdir()
    (root / "config" / "global.yaml").write_text(
        yaml.safe_dump(
            {
                "primary_lang": "zh",
                "secondary_langs": ["en"],
                "schemas_dir": "config/schemas",
                "excel_dir": "excel",
                "output_dir": "output",
                "cache_dir": "cache",
                "i18n_dir": "i18n",
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    (root / "config" / "schemas" / "Item.yaml").write_text(
        yaml.safe_dump(
            {
                "table": "Item",
                "primary": "Id",
                "fields": [
                    {"name": "Id", "type": "int32"},
                    {"name": "Name", "type": "string", "i18n": True},
                    {"name": "Price", "type": "float"},
                ],
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    wb = Workbook()
    ws = wb.active
    ws.append(["id", "name", "price"])
    ws.append(["主键", "名称", "价格"])
    ws.append([1001, "铁剑", "abc"])  # Price coerce 失败
    ws.append([1002, "魔杖", 200.0])
    wb.save(root / "excel" / "item.xlsx")


def test_reader_issues_merged_without_duplicate_report(tmp_path: Path) -> None:
    """coerce 失败只报一条：reader issue 替换 validate_table 同位置输出。"""
    _build_project(tmp_path)
    ws = Workspace.load(tmp_path)

    pv = parse_and_validate(ws, ["Item"], CacheState(), ws.resolve("excel_dir"))

    assert len(pv.errors) == 1
    assert len(pv.parsed_issues["Item"]) == 1
    issue = pv.errors[0]
    assert issue.field == "Price"
    assert issue.excel_row == 3
    assert issue.value == "abc"
    assert issue.render() == (
        "[Item.xlsx] Excel 第3行 · 列C (Price) · 当前值 'abc' → "
        "期望数值类型，实际值为 'abc'（str）"
    )
