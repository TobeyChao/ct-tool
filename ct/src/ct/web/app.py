"""Flask 面板：静态托管 + JSON API，薄封装 ct/app 用例层。"""

from __future__ import annotations

import json
import logging
from functools import wraps
from pathlib import Path
from typing import Any, Callable

from flask import Flask, jsonify, request, send_from_directory

from ct.app.i18n import read_i18n_rows
from ct.app.status import compute_status as compute_workspace_status
from ct.app.workspace import Workspace
from ct.cache.state import load_cache
from ct.export.i18n.compact import CompactError, compact_i18n
from ct.export.i18n.io import dump_lang_file
from ct.export.i18n.merger import load_translation
from ct.export.i18n.state import (
    compute_status as compute_entry_status,
    sync_lang_table,
)
from ct.export.i18n.status import compute_status_report, render_json
from ct.export.i18n.sync import sync_all
from ct.schema.models import FieldDef
from ct.web.history import load_history
from ct.web.logs import PanelLogHandler, log_buffer
from ct.web.schema_workspace_api import register_schema_workspace_api
from ct.web.tasks import export_task
from ct.web.task_state import task_state


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
        except CompactError as e:
            return err(str(e), 400)
        except FileNotFoundError as e:
            return err(f"文件不存在: {e}", 404)
        except ValueError as e:
            return err(str(e), 400)
        except Exception as e:  # noqa: BLE001
            log_buffer.add("系统", "ERROR", f"API 异常: {e}")
            return err(f"内部错误: {e}", 500)

    return wrapper


def _load_ws(app: Flask) -> Workspace:
    root: Path = app.config["ROOT"]
    try:
        return Workspace.load(root)
    except FileNotFoundError as e:
        raise PanelError(
            f"工作区不可用：{e}。请确认 --root 指向包含 config/global.yaml 的 gd/ 目录",
            400,
        ) from e


def _deploy_summary(ws) -> dict:
    """deploy 配置摘要：绝对路径，供前端展示。"""
    cfg = ws.config
    unity = cfg.unity_project_root
    targets = []
    if unity is not None:
        targets = [
            {"source": t.source, "dest": str(unity / t.dest)}
            for t in cfg.deploy.targets
        ]
    return {
        "enabled": cfg.deploy.enabled,
        "unity_project": str(unity) if unity else "",
        "targets": targets,
    }


def _looks_canonical(root: Path) -> bool:
    """Positive evidence of the canonical v4 workspace format."""
    import yaml

    types_dir = root / "config" / "types"
    if types_dir.exists() and any(types_dir.glob("*.yaml")):
        return True
    schemas_dir = root / "config" / "schemas"
    if not schemas_dir.exists():
        return False
    for path in schemas_dir.glob("*.yaml"):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except OSError:
            continue
        for field in data.get("fields", []):
            type_text = field.get("type", "") if isinstance(field, dict) else ""
            if isinstance(type_text, str) and (
                type_text.startswith("vector<") or ":" in type_text
            ):
                return True
    return False


