"""Flask 面板：静态托管 + JSON API，薄封装 ct/app 用例层。"""

from __future__ import annotations

import json
import logging
from functools import wraps
from pathlib import Path
from typing import Any, Callable

import pydantic
import yaml
from flask import Flask, jsonify, request, send_from_directory

from ct.app.i18n import read_i18n_rows
from ct.app.status import compute_status as compute_workspace_status
from ct.app.template import Action, decide_template_action
from ct.app.workspace import Workspace
from ct.cache.state import load_cache
from ct.excel.template import generate_template, update_template
from ct.export.i18n.compact import CompactError, compact_i18n
from ct.export.i18n.io import dump_lang_file
from ct.export.i18n.merger import load_translation
from ct.export.i18n.state import (
    compute_status as compute_entry_status,
    sync_lang_table,
)
from ct.export.i18n.status import compute_status_report, render_json
from ct.export.i18n.sync import sync_all
from ct.schema.models import FieldDef, TableSchema
from ct.web.history import load_history
from ct.web.logs import PanelLogHandler, log_buffer
from ct.web.tasks import export_task


class PanelError(Exception):
    """带 HTTP 状态码的业务错误。"""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


def _schema_error_text(exc: Exception) -> str:
    if isinstance(exc, pydantic.ValidationError):
        parts = []
        for e in exc.errors():
            loc = ".".join(str(p) for p in e.get("loc", ()))
            ctx = e.get("ctx") or {}
            obj = ctx.get("error")
            msg = str(obj) if obj is not None else e.get("msg", str(exc))
            parts.append(f"{loc}: {msg}" if loc else msg)
        return "; ".join(parts)
    return str(exc)


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


def _field_dict(f: FieldDef) -> dict:
    d: dict = {
        "name": f.name,
        "type": f.type,
        "i18n": f.i18n,
        "server_only": f.server_only,
        "ref": f.ref,
        "comment": f.comment,
    }
    if f.type == "enum":
        d["values"] = f.values or []
    elif f.type == "struct":
        d["fields"] = [_field_dict(sf) for sf in (f.fields or [])]
    elif f.type == "array":
        d["element"] = f.element
        d["separator"] = f.separator
        if f.element_values:
            d["element_values"] = f.element_values
    return d


def _build_schema(data: dict) -> TableSchema:
    fields_yaml = data.get("fields_yaml", "")
    try:
        fields = yaml.safe_load(fields_yaml) if str(fields_yaml).strip() else []
    except yaml.YAMLError as e:
        raise PanelError(f"字段定义 YAML 解析失败: {e}") from e
    if not isinstance(fields, list):
        raise PanelError("字段定义必须是 YAML 列表")
    try:
        return TableSchema(
            table=str(data.get("table", "")).strip(),
            primary=str(data.get("primary", "")).strip(),
            json_key=data.get("json_key") or None,
            excel_file=data.get("excel_file") or None,
            fields=fields,
        )
    except pydantic.ValidationError as e:
        raise PanelError(f"schema 校验失败: {_schema_error_text(e)}") from e


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


