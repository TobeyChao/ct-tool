"""Schema Workspace Web API: snapshot, validate, change-plan, apply.

The API is structured JSON only (never YAML text from the browser). Plans are
identified by token + hashes; Apply never accepts a full candidate replay.
"""

from __future__ import annotations

import time
from pathlib import Path

from flask import Blueprint, jsonify, request

from ct.app.canonical_workspace import CanonicalWorkspace
from ct.app.schema_workspace.apply import (
    ApplyError,
    apply_plan,
    create_plan,
    load_plan,
    recover,
)
from ct.app.schema_workspace.candidate import validate_candidate
from ct.app.schema_workspace.commands_reducer import Command, DraftLog
from ct.app.schema_workspace.plan import build_change_plan
from ct.app.schema_workspace.snapshot import build_snapshot
from ct.schema.resources import SchemaResource

schema_workspace_api = Blueprint("schema_workspace", __name__)


def _root() -> Path:
    # ROOT is injected via app config by the caller; Flask passes it below.
    from flask import current_app

    return current_app.config["ROOT"]


def _workspace() -> CanonicalWorkspace:
    return CanonicalWorkspace.load(_root())


def _commands(payload) -> list[Command]:
    return [
        Command(type=item["type"], payload=item.get("payload", {}))
        for item in payload.get("commands", [])
    ]


def _draft_from_payload(payload):
    ws = _workspace()
    log = DraftLog(
        ws.resources.resources,
        base_indexes={},
    )
    for command in _commands(payload):
        log.execute(command)
    return ws, log


@schema_workspace_api.get("/api/schema-workspace")
def workspace_snapshot():
    ws = _workspace()
    snapshot = build_snapshot(ws)
    return jsonify(
        {
            "ok": True,
            "data": {
                "revision": snapshot.revision,
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
def workspace_validate():
    payload = request.get_json(silent=True) or {}
    _ws, log = _draft_from_payload(payload)
    resources, indexes = log.current()
    issues = validate_candidate(resources, indexes)
    return jsonify(
        {
            "ok": True,
            "data": {
                "valid": not issues,
                "issues": [
                    {"message": issue.message, "location": issue.location, "kind": issue.kind}
                    for issue in issues
                ],
            },
        }
    )


@schema_workspace_api.post("/api/schema-workspace/change-plan")
def workspace_change_plan():
    payload = request.get_json(silent=True) or {}
    ws, log = _draft_from_payload(payload)
    resources, indexes = log.current()
    issues = validate_candidate(resources, indexes)
    if issues:
        return jsonify(
            {
                "ok": True,
                "data": {
                    "plan": None,
                    "issues": [
                        {"message": i.message, "location": i.location, "kind": i.kind}
                        for i in issues
                    ],
                },
            }
        )
    plan = build_change_plan(
        ws.resources.resources,
        resources,
        old_indexes={},
        new_indexes=indexes,
    )
    return jsonify(
        {
            "ok": True,
            "data": {
                "risk": plan.risk,
                "blocked": plan.blocked,
                "impacts": [
                    {"artifact": i.artifact, "table": i.table, "action": i.action, "detail": i.detail}
                    for i in plan.impacts
                ],
                "issues": [
                    {
                        "message": getattr(i, "message", i.render()),
                        "location": getattr(i, "field_path", ""),
                        "kind": getattr(i, "kind", "warning"),
                    }
                    for i in plan.issues
                ],
            },
        }
    )


@schema_workspace_api.post("/api/schema-workspace/candidate")
def workspace_candidate():
    """Return the candidate resource payloads for the draft commands."""
    _ws, log = _draft_from_payload(request.get_json(silent=True) or {})
    resources, _ = log.current()
    return jsonify(
        {"ok": True, "data": {"resources": [_resource_payload(r) for r in resources]}}
    )


@schema_workspace_api.post("/api/schema-workspace/prepare-apply")
def workspace_prepare_apply():
    """Persist a validated candidate as an apply plan (with staged YAML)."""
    from ct.app.schema_workspace.apply import stage_candidate_yaml
    from ct.schema.resources import TableResource

    payload = request.get_json(silent=True) or {}
    ws, log = _draft_from_payload(payload)
    resources, indexes = log.current()
    issues = validate_candidate(resources, indexes)
    if issues:
        return jsonify(
            {
                "ok": False,
                "error": "; ".join(
                    f"{i.message}（{i.location}）" for i in issues
                ),
            }
        ), 400

    targets: list[tuple[str, str]] = []
    for resource in resources:
        directory = "config/schemas" if isinstance(resource, TableResource) else "config/types"
        targets.append((f"{directory}/{resource.name}.yaml", f"{resource.name}.yaml"))

    manifest = create_plan(
        ws,
        candidate_resources=list(resources),
        candidate_indexes=indexes,
        targets=targets,
        table_fingerprints={},
    )
    stage_candidate_yaml(manifest, list(resources))
    return jsonify(
        {
            "ok": True,
            "data": {
                "planId": manifest.plan_id,
                "baseRevision": manifest.base_revision,
                "candidateHash": manifest.candidate_hash,
                "expiresAt": manifest.expires_at,
            },
        }
    )


@schema_workspace_api.post("/api/schema-workspace/apply")
def workspace_apply():
    payload = request.get_json(silent=True) or {}
    plan_id = str(payload.get("planId", ""))
    base_revision = str(payload.get("baseRevision", ""))
    candidate_hash = str(payload.get("candidateHash", ""))
    try:
        result = apply_plan(
            _workspace(),
            plan_id,
            base_revision=base_revision,
            candidate_hash=candidate_hash,
        )
        return jsonify({"ok": True, "data": result})
    except ApplyError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 409


@schema_workspace_api.get("/api/schema-workspace/recover")
def workspace_recover():
    reports = recover(_workspace())
    return jsonify({"ok": True, "data": {"reports": reports}})


def register_schema_workspace_api(app, *, staging_root: Path | None = None) -> None:
    app.register_blueprint(schema_workspace_api)
