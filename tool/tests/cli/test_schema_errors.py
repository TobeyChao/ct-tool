"""CLI 配置/schema 加载错误路径：友好提示而非 Python traceback。"""

from __future__ import annotations

from pathlib import Path

import yaml
from typer.testing import CliRunner

from ct.cli import app

runner = CliRunner()


def _setup(root: Path, schema_bodies: dict[str, str] | None = None) -> None:
    (root / "config" / "schemas").mkdir(parents=True)
    (root / "excel").mkdir()
    (root / "i18n").mkdir()
    (root / "cache").mkdir()
    (root / "config" / "global.yaml").write_text(
        yaml.safe_dump({"primary_lang": "zh"}), encoding="utf-8"
    )
    for name, body in (schema_bodies or {}).items():
        (root / "config" / "schemas" / f"{name}.yaml").write_text(body, encoding="utf-8")


def test_missing_config_file_reports_error(tmp_path: Path) -> None:
    (tmp_path / "config").mkdir()
    result = runner.invoke(app, ["validate", "--root", str(tmp_path)])
    assert result.exit_code != 0
    assert "Traceback" not in result.output
    assert "[error] 配置文件不存在" in result.output


def test_invalid_table_name_reports_error(tmp_path: Path) -> None:
    _setup(
        tmp_path,
        {
            "Item": (
                "table: item\n"
                "primary: Id\n"
                "fields:\n  - {name: Id, type: int32}\n"
            )
        },
    )
    result = runner.invoke(app, ["validate", "--root", str(tmp_path)])
    assert result.exit_code != 0
    assert "Traceback" not in result.output
    assert "[error]" in result.output
    assert "首字符必须大写" in result.output


def test_duplicate_table_name_reports_error(tmp_path: Path) -> None:
    body = (
        "table: Item\n"
        "primary: Id\n"
        "fields:\n  - {name: Id, type: int32}\n"
    )
    _setup(tmp_path, {"Item.yaml": body, "ItemDup.yaml": body})
    result = runner.invoke(app, ["validate", "--root", str(tmp_path)])
    assert result.exit_code != 0
    assert "Traceback" not in result.output
    assert "[error]" in result.output
    assert "重复" in result.output


def test_circular_ref_reports_error(tmp_path: Path) -> None:
    _setup(
        tmp_path,
        {
            "A.yaml": (
                "table: A\nprimary: Id\nfields:\n"
                "  - {name: Id, type: int32}\n"
                "  - {name: BId, type: int32, ref: B.Id}\n"
            ),
            "B.yaml": (
                "table: B\nprimary: Id\nfields:\n"
                "  - {name: Id, type: int32}\n"
                "  - {name: AId, type: int32, ref: A.Id}\n"
            ),
        },
    )
    result = runner.invoke(app, ["validate", "--root", str(tmp_path)])
    assert result.exit_code != 0
    assert "Traceback" not in result.output
    assert "[error]" in result.output
    assert "循环引用" in result.output


def test_yaml_syntax_error_reports_error(tmp_path: Path) -> None:
    _setup(tmp_path, {"Broken.yaml": "table: Item\n  bad indent\n"})
    result = runner.invoke(app, ["validate", "--root", str(tmp_path)])
    assert result.exit_code != 0
    assert "Traceback" not in result.output
    assert "[error]" in result.output
    assert "加载 schema 失败" in result.output


def test_string_primary_key_reports_error_on_validate(tmp_path: Path) -> None:
    """主键类型约束：string 主键在 schema 加载期被拒绝（不再导出中段崩溃）。"""
    _setup(
        tmp_path,
        {
            "Item.yaml": (
                "table: Item\n"
                "primary: Code\n"
                "fields:\n  - {name: Code, type: string}\n"
            )
        },
    )
    result = runner.invoke(app, ["validate", "--root", str(tmp_path)])
    assert result.exit_code != 0
    assert "Traceback" not in result.output
    assert "[error]" in result.output
    assert "主键" in result.output
    assert "string" in result.output


def test_string_primary_key_reports_error_on_export(tmp_path: Path) -> None:
    """原崩溃路径：string 主键 + ct export 现在是加载期友好报错。"""
    _setup(
        tmp_path,
        {
            "Item.yaml": (
                "table: Item\n"
                "primary: Code\n"
                "fields:\n  - {name: Code, type: string}\n"
            )
        },
    )
    result = runner.invoke(app, ["export", "--all", "--root", str(tmp_path)])
    assert result.exit_code != 0
    assert "Traceback" not in result.output
    assert "[error]" in result.output
    assert "主键" in result.output


def test_int64_primary_key_is_accepted(tmp_path: Path) -> None:
    """int64 主键与 int32 一样合法。"""
    _setup(
        tmp_path,
        {
            "Item.yaml": (
                "table: Item\n"
                "primary: Id\n"
                "fields:\n  - {name: Id, type: int64}\n"
            )
        },
    )
    result = runner.invoke(app, ["validate", "--root", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "Traceback" not in result.output
