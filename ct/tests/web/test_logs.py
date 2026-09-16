"""面板日志接线：模块归类、级别归一化、handler 幂等、前后端分类一致。

日志页的分类按钮曾出现「有按钮没人产出」的死分类（i18n / 模板），这里的
测试同时守住写入侧（各流程真的写了对应模块）与两份模块列表的一致性。
"""

from __future__ import annotations

import json
import logging
import re
import shutil
from pathlib import Path

import pytest

from ct.web.app import create_app
from ct.web.logs import (
    LEVEL_ERROR,
    LEVEL_INFO,
    LEVEL_WARN,
    MODULE_EXPORT,
    MODULE_I18N,
    MODULE_SYSTEM,
    MODULE_TEMPLATE,
    MODULE_VALIDATE,
    PANEL_MODULES,
    log_buffer,
    module_for_logger,
    normalize_level,
)

CT_ROOT = Path(__file__).parents[2]
FIXTURE = CT_ROOT / "tests/fixtures/repository_cutover/workspace"
LOGS_JS = CT_ROOT / "src/ct/web/static/js/modules/logs.js"


@pytest.fixture
def isolated_log_buffer():
    """面板缓冲是模块级共享状态：先清空隔离，测试后原样恢复。

    只恢复不清空的话，同一进程里先跑过的导出任务会留下 导出 记录，
    「分类不串味」这类全等断言就变成对别的测试的断言。
    """
    saved = list(log_buffer._records)
    with log_buffer._lock:
        log_buffer._records.clear()
    try:
        yield log_buffer
    finally:
        with log_buffer._lock:
            log_buffer._records.clear()
            log_buffer._records.extend(saved)


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    for section in ("config", "excel", "i18n"):
        shutil.copytree(FIXTURE / section, root / section)
    return root


def _client(workspace: Path):
    return create_app(workspace).test_client()


def _rows(module: str) -> list[dict]:
    return log_buffer.snapshot(module)


# ------------------------------------------------------------ 分类与级别契约


@pytest.mark.parametrize(
    ("logger_name", "module"),
    [
        ("ct.web.i18n", MODULE_I18N),
        ("ct.web.template", MODULE_TEMPLATE),
        ("ct.app.exporting.build", MODULE_EXPORT),
        ("ct.validate.gate", MODULE_VALIDATE),
        ("ct.web.app", MODULE_SYSTEM),
        ("", MODULE_SYSTEM),
    ],
)
def test_module_for_logger_maps_every_panel_module(logger_name: str, module: str) -> None:
    assert module_for_logger(logger_name) == module


@pytest.mark.parametrize(
    ("levelname", "expected"),
    [
        ("INFO", LEVEL_INFO),
        ("WARNING", LEVEL_WARN),
        ("WARN", LEVEL_WARN),
        ("ERROR", LEVEL_ERROR),
        ("CRITICAL", LEVEL_ERROR),
        ("", LEVEL_INFO),
    ],
)
def test_level_names_are_normalized(levelname: str, expected: str) -> None:
    assert normalize_level(levelname) == expected


def test_buffer_normalizes_levels_on_write(isolated_log_buffer) -> None:
    """显式写入也归一化：stdlib 的 WARNING 不会绕过前端的 WARN 筛选。"""
    log_buffer.add(MODULE_EXPORT, "WARNING", "归一化探针")
    assert [row["level"] for row in _rows(MODULE_EXPORT)] == [LEVEL_WARN]


def test_frontend_module_pills_match_backend_modules() -> None:
    """分类按钮与 PANEL_MODULES 必须一一对应，否则又会出现死分类。"""
    text = LOGS_JS.read_text(encoding="utf-8")
    match = re.search(r"const MODULES = \[(.*?)\];", text, re.S)
    assert match, "logs.js 中找不到 MODULES 列表"
    frontend_modules = json.loads("[" + match.group(1) + "]")
    assert frontend_modules == ["all", *PANEL_MODULES]


