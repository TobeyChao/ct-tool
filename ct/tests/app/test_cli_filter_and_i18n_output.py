"""CLI 过滤取值与 i18n 输出的规格落地（回归：过滤被静默忽略 / dry-run 落盘 / 输出格式）。

覆盖 2026-09-12 复核发现的五类缺陷：
1. `--table` / `--lang` 指向不存在的取值时静默成功（export / i18n sync / i18n compact /
   i18n status / gen-template）
2. `ct i18n compact --dry-run` 未转发 `dry_run`，**真的删了文件**
3. `ct i18n compact` 把返回的 dict 直接插进输出行
4. `ct i18n status` 无进度条、`--by-table` 无效、`--json` 缺 `langs` 外层
5. `ct i18n sync --verbose` 无输出、完成时无汇总行
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import yaml
from openpyxl import Workbook
from typer.testing import CliRunner

from ct.cli import app

runner = CliRunner()


def _combined(result) -> str:
    """stdout + stderr。

    click 8.4 的 `result.output` 已经包含 stderr（`stdout` 为空、`stderr` 单独可取），
    故不能与 `output` 相加，否则每条 stderr 行会被数两遍。
    """
    streams = (getattr(result, "stdout", "") or "") + (getattr(result, "stderr", "") or "")
    return streams or result.output


def _build_project(root: Path) -> None:
    (root / "config" / "schemas").mkdir(parents=True)
    (root / "excel").mkdir()
    (root / "i18n").mkdir()
    (root / "cache").mkdir()
    cfg = {
        "primary_lang": "zh",
        "secondary_langs": ["en", "ja"],
        "schemas_dir": "config/schemas",
        "excel_dir": "excel",
        "output_dir": "output",
        "cache_dir": "cache",
        "i18n_dir": "i18n",
    }
    (root / "config" / "global.yaml").write_text(
        yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8"
    )
    for table in ("Item", "Plain"):
        fields = [
            {"name": "Id", "type": "int32"},
            {"name": "Name", "type": "string", "i18n": True},
        ] if table == "Item" else [
            {"name": "Id", "type": "int32"},
            {"name": "Count", "type": "int32"},
        ]
        schema = {"table": table, "primary": "Id", "fields": fields}
        (root / "config" / "schemas" / f"{table}.yaml").write_text(
            yaml.safe_dump(schema, allow_unicode=True), encoding="utf-8"
        )
        from _helpers import make_workbook

        rows = [[1, "铁剑"], [2, "木剑"]] if table == "Item" else [[1, 3]]
        make_workbook(root, table, rows)


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "gd"
    _build_project(root)
    return root


def _inject_orphan(root: Path, lang: str, key: str = "999.Name") -> Path:
    path = root / "i18n" / lang / "Item.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data[key] = {"source": "幽灵", "text": "Ghost", "confirmed": True, "status": "translated"}
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


# --------------------------------------------------------------- 1. 过滤取值


def test_export_unknown_language_fails(tmp_path: Path) -> None:
    root = _project(tmp_path)
    result = runner.invoke(app, ["export", "--lang", "zz", "--root", str(root)])
    assert result.exit_code != 0
    assert "语言 'zz' 不在可导出语言中" in _combined(result)
    assert "zh, en, ja" in _combined(result)
    assert not (root / "output" / "binary").exists()


def test_export_unknown_table_fails(tmp_path: Path) -> None:
    root = _project(tmp_path)
    result = runner.invoke(app, ["export", "--table", "Nope", "--root", str(root)])
    assert result.exit_code != 0
    assert "表 'Nope' 不存在" in _combined(result)


def test_gen_template_unknown_table_fails(tmp_path: Path) -> None:
    root = _project(tmp_path)
    result = runner.invoke(app, ["gen-template", "--table", "Nope", "--root", str(root)])
    assert result.exit_code != 0
    assert "表 'Nope' 不存在" in _combined(result)


def test_gen_template_case_mismatch_hints(tmp_path: Path) -> None:
    root = _project(tmp_path)
    result = runner.invoke(app, ["gen-template", "--table", "item", "--root", str(root)])
    assert result.exit_code != 0
    assert "是否想用 'Item'？" in _combined(result)


def test_i18n_sync_unknown_language_writes_nothing(tmp_path: Path) -> None:
    root = _project(tmp_path)
    result = runner.invoke(app, ["i18n", "sync", "--lang", "zz", "--root", str(root)])
    assert result.exit_code != 0
    assert "语言 'zz' 不在 secondary_langs 中" in _combined(result)
    assert not (root / "i18n" / "source").exists()


def test_i18n_sync_table_without_i18n_fields_fails(tmp_path: Path) -> None:
    root = _project(tmp_path)
    result = runner.invoke(app, ["i18n", "sync", "--table", "Plain", "--root", str(root)])
    assert result.exit_code != 0
    assert "表 'Plain' 没有 i18n 字段" in _combined(result)


def test_i18n_status_unknown_language_fails(tmp_path: Path) -> None:
    root = _project(tmp_path)
    runner.invoke(app, ["i18n", "sync", "--root", str(root)])
    result = runner.invoke(app, ["i18n", "status", "--lang", "zz", "--root", str(root)])
    assert result.exit_code != 0
    assert "语言 'zz' 不在 secondary_langs 中" in _combined(result)
    assert "translated" not in result.output


def test_i18n_compact_unknown_language_fails(tmp_path: Path) -> None:
    root = _project(tmp_path)
    runner.invoke(app, ["i18n", "sync", "--root", str(root)])
    path = _inject_orphan(root, "en")
    result = runner.invoke(app, ["i18n", "compact", "--lang", "zz", "--root", str(root)])
    assert result.exit_code != 0
    assert "语言 'zz' 不在 secondary_langs 中" in _combined(result)
    assert "999.Name" in path.read_text(encoding="utf-8")


# --------------------------------------------------------------- 2/5. sync


def test_i18n_sync_language_filter_only_writes_that_language(tmp_path: Path) -> None:
    root = _project(tmp_path)
    runner.invoke(app, ["i18n", "sync", "--root", str(root)])
    (root / "i18n" / "ja" / "Item.json").unlink()

    result = runner.invoke(app, ["i18n", "sync", "--lang", "en", "--root", str(root)])

    assert result.exit_code == 0
    assert not (root / "i18n" / "ja" / "Item.json").exists(), "ja 骨架被 --lang en 重写了"
    assert (root / "i18n" / "en" / "Item.json").exists()
    # source 仍全量刷新（与 --lang 无关）
    assert (root / "i18n" / "source" / "Item.json").exists()


def test_i18n_sync_reports_summary_and_verbose_files(tmp_path: Path) -> None:
    root = _project(tmp_path)
    result = runner.invoke(app, ["i18n", "sync", "--root", str(root)])
    # Item 有 2 行数据 × 1 个 i18n 字段 × 2 个语言 = 4 条新条目
    assert "处理 1 张表 × 2 语言：新增 4、更新 0、stale 0、orphan 0" in _combined(result)

    verbose = runner.invoke(app, ["i18n", "sync", "--verbose", "--root", str(root)])
    text = _combined(verbose)
    assert "写入 i18n/source/Item.json（2 条 source）" in text
    assert "写入 i18n/en/Item.json（新增 0、更新 0、stale 0、orphan 0）" in text


# --------------------------------------------------------------- 3. status


def test_i18n_status_renders_progress_line(tmp_path: Path) -> None:
    root = _project(tmp_path)
    runner.invoke(app, ["i18n", "sync", "--root", str(root)])

    result = runner.invoke(app, ["i18n", "status", "--root", str(root)])

    assert result.exit_code == 0
    assert "[en]  0% [░░░░░░░░░░] 0/2 translated, 2 missing, 0 stale, 0 orphan" in result.output
    assert "[ja]  0% [░░░░░░░░░░] 0/2 translated, 2 missing, 0 stale, 0 orphan" in result.output


def test_i18n_status_progress_line_counts_translated(tmp_path: Path) -> None:
    root = _project(tmp_path)
    runner.invoke(app, ["i18n", "sync", "--root", str(root)])
    path = root / "i18n" / "en" / "Item.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["1.Name"] = {"source": "铁剑", "text": "Iron Sword", "confirmed": True, "status": "translated"}
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    result = runner.invoke(app, ["i18n", "status", "--root", str(root)])

    assert "[en]  50% [█████░░░░░] 1/2 translated, 1 missing, 0 stale, 0 orphan" in result.output


def test_i18n_status_by_table_adds_rows(tmp_path: Path) -> None:
    root = _project(tmp_path)
    runner.invoke(app, ["i18n", "sync", "--root", str(root)])

    default = runner.invoke(app, ["i18n", "status", "--root", str(root)]).output
    by_table = runner.invoke(app, ["i18n", "status", "--by-table", "--root", str(root)]).output

    assert "  Item  " not in default
    assert "[en]  " in by_table
    assert "  Item  0% [░░░░░░░░░░] 0/2 translated" in by_table


def test_i18n_status_json_has_langs_wrapper_and_clean_stdout(tmp_path: Path) -> None:
    root = _project(tmp_path)
    runner.invoke(app, ["i18n", "sync", "--root", str(root)])

    result = runner.invoke(app, ["i18n", "status", "--json", "--root", str(root)])

    payload = json.loads(result.stdout)
    assert set(payload) == {"langs"}
    assert set(payload["langs"]) == {"en", "ja"}
    en = payload["langs"]["en"]
    assert en["total"] == 2 and en["missing"] == 2 and en["orphan"] == 0
    assert en["progress"] == 0.0
    assert en["tables"]["Item"]["missing"] == 2


def test_i18n_status_json_language_filter(tmp_path: Path) -> None:
    root = _project(tmp_path)
    runner.invoke(app, ["i18n", "sync", "--root", str(root)])

    result = runner.invoke(app, ["i18n", "status", "--json", "--lang", "en", "--root", str(root)])

    assert set(json.loads(result.stdout)["langs"]) == {"en"}


# --------------------------------------------------------------- 4. compact


def test_i18n_compact_dry_run_does_not_write(tmp_path: Path) -> None:
    root = _project(tmp_path)
    runner.invoke(app, ["i18n", "sync", "--root", str(root)])
    path = _inject_orphan(root, "en")
    before = path.read_text(encoding="utf-8")

    result = runner.invoke(app, ["i18n", "compact", "--dry-run", "--root", str(root)])

    assert result.exit_code == 0
    assert path.read_text(encoding="utf-8") == before, "dry-run 落盘了"
    assert "[compact] en/Item: 将移除 1 条 orphan" in result.output
    assert "  999.Name" in result.output
    assert "（dry-run，未修改任何文件）" in result.output


def test_i18n_compact_language_filter_and_reporting(tmp_path: Path) -> None:
    root = _project(tmp_path)
    runner.invoke(app, ["i18n", "sync", "--root", str(root)])
    _inject_orphan(root, "en")
    ja_path = _inject_orphan(root, "ja")

    result = runner.invoke(app, ["i18n", "compact", "--lang", "en", "--root", str(root)])

    assert result.exit_code == 0
    assert "[compact] en/Item: 移除 1 条 orphan" in result.output
    assert "[compact] 共 1 条 orphan 已移除" in result.output
    assert "999.Name" not in (root / "i18n" / "en" / "Item.json").read_text(encoding="utf-8")
    assert "999.Name" in ja_path.read_text(encoding="utf-8"), "--lang en 动到了 ja"


def test_i18n_compact_reports_nothing_to_do(tmp_path: Path) -> None:
    root = _project(tmp_path)
    runner.invoke(app, ["i18n", "sync", "--root", str(root)])

    result = runner.invoke(app, ["i18n", "compact", "--root", str(root)])

    assert result.exit_code == 0
    assert "[compact] 无 orphan 条目，无需操作" in result.output
    assert "{" not in result.output, "返回的 dict 又被插进输出行了"


# --------------------------------------------------------------- 6. schema 级错误


def _break_schema(root: Path) -> None:
    """把 Item 主键改成 int64：schema 加载阶段即失败（新规则下最容易踩的错）。"""
    path = root / "config" / "schemas" / "Item.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["fields"][0]["type"] = "int64"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")


def test_validate_reports_schema_error_without_traceback(tmp_path: Path) -> None:
    root = _project(tmp_path)
    _break_schema(root)

    result = runner.invoke(app, ["validate", "--root", str(root)])

    assert result.exit_code != 0
    text = _combined(result)
    assert "主键字段 'Id' 类型必须为 int32" in text
    assert "Traceback" not in text, "策划看到了 Python 堆栈"


def test_status_reports_schema_error_without_traceback(tmp_path: Path) -> None:
    root = _project(tmp_path)
    _break_schema(root)

    result = runner.invoke(app, ["status", "--root", str(root)])

    assert result.exit_code != 0
    text = _combined(result)
    assert "主键字段 'Id' 类型必须为 int32" in text
    assert "Traceback" not in text, "策划看到了 Python 堆栈"


def test_validate_verbose_keeps_traceback_for_developers(tmp_path: Path, caplog) -> None:
    root = _project(tmp_path)
    _break_schema(root)

    # CliRunner 复用进程时 `logging.basicConfig` 是 no-op、stderr 已被捕获，
    # 故直接断言日志记录里带 exc_info（真实运行见 `_friendly_exit` 的 debug 分支）。
    with caplog.at_level(logging.DEBUG, logger="ct"):
        result = runner.invoke(app, ["validate", "--verbose", "--root", str(root)])

    assert result.exit_code != 0
    assert "Traceback" not in _combined(result), "默认不应给策划看堆栈"
    assert [r for r in caplog.records if r.levelno == logging.DEBUG and r.exc_info], (
        "--verbose 应把堆栈写进日志（开发逃生门）"
    )
