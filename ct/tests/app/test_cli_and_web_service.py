"""适配器接线：CLI 的输出顺序与友好失败、Web 恒不部署（task 5.3/5.4）。"""

from __future__ import annotations

import io
import time
from contextlib import contextmanager
from pathlib import Path

import pytest
from openpyxl import Workbook
from typer.testing import CliRunner

from _helpers import build_project
from ct.cli import app
from ct.storage.workspace_lock import WorkspaceLock


def _project(tmp_path: Path, tables: tuple[str, ...] = ("Item",)) -> Path:
    root = build_project(
        tmp_path / "gd",
        schemas=[
            {
                "table": name,
                "primary": "Id",
                "fields": [
                    {"name": "Id", "type": "int32"},
                    {"name": "Name", "type": "string", "i18n": True},
                ],
            }
            for name in tables
        ],
    )
    from _helpers import make_workbook

    for name in tables:
        make_workbook(root, name, [[1, "剑"]])
    return root


def _combined(result) -> str:
    return (getattr(result, "stdout", "") or "") + (getattr(result, "stderr", "") or "")


def _deploy_config(root: Path) -> None:
    (root / "config" / "global.yaml").write_text(
        "primary_lang: zh\nsecondary_langs: [en]\n"
        "deploy:\n  enabled: true\n  unity_project: unity\n"
        "  targets:\n    - {source: output/json, dest: Assets/Config}\n",
        encoding="utf-8",
    )


# ------------------------------------------------------------------ CLI (5.3)


def test_cli_export_prints_local_done_then_deploy_result(
    tmp_path: Path, monkeypatch
) -> None:
    root = _project(tmp_path)
    monkeypatch.setattr("ct.cli.deploy", lambda *args, **kwargs: 3)

    result = CliRunner().invoke(app, ["export", "--root", str(root)])
    output = _combined(result)

    assert result.exit_code == 0, output
    assert "导出完成: 1 张表" in output
    assert "[deploy] 完成：3 个文件已同步" in output
    assert output.index("导出完成") < output.index("[deploy]"), "输出顺序必须是先导出后部署"
    assert (root / "cache" / "state.json").is_file()


def test_cli_export_for_build_reaches_the_deployer(
    tmp_path: Path, monkeypatch
) -> None:
    root = _project(tmp_path)
    seen: list[bool] = []

    def spy(config, for_build, reporter):
        seen.append(for_build)
        return 0

    monkeypatch.setattr("ct.cli.deploy", spy)

    result = CliRunner().invoke(app, ["export", "--for-build", "--root", str(root)])

    assert result.exit_code == 0, _combined(result)
    assert seen == [True]
    assert "[deploy] 无文件变更" in _combined(result)


def test_cli_export_busy_exits_nonzero(tmp_path: Path) -> None:
    root = _project(tmp_path)
    with WorkspaceLock(root):
        result = CliRunner().invoke(app, ["export", "--root", str(root)])
    output = _combined(result)
    assert result.exit_code == 1
    assert "工作区正在保存、导出或部署" in output


def test_cli_export_unknown_table_exits_nonzero(tmp_path: Path) -> None:
    root = _project(tmp_path)
    ledger = root / "cache" / "state.json"
    ledger_before = ledger.read_bytes() if ledger.exists() else None
    result = CliRunner().invoke(app, ["export", "--table", "Nope", "--root", str(root)])
    output = _combined(result)
    assert result.exit_code == 1
    assert "表 'Nope' 不存在" in output
    assert (ledger.read_bytes() if ledger.exists() else None) == ledger_before


def test_cli_export_unknown_language_exits_nonzero(tmp_path: Path) -> None:
    root = _project(tmp_path)
    result = CliRunner().invoke(app, ["export", "--lang", "zz", "--root", str(root)])
    output = _combined(result)
    assert result.exit_code == 1
    assert "语言 'zz' 不在可导出语言中" in output


def test_cli_export_deploy_failure_exits_nonzero_and_keeps_old_ledger(
    tmp_path: Path, monkeypatch
) -> None:
    root = _project(tmp_path)
    CliRunner().invoke(app, ["export", "--root", str(root)])
    ledger_before = (root / "cache" / "state.json").read_bytes()

    def boom(*args, **kwargs):
        raise OSError("注入：Unity 目标不可写")

    monkeypatch.setattr("ct.cli.deploy", boom)

    result = CliRunner().invoke(app, ["export", "--all", "--root", str(root)])

    assert result.exit_code == 1
    assert (root / "cache" / "state.json").read_bytes() == ledger_before


def test_cli_standalone_deploy_recovers_pending_publication(tmp_path: Path) -> None:
    """`ct deploy` 也会先恢复现场（未配置 deploy 时正常跳过）。"""
    root = _project(tmp_path)
    CliRunner().invoke(app, ["export", "--root", str(root)])

    result = CliRunner().invoke(app, ["deploy", "--root", str(root)])

    assert result.exit_code == 0, _combined(result)
    assert "[deploy] 未配置或未启用，跳过" in _combined(result)


# ------------------------------------------------------------------ Web (5.4)


def _await_task(task, timeout: float = 30.0) -> dict:
    deadline = time.time() + timeout
    state = task.progress()
    while time.time() < deadline:
        state = task.progress()
        if state["status"] != "running":
            return state
        time.sleep(0.02)
    return state


@contextmanager
def _isolated_log_buffer():
    """Web 任务写的是模块级共享日志缓冲。

    这些测试会产生「导出异常」等 ERROR 行，若不还原会污染日志页的浏览器断言
    （它们假设按 ERROR + “导出” 过滤后为空）。这里保存并恢复缓冲内容。
    """
    from ct.web.logs import log_buffer

    saved = list(log_buffer._records)
    try:
        yield
    finally:
        with log_buffer._lock:
            log_buffer._records.clear()
            log_buffer._records.extend(saved)


def test_web_export_task_never_deploys_even_when_configured(
    tmp_path: Path, monkeypatch
) -> None:
    from ct.web.tasks import canonical_export_task

    root = _project(tmp_path)
    _deploy_config(root)
    calls: list[str] = []
    monkeypatch.setattr(
        "ct.export.deploy.deploy", lambda *args, **kwargs: calls.append("deploy") or 0
    )

    canonical_export_task.status = "idle"
    try:
        with _isolated_log_buffer():
            canonical_export_task.start(root, forced=False)
            state = _await_task(canonical_export_task)
    finally:
        canonical_export_task.status = "idle"

    assert state["status"] == "done", state
    assert calls == [], "Web 策略不得部署"
    # Web 仍然提交成功账本（由统一服务完成）
    assert (root / "cache" / "state.json").is_file()
    assert state["tables_exported"] == 1


def test_web_export_task_reports_validation_failure(tmp_path: Path) -> None:
    from ct.web.tasks import canonical_export_task

    root = _project(tmp_path)
    (root / "excel" / "Item.xlsx").unlink()
    ledger = root / "cache" / "state.json"
    ledger_before = ledger.read_bytes() if ledger.exists() else None

    canonical_export_task.status = "idle"
    try:
        with _isolated_log_buffer():
            canonical_export_task.start(root, forced=False)
            state = _await_task(canonical_export_task)
    finally:
        canonical_export_task.status = "idle"

    assert state["status"] == "error", state
    # 失败任务不得推进成功账本（模板生成留下的内容保持原样）
    assert (ledger.read_bytes() if ledger.exists() else None) == ledger_before
