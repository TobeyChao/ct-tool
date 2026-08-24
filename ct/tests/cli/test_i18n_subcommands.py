from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from openpyxl import Workbook
from typer.testing import CliRunner

from ct.cli import app

runner = CliRunner()


def _build_minimal_project(root: Path, *, secondary: list[str] | None = None) -> None:
    """构建一个最小的 ct 项目，含 item 表（带 i18n 字段）。"""
    secondary = secondary or ["en"]

    (root / "config" / "schemas").mkdir(parents=True)
    (root / "excel").mkdir()
    (root / "i18n").mkdir()
    (root / "cache").mkdir()

    cfg = {
        "primary_lang": "zh",
        "secondary_langs": secondary,
        "schemas_dir": "config/schemas",
        "excel_dir": "excel",
        "output_dir": "output",
        "cache_dir": "cache",
        "i18n_dir": "i18n",
    }
    (root / "config" / "global.yaml").write_text(
        yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8"
    )

    schema = {
        "table": "Item",
        "primary": "Id",
        "fields": [
            {"name": "Id", "type": "int32"},
            {"name": "Name", "type": "string", "i18n": True},
            {"name": "Price", "type": "float"},
        ],
    }
    (root / "config" / "schemas" / "item.yaml").write_text(
        yaml.safe_dump(schema, allow_unicode=True), encoding="utf-8"
    )

    # 简易 Excel：表头 2 行（名字+类型合并 / 注释）+ 数据
    wb = Workbook()
    ws = wb.active
    ws.append(["id", "name", "price"])
    ws.append(["主键", "名称", "价格"])
    ws.append([1001, "铁剑", 100.0])
    ws.append([1002, "魔杖", 200.0])
    wb.save(root / "excel" / "item.xlsx")


def test_sync_creates_lang_skeleton(tmp_path: Path) -> None:
    _build_minimal_project(tmp_path, secondary=["en"])
    result = runner.invoke(app, ["i18n", "sync", "--root", str(tmp_path)])
    assert result.exit_code == 0, result.output

    src = tmp_path / "i18n" / "source" / "item.json"
    en = tmp_path / "i18n" / "en" / "item.json"
    assert src.exists()
    assert en.exists()
    src_data = json.loads(src.read_text(encoding="utf-8"))
    en_data = json.loads(en.read_text(encoding="utf-8"))
    assert src_data == {"1001.Name": "铁剑", "1002.Name": "魔杖"}
    assert en_data["1001.Name"]["status"] == "missing"


def test_sync_filter_by_lang(tmp_path: Path) -> None:
    _build_minimal_project(tmp_path, secondary=["en", "ja"])
    result = runner.invoke(
        app, ["i18n", "sync", "--lang", "en", "--root", str(tmp_path)]
    )
    assert result.exit_code == 0, result.output
    assert (tmp_path / "i18n" / "en" / "item.json").exists()
    assert not (tmp_path / "i18n" / "ja").exists()


def test_sync_filter_by_table(tmp_path: Path) -> None:
    _build_minimal_project(tmp_path)
    result = runner.invoke(
        app, ["i18n", "sync", "--table", "Item", "--root", str(tmp_path)]
    )
    assert result.exit_code == 0


def test_sync_filter_unknown_table_fails(tmp_path: Path) -> None:
    _build_minimal_project(tmp_path)
    result = runner.invoke(
        app, ["i18n", "sync", "--table", "nonexistent", "--root", str(tmp_path)]
    )
    assert result.exit_code != 0


def test_status_default_output(tmp_path: Path) -> None:
    _build_minimal_project(tmp_path)
    runner.invoke(app, ["i18n", "sync", "--root", str(tmp_path)])
    result = runner.invoke(app, ["i18n", "status", "--root", str(tmp_path)])
    assert result.exit_code == 0
    assert "[en]" in result.output
    assert "missing" in result.output


def test_status_json_output_is_valid(tmp_path: Path) -> None:
    _build_minimal_project(tmp_path)
    runner.invoke(app, ["i18n", "sync", "--root", str(tmp_path)])
    result = runner.invoke(app, ["i18n", "status", "--json", "--root", str(tmp_path)])
    assert result.exit_code == 0
    parsed = json.loads(result.output)
    assert "langs" in parsed
    assert "en" in parsed["langs"]
    assert parsed["langs"]["en"]["missing"] == 2


def test_status_by_table(tmp_path: Path) -> None:
    _build_minimal_project(tmp_path)
    runner.invoke(app, ["i18n", "sync", "--root", str(tmp_path)])
    result = runner.invoke(
        app, ["i18n", "status", "--by-table", "--root", str(tmp_path)]
    )
    assert result.exit_code == 0
    assert "Item" in result.output


def test_compact_dry_run_does_not_write(tmp_path: Path) -> None:
    _build_minimal_project(tmp_path)
    runner.invoke(app, ["i18n", "sync", "--root", str(tmp_path)])

    # 手动给 lang 文件加一条 orphan
    en = tmp_path / "i18n" / "en" / "item.json"
    data = json.loads(en.read_text(encoding="utf-8"))
    data["9999.Name"] = {
        "source": "old",
        "text": "Old",
        "confirmed": True,
        "status": "orphan",
    }
    en.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    result = runner.invoke(
        app, ["i18n", "compact", "--dry-run", "--root", str(tmp_path)]
    )
    assert result.exit_code == 0
    assert "9999.Name" in result.output

    # 文件未被修改
    after = json.loads(en.read_text(encoding="utf-8"))
    assert "9999.Name" in after


def test_compact_removes_orphans(tmp_path: Path) -> None:
    _build_minimal_project(tmp_path)
    runner.invoke(app, ["i18n", "sync", "--root", str(tmp_path)])

    en = tmp_path / "i18n" / "en" / "item.json"
    data = json.loads(en.read_text(encoding="utf-8"))
    data["9999.Name"] = {
        "source": "old",
        "text": "Old",
        "confirmed": True,
        "status": "orphan",
    }
    en.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    result = runner.invoke(app, ["i18n", "compact", "--root", str(tmp_path)])
    assert result.exit_code == 0
    assert "移除 1" in result.output

    after = json.loads(en.read_text(encoding="utf-8"))
    assert "9999.Name" not in after
    assert "1001.Name" in after


def test_compact_no_orphans(tmp_path: Path) -> None:
    _build_minimal_project(tmp_path)
    runner.invoke(app, ["i18n", "sync", "--root", str(tmp_path)])
    result = runner.invoke(app, ["i18n", "compact", "--root", str(tmp_path)])
    assert result.exit_code == 0
    assert "无 orphan" in result.output


def test_compact_invalid_lang_fails(tmp_path: Path) -> None:
    _build_minimal_project(tmp_path)
    result = runner.invoke(
        app, ["i18n", "compact", "--lang", "fr", "--root", str(tmp_path)]
    )
    assert result.exit_code != 0