def create_app(root: Path | None = None) -> Flask:
    # 前端静态资源随包分发：与 app.py 同处 ct/web/static
    static_dir = Path(__file__).resolve().parent / "static"
    app = Flask(__name__, static_folder=str(static_dir), static_url_path="/static")
    app.config["ROOT"] = Path(root or Path(".")).resolve()

    logging.getLogger("ct").addHandler(PanelLogHandler(log_buffer))

    @app.get("/")
    @safe
    def index():
        return send_from_directory(static_dir, "index.html")

    # ---------------- 工作区 ----------------
    @app.get("/api/workspace")
    @safe
    def workspace():
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
        ws = _load_ws(app)
        report = compute_status_report(ws.config, ws.schemas)
        return ok(json.loads(render_json(report))["langs"])

    # ---------------- 表格管理 ----------------
    def _template_status(ws: Workspace) -> dict[str, str]:
        cache = load_cache(ws.resolve("cache_dir"))
        report = compute_workspace_status(ws, cache)
        status_map: dict[str, str] = {}
        for name in ws.order:
            if name in report.missing:
                status_map[name] = "missing"
            elif name in report.untracked:
                status_map[name] = "untracked"
            elif name in report.drifted:
                status_map[name] = "drift"
            else:
                status_map[name] = "ok"
        return status_map

    @app.get("/api/schemas")
    @safe
    def schemas_list():
        ws = _load_ws(app)
        status_map = _template_status(ws)
        return ok(
            [
                {
                    "table": s.table,
                    "excel_file": s.resolved_excel_file,
                    "json_key": s.resolved_json_key,
                    "primary": s.primary,
                    "pk_type": s.primary_field.type,
                    "field_count": len(s.fields),
                    "i18n_count": len(s.i18n_fields),
                    "template_status": status_map.get(s.table, "ok"),
                }
                for s in ws.schemas
            ]
        )

    @app.get("/api/schemas/<table>")
    @safe
    def schemas_detail(table: str):
        ws = _load_ws(app)
        if table not in ws.schema_map:
            raise PanelError(f"表 '{table}' 不存在", 404)
        schema = ws.schema_map[table]
        status_map = _template_status(ws)
        return ok(
            {
                "table": schema.table,
                "excel_file": schema.resolved_excel_file,
                "json_key": schema.resolved_json_key,
                "primary": schema.primary,
                "pk_type": schema.primary_field.type,
                "template_status": status_map.get(table, "ok"),
                "fields": [_field_dict(f) for f in schema.fields],
            }
        )

    @app.post("/api/schemas")
    @safe
    def schemas_create():
        ws = _load_ws(app)
        data = request.get_json(silent=True) or {}
        schema = _build_schema(data)
        schemas_dir = ws.resolve("schemas_dir")
        yaml_path = schemas_dir / f"{schema.table}.yaml"
        if yaml_path.exists():
            raise PanelError(f"表 '{schema.table}' 已存在")
        schemas_dir.mkdir(parents=True, exist_ok=True)
        yaml_path.write_text(
            yaml.safe_dump(
                schema.model_dump(exclude_none=True), allow_unicode=True, sort_keys=False
            ),
            encoding="utf-8",
        )
        log_buffer.add("模板", "INFO", f"[new] {schema.table}: schema 已创建")
        ws = _load_ws(app)
        schema = ws.schema_map[schema.table]
        out_path = ws.resolve("excel_dir") / schema.resolved_excel_file
        decision = decide_template_action(schema, out_path, force=False, update_header=False)
        if decision.action in (Action.CREATE_NEW, Action.REBUILD):
            generate_template(schema, out_path)
        log_buffer.add("模板", "INFO", decision.message)
        return ok({"table": schema.table, "message": decision.message})

    @app.put("/api/schemas/<table>")
    @safe
    def schemas_update(table: str):
        ws = _load_ws(app)
        if table not in ws.schema_map:
            raise PanelError(f"表 '{table}' 不存在", 404)
        data = request.get_json(silent=True) or {}
        new_schema = _build_schema(data)
        schemas_dir = ws.resolve("schemas_dir")
        old_yaml = schemas_dir / f"{table}.yaml"

        if new_schema.table != table:
            # 改名：写新 schema 文件，移除旧文件；旧 Excel 不自动迁移
            new_yaml = schemas_dir / f"{new_schema.table}.yaml"
            new_yaml.write_text(
                yaml.safe_dump(
                    new_schema.model_dump(exclude_none=True),
                    allow_unicode=True,
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
            old_yaml.unlink(missing_ok=True)
            log_buffer.add(
                "模板", "WARN", f"[rename] {table} → {new_schema.table}（旧 Excel 未迁移）"
            )
        else:
            old_yaml.write_text(
                yaml.safe_dump(
                    new_schema.model_dump(exclude_none=True),
                    allow_unicode=True,
                    sort_keys=False,
                ),
                encoding="utf-8",
            )

        ws = _load_ws(app)
        schema = ws.schema_map[new_schema.table]
        excel_dir = ws.resolve("excel_dir")
        excel_dir.mkdir(parents=True, exist_ok=True)
        out_path = excel_dir / schema.resolved_excel_file
        decision = decide_template_action(schema, out_path, force=False, update_header=True)
        if decision.action == Action.REFUSE:
            raise PanelError(decision.message)
        if decision.action in (Action.CREATE_NEW, Action.REBUILD):
            generate_template(schema, out_path)
        elif decision.action == Action.UPDATE_PRESERVE:
            preserved = update_template(schema, out_path)
            decision = decide_template_action(schema, out_path, force=False, update_header=False)
            log_buffer.add(
                "模板", "INFO", f"[update] {schema.table}: 保留 {preserved} 行数据重建表头"
            )
        else:
            log_buffer.add("模板", "INFO", decision.message)
        return ok(
            {
                "table": schema.table,
                "renamed": new_schema.table != table,
                "message": decision.message,
            }
        )

    @app.delete("/api/schemas/<table>")
    @safe
    def schemas_delete(table: str):
        ws = _load_ws(app)
        if table not in ws.schema_map:
            raise PanelError(f"表 '{table}' 不存在", 404)
        schema = ws.schema_map[table]
        removed = []
        yaml_path = ws.resolve("schemas_dir") / f"{table}.yaml"
        if yaml_path.exists():
            yaml_path.unlink()
            removed.append(str(yaml_path))
        xlsx_path = ws.resolve("excel_dir") / schema.resolved_excel_file
        if xlsx_path.exists():
            xlsx_path.unlink()
            removed.append(str(xlsx_path))
        log_buffer.add("模板", "WARN", f"[delete] {table}: 已移除 schema 与模板")
        return ok({"table": table, "removed": removed})

    # ---------------- 日志与历史 ----------------
    @app.get("/api/logs")
    @safe
    def logs():
        module = request.args.get("module", "all")
        return ok(log_buffer.snapshot(module))

    @app.get("/api/history")
    @safe
    def history():
        ws = _load_ws(app)
        return ok(load_history(ws.resolve("cache_dir")))

    return app
