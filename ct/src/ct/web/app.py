"""Flask 面板（canonical ）：静态托管 + JSON API，薄封装 ct/app 用例层。"""

from __future__ import annotations

import json
import logging
from functools import wraps
from pathlib import Path
from typing import Any, Callable

from flask import Flask, jsonify, request, send_from_directory

from ct.app.canonical_commands import (
    canonical_i18n_compact,
    canonical_i18n_entries,
    canonical_i18n_save_entry,
    canonical_i18n_status,
    canonical_i18n_sync,
    canonical_i18n_tables,
    canonical_status,
)
from ct.config import load_config
from ct.web.history import load_history
from ct.web.logs import LEVEL_ERROR, MODULE_SYSTEM, attach_panel_handler, log_buffer
from ct.web.schema_workspace_api import register_schema_workspace_api
from ct.web.task_state import task_state
from ct.web.tasks import canonical_export_task

#: 翻译流程的面板日志：模块名由 logger 名（含 ``i18n``）归类到日志页的 i18n 分类。
logger = logging.getLogger("ct.web.i18n")

#: 翻译条目状态（``ct.export.i18n.state``）→ 面板里可读的中文标签。
_I18N_STATUS_LABELS = {
    "translated": "已确认",
    "stale": "待确认",
    "missing": "缺失",
    "orphan": "无主",
}


class PanelError(Exception):
    """带 HTTP 状态码的业务错误。"""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


def ok(data: Any):
    return jsonify({"ok": True, "data": data})


def err(message: str, status: int = 400):
    return jsonify({"ok": False, "error": message}), status


def safe(fn: Callable):
    @wraps(fn)
    def wrapper(*args: Any, **kwargs: Any):
        try:
            return fn(*args, **kwargs)
        except PanelError as e:
            return err(str(e), e.status)
        except FileNotFoundError as e:
            return err(f"文件不存在: {e}", 404)
        except ValueError as e:
            return err(str(e), 400)
        except Exception as e:  # noqa: BLE001
            log_buffer.add(MODULE_SYSTEM, LEVEL_ERROR, f"API 异常: {e}")
            return err(f"内部错误: {e}", 500)

    return wrapper


def _root(app: Flask) -> Path:
    return Path(app.config["ROOT"]).resolve()


def _log_i18n_sync(table: str | None, messages: list[str]) -> None:
    """同步/抽取骨架：逐表消息的最后一条是汇总，取它当日志正文。"""
    scope = table or "全部表"
    summary = messages[-1] if messages else "没有含 i18n 字段的表"
    logger.info("同步翻译骨架：%s · %s", scope, summary)


def _log_i18n_compact(table: str | None, result: dict[str, Any]) -> None:
    scope = table or "全部表"
    removed = int(result.get("total_removed", 0))
    touched = int(result.get("touched", 0))
    if result.get("dry_run"):
        logger.info(
            "翻译整理预览：%s · 待删除 %s 条无主条目（%s 个文件）", scope, removed, touched
        )
    elif removed:
        logger.info(
            "翻译整理完成：%s · 删除 %s 条无主条目（%s 个文件）", scope, removed, touched
        )
    else:
        logger.info("翻译整理：%s · 没有无主条目", scope)


def _log_i18n_entry(table: str, lang: str, key: str, entry: dict[str, Any]) -> None:
    status = _I18N_STATUS_LABELS.get(str(entry.get("status", "")), "未知状态")
    if not str(entry.get("text", "")).strip():
        # 清空译文是有效操作，但结果一定是空缺，值得在日志里留一条 WARN
        logger.warning("翻译未填写内容：%s/%s/%s（%s）", table, lang, key, status)
    else:
        logger.info("翻译已保存：%s/%s/%s（%s）", table, lang, key, status)


