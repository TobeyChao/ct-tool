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
from ct.web.logs import PanelLogHandler, log_buffer
from ct.web.schema_workspace_api import register_schema_workspace_api
from ct.web.task_state import task_state
from ct.web.tasks import canonical_export_task


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
            log_buffer.add("系统", "ERROR", f"API 异常: {e}")
            return err(f"内部错误: {e}", 500)

    return wrapper


def _root(app: Flask) -> Path:
    return Path(app.config["ROOT"]).resolve()


def create_app(
    root: Path | None = None,
) -> Flask:
    # 前端静态资源随包分发：与 app.py 同处 ct/web/static
    static_dir = Path(__file__).resolve().parent / "static"
    app = Flask(__name__, static_folder=str(static_dir), static_url_path="/static")
    app.config["ROOT"] = Path(root or Path(".")).resolve()

    logging.getLogger("ct").addHandler(PanelLogHandler(log_buffer))
    register_schema_workspace_api(app)

    @app.get("/api/tasks")
    @safe
    def tasks():
        return ok(task_state.snapshot())

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
        messages = canonical_i18n_sync(_root(app), table_filter=data.get("table"))
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
        entry = canonical_i18n_save_entry(
            _root(app),
            str(data.get("table", "")),
            str(data.get("lang", "")),
            str(data.get("key", "")),
            str(data.get("text", "")),
            bool(data.get("confirmed", False)),
        )
        return ok(entry)

    @app.post("/api/i18n/compact")
    @safe
    def i18n_compact():
        data = request.get_json(silent=True) or {}
        result = canonical_i18n_compact(
            _root(app),
            table_filter=data.get("table"),
            dry_run=bool(data.get("dry_run", False)),
        )
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
