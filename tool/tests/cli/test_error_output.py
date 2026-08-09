"""CLI 错误输出测试：实际输出包含 Excel 绝对行号 + 列字母 + 当前值。"""

from __future__ import annotations

from pathlib import Path

import yaml
from openpyxl import Workbook
from typer.testing import CliRunner

from ct.cli import app

runner = CliRunner()


def _build_project_with_duplicate_pk(root: Path) -> None:
    (root / "config" / "schemas").mkdir(parents=True)
    (root / "excel").mkdir()
    (root / "i18n").mkdir()
    (root / "cache").mkdir()
    (root / "config" / "global.yaml").write_text(
        yaml.safe_dump(
            {
                "primary_lang": "zh",
                "secondary_langs": ["en"],
                "flatc_path": "tools/nope",
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
                    {"name": "Price", "type": "float"},
                ],
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    wb = Workbook()
    ws = wb.active
    ws.append(["id", "price"])
    ws.append(["主键", "价格"])
    ws.append([1001, 100.0])
    ws.append([1001, 200.0])
    wb.save(root / "excel" / "item.xlsx")


def test_export_error_output_has_exact_location(tmp_path: Path) -> None:
    _build_project_with_duplicate_pk(tmp_path)
    result = runner.invoke(app, ["export", "--all", "--root", str(tmp_path)])

    assert result.exit_code != 0
    assert "Excel 第4行" in result.output
    assert "列A (Id)" in result.output
    assert "当前值 1001" in result.output
    assert "主键值 1001 重复" in result.output


def test_validate_error_output_has_exact_location(tmp_path: Path) -> None:
    _build_project_with_duplicate_pk(tmp_path)
    result = runner.invoke(app, ["validate", "--root", str(tmp_path)])

    assert result.exit_code != 0
    assert "Excel 第4行" in result.output
    assert "列A (Id)" in result.output