# ------------------------------------------------------- logger → 面板缓冲


def test_ct_logger_records_reach_the_panel_exactly_once(
    isolated_log_buffer, workspace: Path
) -> None:
    """重复 create_app 不得重复挂 handler（否则每条日志会被转发 N 次）。"""
    create_app(workspace)
    create_app(workspace)
    logger = logging.getLogger("ct.web.i18n")
    before = len(_rows("all"))
    logger.info("分类探针")
    logger.warning("警告探针")
    logger.debug("调试探针")  # DEBUG 是 CLI --verbose 的逃生门，不进面板

    rows = log_buffer.snapshot()[before:]
    assert [(row["module"], row["level"], row["message"]) for row in rows] == [
        (MODULE_I18N, LEVEL_INFO, "分类探针"),
        (MODULE_I18N, LEVEL_WARN, "警告探针"),
    ]


# ------------------------------------------------------------ i18n 流程接线


def test_i18n_sync_entry_and_compact_write_panel_logs(
    isolated_log_buffer, workspace: Path
) -> None:
    client = _client(workspace)

    resp = client.post("/api/i18n/sync", json={"table": "Item"})
    assert resp.status_code == 200, resp.get_json()

    entries = json.loads((workspace / "i18n/en/Item.json").read_text(encoding="utf-8"))
    assert entries, "同步后 en/Item.json 应有条目"
    key = sorted(entries)[0]

    saved = client.post(
        "/api/i18n/entry",
        json={"table": "Item", "lang": "en", "key": key, "text": "Iron Sword", "confirmed": True},
    )
    assert saved.status_code == 200, saved.get_json()
    blank = client.post(
        "/api/i18n/entry",
        json={"table": "Item", "lang": "en", "key": key, "text": "", "confirmed": True},
    )
    assert blank.status_code == 200, blank.get_json()
    preview = client.post("/api/i18n/compact", json={"table": "Item", "dry_run": True})
    assert preview.status_code == 200, preview.get_json()

    rows = _rows(MODULE_I18N)
    messages = [row["message"] for row in rows]
    assert any("同步翻译骨架：Item" in message for message in messages)
    assert any("翻译已保存：Item/en/" in message and "已确认" in message for message in messages)
    assert any("翻译未填写内容：Item/en/" in message for message in messages)
    assert any("翻译整理预览：Item" in message for message in messages)
    assert LEVEL_WARN in {row["level"] for row in rows}
    # i18n 流程不往别的模块写：分类之间不串味
    assert _rows(MODULE_SYSTEM) == []
    assert _rows(MODULE_EXPORT) == []


def test_i18n_failures_stay_out_of_the_panel(isolated_log_buffer, workspace: Path) -> None:
    """业务错误（400/404）由页面提示，不该伪装成运行日志。"""
    client = _client(workspace)
    resp = client.post(
        "/api/i18n/entry",
        json={"table": "Item", "lang": "en", "key": "999.Name", "text": "x", "confirmed": True},
    )
    assert resp.status_code == 400, resp.get_json()
    assert _rows(MODULE_I18N) == []


# ------------------------------------------------------------- 模板流程接线


def test_template_flow_writes_template_module(isolated_log_buffer, workspace: Path) -> None:
    client = _client(workspace)

    ok_resp = client.post("/api/schema-workspace/gen-template", json={"table": "Item"})
    assert ok_resp.status_code == 200, ok_resp.get_json()
    missing = client.post("/api/schema-workspace/gen-template", json={"table": "Missing"})
    assert missing.status_code == 404, missing.get_json()

    rows = _rows(MODULE_TEMPLATE)
    assert [(row["level"], row["message"]) for row in rows] == [
        (LEVEL_INFO, "生成模板：Item（1 张表）"),
        (LEVEL_ERROR, "生成模板失败：未找到表 Missing"),
    ]
    assert _rows(MODULE_SYSTEM) == []