def create_app(
    root: Path | None = None,
) -> Flask:
    # 前端静态资源随包分发：与 app.py 同处 ct/web/static
    static_dir = Path(__file__).resolve().parent / "static"
    app = Flask(__name__, static_folder=str(static_dir), static_url_path="/static")
    app.config["ROOT"] = Path(root or Path(".")).resolve()

    logging.getLogger("ct").addHandler(PanelLogHandler(log_buffer))
    register_schema_workspace_api(app)
    from ct.web.schema_routes import schema_routes
    app.register_blueprint(schema_routes)

    @app.get("/api/tasks")
    @safe
    def tasks():
        return ok(task_state.snapshot())

    @app.get("/")
    @safe
    def index():
        return send_from_directory(static_dir, "v4/index.html")

    # ---------------- 工作区 ----------------
    @app.get("/api/workspace")
    @safe
    def workspace():
        if _looks_canonical(app.config["ROOT"]):
            from ct.app.canonical_commands import canonical_status
            from ct.config import load_config

            root = app.config["ROOT"]
            cfg = load_config(root)
            report = canonical_status(root)
            return ok(
                {
                    "root": str(root),
                    "config": {
                        "primary_lang": cfg.primary_lang,
                        "secondary_langs": cfg.secondary_langs,
                        "schema_format": "yaml",
                        "deploy": {"enabled": False, "unity_project": "", "targets": []},
                    },
                    "status": report,
                }
            )
        ws = _load_ws(app)
        cache = load_cache(ws.resolve("cache_dir"))
        report = compute_workspace_status(ws, cache)
        return ok(
            {
                "root": str(ws.root),
                "config": {
                    "primary_lang": ws.config.primary_lang,
                    "secondary_langs": ws.config.secondary_langs,
                    "schema_format": ws.config.schema_format,
                    "deploy": _deploy_summary(ws),
                },
                "status": {
                    "changed": report.changed,
                    "drifted": report.drifted,
                    "untracked": report.untracked,
                    "missing": report.missing,
                },
            }
        )

    # ---------------- 导出 ----------------
    @app.post("/api/export")
    @safe
    def start_export():
        if _looks_canonical(app.config["ROOT"]):
            from ct.app.canonical_export import run_canonical_export

            result = run_canonical_export(app.config["ROOT"])
            log_buffer.add("导出", "INFO", f"[v4] 导出完成: {result['tables']} 张表")
            return ok({"running": False, "total": result["tables"], "current": result["tables"], "message": "导出完成（v4）"})
        data = request.get_json(silent=True) or {}
        forced = bool(data.get("forced", False))
        try:
            export_task.start(app.config["ROOT"], forced)
        except RuntimeError as e:
            return err(str(e), 409)
        return ok(export_task.progress())

    @app.get("/api/export/progress")
    @safe
    def export_progress():
        return ok(export_task.progress())

    @app.post("/api/export/cancel")
    @safe
    def cancel_export():
        export_task.cancel()
        return ok(export_task.progress())

    # ---------------- 翻译 ----------------
    @app.get("/api/i18n/tables")
    @safe
    def i18n_tables():
        ws = _load_ws(app)
        return ok(
            [
                {
                    "table": s.table,
                    "field_count": len(s.fields),
                    "i18n_count": len(s.i18n_fields),
                    "has_i18n": s.has_i18n,
                }
                for s in ws.schemas
            ]
        )

    @app.get("/api/i18n/entries")
    @safe
    def i18n_entries():
        ws = _load_ws(app)
        table = request.args.get("table", "")
        lang = request.args.get("lang", "")
        if table not in ws.schema_map:
            raise PanelError(f"表 '{table}' 不存在")
        if lang not in ws.config.secondary_langs:
            raise PanelError(f"语言 '{lang}' 不在 secondary_langs 中")
        schema = ws.schema_map[table]
        i18n_dir = ws.resolve("i18n_dir")
        source_path = i18n_dir / "source" / f"{table}.json"
        source = (
            json.loads(source_path.read_text(encoding="utf-8"))
            if source_path.exists()
            else {}
        )
        computed = sync_lang_table(source, load_translation(i18n_dir, lang, table))
        entries = []
        for key, entry in computed.items():
            id_part, _, field = key.partition(".")
            entries.append(
                {
                    "key": key,
                    "id": id_part,
                    "field": field,
                    "source": entry.get("source", ""),
                    "text": entry.get("text", ""),
                    "confirmed": bool(entry.get("confirmed", False)),
                    "status": entry.get("status", "missing"),
                }
            )
        return ok(entries)

    @app.post("/api/i18n/entry")
    @safe
    def i18n_entry_save():
        ws = _load_ws(app)
        data = request.get_json(silent=True) or {}
        table = str(data.get("table", ""))
        lang = str(data.get("lang", ""))
        key = str(data.get("key", ""))
        if table not in ws.schema_map:
            raise PanelError(f"表 '{table}' 不存在")
        if lang not in ws.config.secondary_langs:
            raise PanelError(f"语言 '{lang}' 不在 secondary_langs 中")
        schema = ws.schema_map[table]
        i18n_dir = ws.resolve("i18n_dir")
        entries = load_translation(i18n_dir, lang, table)
        if key not in entries:
            raise PanelError(f"条目 {key} 不存在，请先同步骨架")
        entries[key]["text"] = str(data.get("text", ""))
        entries[key]["confirmed"] = bool(data.get("confirmed", False))
        entries[key]["status"] = compute_entry_status(
            entries[key]["text"], entries[key]["confirmed"], in_source=True
        ).value
        field_order = [f.name for f in schema.i18n_fields]
        dump_lang_file(entries, i18n_dir / lang / f"{table}.json", field_order)
        return ok(entries[key])

    @app.post("/api/i18n/sync")
    @safe
    def i18n_sync():
        if _looks_canonical(app.config["ROOT"]):
            from ct.app.canonical_commands import canonical_i18n_sync

            data = request.get_json(silent=True) or {}
            messages = canonical_i18n_sync(app.config["ROOT"], table_filter=data.get("table"))
            return ok({"synced": messages})
        ws = _load_ws(app)
        data = request.get_json(silent=True) or {}
        table = str(data.get("table", ""))
        if table not in ws.schema_map:
            raise PanelError(f"表 '{table}' 不存在")
        rows_result = read_i18n_rows(ws.config, ws.schemas, table=table)
        for name, path in rows_result.missing:
            log_buffer.add("i18n", "WARN", f"[warn] {path} 不存在，跳过 {name}")
        summary = sync_all(
            ws.config,
            ws.schemas,
            rows_result.rows_by_table,
            issues_by_table=rows_result.issues_by_table,
            table_filter=table,
        )
        totals = summary.totals_by_lang()
        payload = {}
        for lang, counts in sorted(totals.items()):
            payload[lang] = {
                "translated": counts.translated,
                "missing": counts.missing,
                "stale": counts.stale,
                "orphan": counts.orphan,
            }
            log_buffer.add(
                "i18n",
                "INFO",
                f"[sync] {lang}: translated={counts.translated}, "
                f"missing={counts.missing}, stale={counts.stale}, orphan={counts.orphan}",
            )
        return ok({"langs": payload, "elapsed": round(summary.elapsed, 2)})

    @app.post("/api/i18n/compact")
    @safe
    def i18n_compact():
        if _looks_canonical(app.config["ROOT"]):
            from ct.app.canonical_commands import canonical_i18n_compact

            data = request.get_json(silent=True) or {}
            removed = canonical_i18n_compact(app.config["ROOT"], table_filter=data.get("table"))
            return ok({"total_removed": removed})
        ws = _load_ws(app)
        data = request.get_json(silent=True) or {}
        table = str(data.get("table", ""))
        dry_run = bool(data.get("dry_run", False))
        if table not in ws.schema_map:
            raise PanelError(f"表 '{table}' 不存在")
        summary = compact_i18n(ws.config, ws.schemas, table=table, dry_run=dry_run)
        files = [
            {
                "lang": f.lang,
                "table": f.table,
                "removed_keys": f.removed_keys,
            }
            for f in summary.files
        ]
        total_removed = (
            sum(len(f["removed_keys"]) for f in files)
            if dry_run
            else summary.total_removed
        )
        return ok(
            {
                "dry_run": dry_run,
                "touched": summary.touched,
                "total_removed": total_removed,
                "files": files,
            }
        )

    @app.get("/api/i18n/status")
    @safe
    def i18n_status():
        if _looks_canonical(app.config["ROOT"]):
            from ct.app.canonical_commands import canonical_i18n_status

            return ok(canonical_i18n_status(app.config["ROOT"]))
        ws = _load_ws(app)
        report = compute_status_report(ws.config, ws.schemas)
        return ok(json.loads(render_json(report))["langs"])

    # ---------------- 日志与历史 ----------------
    @app.get("/api/logs")
    @safe
    def logs():
        module = request.args.get("module", "all")
        return ok(log_buffer.snapshot(module))

    @app.get("/api/history")
    @safe
    def history():
        if _looks_canonical(app.config["ROOT"]):
            cache_dir = app.config["ROOT"] / "cache"
            return ok(load_history(cache_dir))
        ws = _load_ws(app)
        return ok(load_history(ws.resolve("cache_dir")))

    return app
