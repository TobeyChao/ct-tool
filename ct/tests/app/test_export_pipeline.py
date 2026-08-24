"""导出管道测试：取消语义、校验失败、成功提交缓存。"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from openpyxl import Workbook

from ct.app.events import CancelToken
from ct.app.export import ExportPipeline, ExportValidationError
from ct.app.options import ExportOptions
from ct.app.workspace import Workspace
from ct.cache.state import load_cache


def _build_project(
    root: Path,
    *,
    duplicate_pk: bool = False,
    extra_tables: list[str] | None = None,
) -> None:
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
    if duplicate_pk:
        ws.append([1001, "铁剑二号", 200.0])
    wb.save(root / "excel" / "item.xlsx")

    for extra in extra_tables or []:
        extra_schema = {
            "table": extra,
            "primary": "Id",
            "fields": [
                {"name": "Id", "type": "int32"},
                {"name": "Name", "type": "string"},
            ],
        }
        (root / "config" / "schemas" / f"{extra}.yaml").write_text(
            yaml.safe_dump(extra_schema, allow_unicode=True), encoding="utf-8"
        )
        wb2 = Workbook()
        ws2 = wb2.active
        ws2.append(["id", "name"])
        ws2.append(["主键", "名称"])
        ws2.append([1, "A"])
        wb2.save(root / "excel" / f"{extra}.xlsx")


class _RecordingReporter:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self.steps: list[str] = []

    def step_started(self, step: str) -> None:
        self.steps.append(step)

    def step_finished(self, step: str) -> None:
        pass

    def log(self, line: str, *, err: bool = False) -> None:
        self.lines.append(line)


class _CancelAfterFirstJson(_RecordingReporter):
    """JsonStep 处理完第一张表后触发取消（用于中途取消语义测试）。"""

    def __init__(self, cancel: CancelToken) -> None:
        super().__init__()
        self._cancel = cancel
        self._json_logged = False

    def log(self, line: str, *, err: bool = False) -> None:
        super().log(line, err=err)
        if line.startswith("[json]") and not self._json_logged:
            self._json_logged = True
            self._cancel.cancel()


def test_cancelled_export_does_not_commit_cache(tmp_path: Path) -> None:
    _build_project(tmp_path)
    ws = Workspace.load(tmp_path)
    cache = load_cache(ws.resolve("cache_dir"))
    cancel = CancelToken()
    cancel.cancel()

    result = ExportPipeline().run(
        ws, ExportOptions(all_tables=True), cache, ws.order,
        _RecordingReporter(), cancel,
    )

    assert result.cancelled
    assert not (ws.resolve("cache_dir") / "state.json").exists()


def test_export_validation_error_is_raised(tmp_path: Path) -> None:
    _build_project(tmp_path, duplicate_pk=True)
    ws = Workspace.load(tmp_path)
    cache = load_cache(ws.resolve("cache_dir"))

    with pytest.raises(ExportValidationError) as exc_info:
        ExportPipeline().run(
            ws, ExportOptions(all_tables=True), cache, ws.order,
            _RecordingReporter(), CancelToken(),
        )

    assert exc_info.value.issues
    assert "主键值 1001 重复" in exc_info.value.issues[0].render()


def test_successful_export_commits_cache_and_bundles(tmp_path: Path) -> None:
    _build_project(tmp_path)
    ws = Workspace.load(tmp_path)
    cache = load_cache(ws.resolve("cache_dir"))
    reporter = _RecordingReporter()

    result = ExportPipeline().run(
        ws, ExportOptions(all_tables=True), cache, ws.order,
        reporter, CancelToken(),
    )

    assert not result.cancelled
    assert (ws.resolve("cache_dir") / "state.json").exists()
    assert any("data_zh.bin" in p.name for p in result.bundles_written)
    assert any(line.startswith("[parse] Item") for line in reporter.lines)
    assert any(line.startswith("[bundle]") for line in reporter.lines)


def test_cancelled_mid_export_reports_actual_exported_tables(tmp_path: Path) -> None:
    _build_project(tmp_path, extra_tables=["Quest"])
    ws = Workspace.load(tmp_path)
    cache = load_cache(ws.resolve("cache_dir"))
    cancel = CancelToken()
    reporter = _CancelAfterFirstJson(cancel)

    result = ExportPipeline().run(
        ws, ExportOptions(all_tables=True), cache, ws.order,
        reporter, cancel,
    )

    assert result.cancelled
    assert result.tables_exported == 1
    assert not (ws.resolve("cache_dir") / "state.json").exists()
