"""Schema Workspace Web API: snapshot, validate, candidate, gen-template, save.

The API is structured JSON only (never YAML text from the browser). Saving is a
single request carrying the Schema baseline, the command prefix and the
server-computed candidate hash; the server rebuilds and publishes only the YAML
that really differs. There is no persisted plan, no TTL and no full-pipeline
apply endpoint any more.
"""

from __future__ import annotations

import logging
import time
from functools import wraps
from pathlib import Path

from flask import Blueprint, jsonify, request

from ct.app.canonical_commands import UnknownTableError, canonical_gen_template
from ct.app.canonical_workspace import CanonicalWorkspace
from ct.app.schema_workspace.candidate import (
    candidate_hash,
    merge_indexes,
    validate_candidate,
)
from ct.app.schema_workspace.commands_reducer import (
    Command,
    DraftLog,
    apply_command,
)
from ct.app.schema_workspace.legacy_apply import (
    LegacyApplyBlocked,
    recover_legacy_apply,
)
from ct.app.schema_workspace.netdiff import compute_net_diff
from ct.app.schema_workspace.save import (
    YamlSaveResult,
    plan_yaml_save,
    publish_yaml_save,
)
from ct.app.schema_workspace.snapshot import (
    build_schema_revision,
    build_snapshot,
    capture_schema_sources,
)
from ct.schema.resource_repository import ResourceDecodeError
from ct.storage.files import normalize
from ct.config import load_config
from ct.schema.resources import SchemaResource
from ct.storage.publication import PublicationError
from ct.storage.workspace_lock import WorkspaceBusyError
from ct.storage.workspace_transaction import workspace_transaction

schema_workspace_api = Blueprint("schema_workspace", __name__)

#: 模板生成的面板日志：模块名由 logger 名（含 ``template``）归类到日志页的模板分类。
logger = logging.getLogger("ct.web.template")


def json_errors(fn):
    """把未捕获异常转成 {"ok": false, "error": ...} JSON。

    本 blueprint 的路由不走 ``ct.web.app.safe``，异常会落到 Flask 默认的 HTML
    500，前端只能显示 "HTTP 500"，加载失败的原因（例如某个 YAML 解析不了）
    在面板里就看不见了。
    """

    @wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except FileNotFoundError as exc:
            return jsonify({"ok": False, "error": f"文件不存在: {exc}"}), 404
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        except OSError as exc:
            return jsonify({"ok": False, "error": f"内部错误: {exc}"}), 500
        except Exception as exc:  # noqa: BLE001 - 兜底：宁可 JSON 报错也不返回 HTML
            return jsonify({"ok": False, "error": f"内部错误: {exc}"}), 500

    return wrapper


def _root() -> Path:
    # ROOT is injected via app config by the caller; Flask passes it below.
    from flask import current_app

    return current_app.config["ROOT"]


def _workspace() -> CanonicalWorkspace:
    return CanonicalWorkspace.load(_root())


class SchemaRevisionConflict(ValueError):
    """Candidate requests cannot silently rebase a draft."""


