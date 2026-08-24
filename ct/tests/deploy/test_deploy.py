"""deploy 与 export 的集成行为：自动部署、无变化部署、独立命令、--for-build、失败语义。"""

from __future__ import annotations

from pathlib import Path

import yaml
from openpyxl import Workbook
from typer.testing import CliRunner

from ct.cli import app

runner = CliRunner()


def _build_project(root: Path, unity: Path | None = None) -> None:
    """最小项目：Item 表（i18n=Name），可配 deploy，不依赖 flatc。"""
    (root / "config" / "schemas").mkdir(parents=True)
    (root / "excel").mkdir()
    (root / "i18n").mkdir()
    (root / "cache").mkdir()

    cfg = {
        "primary_lang": "zh",
        "secondary_langs": ["en"],
        "schemas_dir": "config/schemas",
        "excel_dir": "excel",
        "output_dir": "output",
        "cache_dir": "cache",
        "i18n_dir": "i18n",
    }
    if unity is not None:
        cfg["deploy"] = {
            "enabled": True,
            "unity_project": str(unity),
            "targets": [
                {"source": "output/binary", "dest": "Assets/Content/Config"},
                {"source": "output/generated/csharp", "dest": "Assets/Scripts/Config/Gen"},
            ],
            "build_targets": [
                {"source": "output/binary", "dest": "Assets/StreamingAssets/Config"},
            ],
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
    (root / "config" / "schemas" / "Item.yaml").write_text(
        yaml.safe_dump(schema, allow_unicode=True), encoding="utf-8"
    )
    wb = Workbook()
    ws = wb.active
    ws.append(["id", "name", "price"])
    ws.append(["主键", "名称", "价格"])
    ws.append([1001, "铁剑", 100.0])
    wb.save(root / "excel" / "item.xlsx")


def test_export_deploys_to_unity(tmp_path: Path) -> None:
    root, unity = tmp_path / "gd", tmp_path / "unity"
    _build_project(root, unity)

    result = runner.invoke(app, ["export", "--all", "--root", str(root)])
    assert result.exit_code == 0, result.output

    assert (unity / "Assets/Content/Config/data_zh.bin").exists()
    assert (unity / "Assets/Scripts/Config/Gen/ItemAccessor.cs").exists()
    # 常规导出不带构建目标
    assert not (unity / "Assets/StreamingAssets/Config").exists()


def test_export_without_deploy_config_skips(tmp_path: Path) -> None:
    root = tmp_path / "gd"
    _build_project(root)

    result = runner.invoke(app, ["export", "--all", "--root", str(root)])
    assert result.exit_code == 0, result.output
    assert "[deploy] 未配置或未启用，跳过" in result.output


def test_no_changes_still_deploys(tmp_path: Path) -> None:
    root, unity = tmp_path / "gd", tmp_path / "unity"
    _build_project(root, unity)

    first = runner.invoke(app, ["export", "--all", "--root", str(root)])
    assert first.exit_code == 0, first.output
    target = unity / "Assets/Content/Config/data_zh.bin"
    assert target.exists()
    target.unlink()

    second = runner.invoke(app, ["export", "--root", str(root)])
    assert second.exit_code == 0, second.output
    assert "所有表均无变化，仅部署" in second.output
    assert target.exists()


def test_deploy_command_only_deploys(tmp_path: Path) -> None:
    root, unity = tmp_path / "gd", tmp_path / "unity"
    _build_project(root, unity)

    # 先导一次产生产物
    first = runner.invoke(app, ["export", "--all", "--root", str(root)])
    assert first.exit_code == 0, first.output
    target = unity / "Assets/Content/Config/data_zh.bin"
    target.unlink()

    # 只部署不导出：产物已在 output，直接补齐目标
    result = runner.invoke(app, ["deploy", "--root", str(root)])
    assert result.exit_code == 0, result.output
    assert target.exists()


def test_deploy_for_build_adds_streaming(tmp_path: Path) -> None:
    root, unity = tmp_path / "gd", tmp_path / "unity"
    _build_project(root, unity)

    result = runner.invoke(app, ["export", "--all", "--for-build", "--root", str(root)])
    assert result.exit_code == 0, result.output
    assert (unity / "Assets/StreamingAssets/Config/data_zh.bin").exists()


def test_deploy_failure_fails_export(tmp_path: Path) -> None:
    root, unity = tmp_path / "gd", tmp_path / "unity"
    _build_project(root, unity)
    # source 指向不存在的产物目录 → 部署失败
    cfg_path = root / "config" / "global.yaml"
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    cfg["deploy"]["targets"] = [{"source": "output/nope", "dest": "Assets/Nope"}]
    cfg_path.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")

    result = runner.invoke(app, ["export", "--all", "--root", str(root)])
    assert result.exit_code != 0
    assert "[deploy error]" in result.output
    # 部署失败不提交缓存
    assert not (root / "cache" / "state.json").exists()
