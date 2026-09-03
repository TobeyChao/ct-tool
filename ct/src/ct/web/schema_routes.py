"""Schema read + gated-write routes (extracted from app.py for 14.4).

Route modules stay thin presenters: they never write YAML/Excel/cache, never
call the destructive file-replacement primitive and never orchestrate generators. Writable legacy Schema
routes are permanently gated (409) by the SchemaEntryGate.
"""

from __future__ import annotations

from functools import wraps
from typing import Any, Callable

from flask import Blueprint, current_app, jsonify

from ct.app.status import compute_status as compute_workspace_status
from ct.app.workspace import Workspace
from ct.cache.state import load_cache
from ct.schema.models import FieldDef

schema_routes = Blueprint("schema_routes", __name__)


class PanelError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


def ok(data: Any):
    return jsonify({"ok": True, "data": data})


def safe(fn: Callable):
    @wraps(fn)
    def wrapper(*args: Any, **kwargs: Any):
        try:
            return fn(*args, **kwargs)
        except PanelError as e:
            return jsonify({"ok": False, "error": str(e)}), e.status
        except FileNotFoundError as e:
            return jsonify({"ok": False, "error": f"文件不存在: {e}"}), 404
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400
        except Exception as e:  # noqa: BLE001
            return jsonify({"ok": False, "error": f"内部错误: {e}"}), 500

    return wrapper


def _load_ws() -> Workspace:
    root = current_app.config["ROOT"]
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


@schema_routes.get("/api/schemas")
@safe
def schemas_list():
    ws = _load_ws()
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

@schema_routes.get("/api/schemas/<table>")
@safe
def schemas_detail(table: str):
    ws = _load_ws()
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