class DraftCommandError(ValueError):
    """一条草稿命令无法执行：携带 ``commands[i].<字段>`` 定位。"""

    def __init__(self, message: str, *, location: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.location = location

    def to_issue(self) -> dict:
        return {"message": self.message, "location": self.location, "kind": "blocker"}


def _commands(payload) -> list[Command]:
    items = payload.get("commands", [])
    if not isinstance(items, list):
        raise DraftCommandError("commands 必须是数组", location="commands")
    commands: list[Command] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise DraftCommandError("命令必须是对象", location=f"commands[{index}]")
        if "type" not in item:
            raise DraftCommandError("命令缺少 type", location=f"commands[{index}]")
        commands.append(
            Command(type=str(item["type"]), payload=item.get("payload") or {})
        )
    return commands


def _replay(ws: CanonicalWorkspace, commands: list[Command]) -> DraftLog:
    """在基线上重放命令；任何一条失败都转成带命令位置的客户端错误。

    ``DraftLog`` 是惰性的（``execute`` 只入队，``current()`` 才重放），所以这里
    逐条应用一次以定位失败命令；同一份 reducer 随后仍由 ``log.current()`` 重算，
    两边语义完全一致。
    """
    log = DraftLog(ws.resources.resources, base_indexes=dict(ws.indexes))
    state = (ws.resources.resources, dict(ws.indexes))
    for index, command in enumerate(commands):
        try:
            state = apply_command(state, command)
        except ResourceDecodeError as exc:
            location = f"commands[{index}].payload"
            if exc.location:
                location += f".{exc.location}"
            raise DraftCommandError(exc.message, location=location) from exc
        except (KeyError, TypeError, ValueError) as exc:
            raise DraftCommandError(
                f"命令 {command.type} 无法执行：{exc}", location=f"commands[{index}]"
            ) from exc
        log.execute(command)
    return log


def _draft_from_payload(payload):
    # 索引不是纯草稿层概念：它是持久化 Table 资源的一部分（随 YAML 落盘）。
    # base 必须带上工作区已声明的索引，否则候选校验看不见它们
    # （删/改/重类型 CodeName 不会被拦），保存时也会被抹成 ()。
    config = load_config(_root())
    sources = capture_schema_sources(config)
    expected = payload.get("schemaRevision")
    if expected and expected != sources.revision.revision:
        raise SchemaRevisionConflict("Schema 基线已变化，草稿保留；请核对后重新加载。")
    ws = CanonicalWorkspace.load(_root(), contents=sources.contents, config=config)
    return ws, _replay(ws, _commands(payload))


def _stale_draft_issue(exc: Exception) -> dict:
    return {
        "message": f"未应用草稿已过期，无法应用当前变更：{exc}。请放弃草稿后重新编辑。",
        "location": "",
        "kind": "blocker",
    }


def _draft_view(ws, log) -> dict:
    """Authoritative server-side view of one draft: resources, issues, net diff.

    The browser is never trusted for the summary: the candidate is rebuilt from
    the command prefix, validated structurally, hashed for optimistic
    concurrency and diffed against the on-disk baseline.
    """
    resources, indexes = log.current()
    merged = merge_indexes(resources, indexes)
    base = (ws.resources.resources, dict(ws.indexes))
    diff = compute_net_diff(base, (merged, indexes), log.commands, cursor=log.cursor)
    issues = validate_candidate(merged, indexes)
    return {
        "resources": merged,
        "issues": issues,
        "netDiff": diff.to_payload(),
        "candidateHash": candidate_hash(resources, indexes),
        "schemaRevision": build_schema_revision(ws.config).to_payload(),
    }


@schema_workspace_api.get("/api/schema-workspace")
@json_errors
def workspace_snapshot():
    ws = _workspace()
    snapshot = build_snapshot(ws)
    return jsonify(
        {
            "ok": True,
            "data": {
                "revision": snapshot.revision,
                "schemaRevision": build_schema_revision(ws.config).revision,
                "resources": [_resource_payload(resource) for resource in ws.resources.resources],
                "reverseRefs": {
                    resource_id: [
                        {"owner": ref.owner, "field": ref.field_path, "kind": ref.kind}
                        for ref in references
                    ]
                    for resource_id, references in ws.reverse_refs.items()
                },
                "changed": snapshot.changed_inputs(snapshot),
            },
        }
    )


def _resource_payload(resource):
    """Normalized resource payload: stable resourceId + kind + display name."""
    from ct.schema.resources import TableResource

    data = resource.model_dump(mode="json", by_alias=True, exclude_none=True)
    data["resourceId"] = resource.resource_id
    if isinstance(resource, TableResource):
        data["kind"] = "table"
        data.setdefault("name", resource.table)
    return data


@schema_workspace_api.post("/api/schema-workspace/validate")
@json_errors
def workspace_validate():
    payload = request.get_json(silent=True) or {}
    try:
        ws, log = _draft_from_payload(payload)
        view = _draft_view(ws, log)
    except SchemaRevisionConflict as exc:
        return _save_conflict("schema-revision", str(exc))
    except DraftCommandError as exc:
        return jsonify(
            {
                "ok": True,
                "data": {"valid": False, "issues": [exc.to_issue()], "netDiff": None},
            }
        )
    except (KeyError, ValueError) as exc:
        issue = _stale_draft_issue(exc)
        return jsonify(
            {"ok": True, "data": {"valid": False, "issues": [issue], "netDiff": None}}
        )
    issues = view["issues"]
    return jsonify(
        {
            "ok": True,
            "data": {
                "valid": not issues,
                "issues": [
                    {"message": issue.message, "location": issue.location, "kind": issue.kind}
                    for issue in issues
                ],
                "candidateHash": view["candidateHash"],
                "schemaRevision": view["schemaRevision"],
                "netDiff": view["netDiff"],
            },
        }
    )


@schema_workspace_api.post("/api/schema-workspace/gen-template")
@json_errors
def workspace_gen_template():
    """Regenerate the Excel template for one persisted table schema."""
    payload = request.get_json(silent=True) or {}
    table = str(payload.get("table", "")).strip()
    if not table:
        return jsonify({"ok": False, "error": "缺少 table"}), 400
    try:
        messages = canonical_gen_template(_root(), table_filter=table)
    except UnknownTableError:
        logger.error("生成模板失败：未找到表 %s", table)
        # 保持既有 404 契约（`canonical_gen_template` 现在对未知表名一律报错）
        return jsonify({"ok": False, "error": f"未找到表: {table}"}), 404
    except (ValueError, OSError) as exc:
        logger.error("生成模板失败：%s · %s", table, exc)
        return jsonify({"ok": False, "error": str(exc)}), 400
    logger.info("生成模板：%s（%s 张表）", table, len(messages))
    return jsonify({"ok": True, "data": {"messages": messages}})


@schema_workspace_api.post("/api/schema-workspace/candidate")
@json_errors
def workspace_candidate():
    """Return the candidate resource payloads, net diff and structural issues."""
    try:
        ws, log = _draft_from_payload(request.get_json(silent=True) or {})
        view = _draft_view(ws, log)
    except SchemaRevisionConflict as exc:
        return _save_conflict("schema-revision", str(exc))
    except DraftCommandError as exc:
        return jsonify({"ok": False, "error": exc.message, "issues": [exc.to_issue()]}), 400
    except (KeyError, ValueError) as exc:
        return jsonify({"ok": False, "error": _stale_draft_issue(exc)["message"]}), 400
    return jsonify(
        {
            "ok": True,
            "data": {
                "resources": [_resource_payload(r) for r in view["resources"]],
                "issues": [
                    {"message": issue.message, "location": issue.location, "kind": issue.kind}
                    for issue in view["issues"]
                ],
                "netDiff": view["netDiff"],
                "candidateHash": view["candidateHash"],
                "schemaRevision": view["schemaRevision"],
            },
        }
    )


@schema_workspace_api.post("/api/schema-workspace/save")
@json_errors
def workspace_save():
    """YAML-only transactional save.

    The browser submits the baseline it edited from, the command prefix and the
    candidate hash it believes in. The server rebuilds the candidate from the
    commands, re-reads the baseline from captured bytes, and publishes only the
    YAML files that really differ — inside the shared workspace transaction, so
    export/deploy/save cannot interleave.
    """
    payload = request.get_json(silent=True) or {}
    root = _root()
    expected_revision = str(payload.get("schemaRevision", "")).strip()
    expected_candidate = str(payload.get("candidateHash", "")).strip()
    if not expected_revision or not expected_candidate:
        return jsonify({"ok": False, "error": "保存必须提供 schemaRevision 和 candidateHash"}), 400
    try:
        commands = _commands(payload)
    except DraftCommandError as exc:
        return jsonify({"ok": False, "error": exc.message, "issues": [exc.to_issue()]}), 400
    except (KeyError, TypeError) as exc:
        return jsonify({"ok": False, "error": f"保存请求的命令格式非法：{exc}"}), 400

    recovery: str | None = None
    try:
        with workspace_transaction(root) as recovery:
            # 旧 Apply 的遗留材料必须先有定论：能还原就还原，否则保留材料并拒绝写入
            legacy = recover_legacy_apply(root)
            if legacy is not None and legacy.blocked:
                return _save_conflict(
                    "legacy-apply",
                    "存在无法可靠还原的旧 Apply 事务材料，已保留材料并阻止保存："
                    + legacy.reason,
                    materials=list(legacy.materials),
                )
            if legacy is not None and legacy.recovered:
                # 现场刚被改动：调用方手里的基线已不代表磁盘，必须先重新加载
                return _save_conflict(
                    "legacy-apply-recovered",
                    f"{legacy.reason}；请重新加载工作区后再保存。",
                    materials=list(legacy.materials),
                    schemaRevision=build_schema_revision(
                        CanonicalWorkspace.load(root).config
                    ).to_payload(),
                )
            # 恢复发生在加载配置之前：global.yaml 即使已被改坏也要先复原现场
            config = load_config(root)
            sources = capture_schema_sources(config)
            current_revision = sources.revision

            if current_revision.revision != expected_revision:
                return _save_conflict(
                    "schema-revision",
                    "Schema 基线已变化，未覆盖外部修改；草稿保留，请核对后重新加载。",
                    schemaRevision=current_revision.to_payload(),
                )

            workspace = CanonicalWorkspace.load(
                root, contents=sources.contents, config=config
            )
            log = _replay(workspace, commands)
            resources, indexes = log.current()
            merged = merge_indexes(resources, indexes)

            if candidate_hash(resources, indexes) != expected_candidate:
                return _save_conflict(
                    "candidate-hash",
                    "候选内容与服务器重建结果不一致，保存被拒绝，未写入任何文件。",
                )

            issues = validate_candidate(merged, indexes)
            if issues:
                return (
                    jsonify(
                        {
                            "ok": False,
                            "error": "；".join(issue.render() for issue in issues),
                            "issues": [
                                {
                                    "message": issue.message,
                                    "location": issue.location,
                                    "kind": issue.kind,
                                }
                                for issue in issues
                            ],
                        }
                    ),
                    400,
                )

            diff = compute_net_diff(
                (workspace.resources.resources, dict(workspace.indexes)),
                (merged, indexes),
                log.commands,
                cursor=log.cursor,
            )
            plan = plan_yaml_save(workspace, merged)
            if plan.blocked:
                return _save_conflict("target", "；".join(plan.conflicts))

            # 发布前复核：加载到发布的窗口内源文件不得变化
            recheck = capture_schema_sources(config)
            if recheck.revision.revision != current_revision.revision:
                return _save_conflict(
                    "schema-revision",
                    "保存期间 Schema 源文件被其他进程修改，未写入任何文件。",
                    changedMembers=recheck.revision.changed_members(
                        current_revision
                    ),
                    schemaRevision=recheck.revision.to_payload(),
                )

            # 发布前目标存在性复核：计划生成后到真正落盘之间，目标不得被外部创建
            baseline_sources = {
                normalize(Path(path)) for path in workspace.resources.sources.values()
            }
            unexpected = [
                path
                for path in plan.writes
                if path not in baseline_sources and path.exists()
            ]
            if unexpected:
                return _save_conflict(
                    "target",
                    "发布前发现目标文件已被其他进程创建，拒绝覆盖："
                    + "、".join(str(path) for path in sorted(unexpected)),
                )

            if diff.is_empty:
                result = YamlSaveResult(unchanged=plan.unchanged)
            else:
                result = publish_yaml_save(root, plan)
    except SchemaRevisionConflict as exc:
        return _save_conflict("schema-revision", str(exc))
    except DraftCommandError as exc:
        return jsonify({"ok": False, "error": exc.message, "issues": [exc.to_issue()]}), 400
    except LegacyApplyBlocked as exc:
        return _save_conflict(
            "legacy-apply", str(exc), materials=list(getattr(exc, "materials", ()))
        )
    except WorkspaceBusyError as exc:
        return jsonify({"ok": False, "error": str(exc), "busy": True}), 409
    except PublicationError as exc:
        return jsonify(
            {"ok": False, "error": f"保存发布失败，已恢复到保存前状态：{exc}"}
        ), 500
    except (ValueError, OSError) as exc:
        return jsonify({"ok": False, "error": f"保存失败：{exc}"}), 400

    fresh = _workspace()
    saved_revision = build_schema_revision(fresh.config).revision
    return jsonify(
        {
            "ok": True,
            "data": {
                "isNoOp": not result.changed,
                "notes": list(plan.notes),
                "written": sorted(str(path) for path in result.written),
                "deleted": sorted(str(path) for path in result.deleted),
                "unchanged": sorted(str(path) for path in result.unchanged),
                "changedResources": diff.changed_resources,
                "netDiff": compute_net_diff(
                    (fresh.resources.resources, dict(fresh.indexes)),
                    (fresh.resources.resources, dict(fresh.indexes)),
                ).to_payload(),
                "recovery": recovery,
                "revision": saved_revision,
                "schemaRevision": saved_revision,
                "resources": [
                    _resource_payload(resource) for resource in fresh.resources.resources
                ],
                "reverseRefs": {
                    resource_id: [
                        {"owner": ref.owner, "field": ref.field_path, "kind": ref.kind}
                        for ref in references
                    ]
                    for resource_id, references in fresh.reverse_refs.items()
                },
            },
        }
    )


def _save_conflict(kind: str, message: str, **extra):
    return (
        jsonify({"ok": False, "error": message, "conflict": {"kind": kind, **extra}}),
        409,
    )


def register_schema_workspace_api(app) -> None:
    app.register_blueprint(schema_workspace_api)