def create_app(
    root: Path | None = None,
) -> Flask:
    # 前端静态资源随包分发：与 app.py 同处 ct/web/static
    static_dir = Path(__file__).resolve().parent / "static"
    app = Flask(__name__, static_folder=str(static_dir), static_url_path="/static")
    app.config["ROOT"] = Path(root or Path(".")).resolve()

    attach_panel_handler(logging.getLogger("ct"), log_buffer)
    register_schema_workspace_api(app)

    @app.get("/api/tasks")
    @safe
    def tasks():
        tasks = task_state.snapshot()
        export = canonical_export_task.global_task(_root(app))
        if export:
            tasks.insert(0, export)
        return ok(tasks)

    @app.post("/api/tasks/<task_id>/dismiss")
    @safe
    def dismiss_task(task_id: str):
        """关闭右下角失败卡片：服务端记账，刷新页面不复活。"""
        if task_id != "canonical-export":
            return err(f"未知任务: {task_id}", 404)
        return ok({"dismissed": canonical_export_task.dismiss_global()})

    @app.get("/")
    @safe
    def index():
        return send_from_directory(static_dir, "index.html")

    # ---------------- 工作区 ----------------
    @app.get("/api/workspace")
    @safe
    def workspace():
        root = _root(app)
        cfg = load_config(root)
        report = canonical_status(root)
        return ok(
            {
                "root": str(root),
                "config": {
                    "primary_lang": cfg.primary_lang,
                    "secondary_langs": cfg.secondary_langs,
                    "schema_format": "yaml",
                    "deploy": {
                        "enabled": cfg.deploy.enabled,
                        "unity_project": str(cfg.unity_project_root) if cfg.unity_project_root else "",
                        "targets": [],
                    },
                },
                "status": report,
            }
        )

    # ---------------- 导出 ----------------
    @app.post("/api/export")
    @safe
    def start_export():
        data = request.get_json(silent=True) or {}
        forced = bool(data.get("forced", False))
        try:
            canonical_export_task.start(_root(app), forced)
        except RuntimeError as e:
            return err(str(e), 409)
        return ok(canonical_export_task.progress())

    @app.get("/api/export/progress")
    @safe
    def export_progress():
        return ok(canonical_export_task.progress())

    @app.post("/api/export/cancel")
    @safe
    def cancel_export():
        canonical_export_task.cancel()
        return ok(canonical_export_task.progress())

    # ---------------- 翻译 ----------------
    @app.get("/api/i18n/tables")
    @safe
    def i18n_tables():
        return ok(canonical_i18n_tables(_root(app)))

    @app.get("/api/i18n/status")
    @safe
    def i18n_status():
        return ok(canonical_i18n_status(_root(app)))

    @app.post("/api/i18n/sync")
    @safe
    def i18n_sync():
        data = request.get_json(silent=True) or {}
        table = data.get("table")
        messages = canonical_i18n_sync(_root(app), table_filter=table)
        _log_i18n_sync(table, messages)
        return ok({"synced": messages})

    @app.get("/api/i18n/entries")
    @safe
    def i18n_entries():
        table = request.args.get("table", "")
        lang = request.args.get("lang", "")
        return ok(canonical_i18n_entries(_root(app), table, lang))

    @app.post("/api/i18n/entry")
    @safe
    def i18n_entry_save():
        data = request.get_json(silent=True) or {}
        table = str(data.get("table", ""))
        lang = str(data.get("lang", ""))
        key = str(data.get("key", ""))
        entry = canonical_i18n_save_entry(
            _root(app),
            table,
            lang,
            key,
            str(data.get("text", "")),
            bool(data.get("confirmed", False)),
        )
        _log_i18n_entry(table, lang, key, entry)
        return ok(entry)

    @app.post("/api/i18n/compact")
    @safe
    def i18n_compact():
        data = request.get_json(silent=True) or {}
        table = data.get("table")
        result = canonical_i18n_compact(
            _root(app),
            table_filter=table,
            dry_run=bool(data.get("dry_run", False)),
        )
        _log_i18n_compact(table, result)
        return ok(result)

    # ---------------- 日志与历史 ----------------
    @app.get("/api/logs")
    @safe
    def logs():
        module = request.args.get("module", "all")
        return ok(log_buffer.snapshot(module))

    @app.get("/api/history")
    @safe
    def history():
        return ok(load_history(_root(app) / "cache"))

    return app
