"""Schema Workspace Web API tests (7.5/7.6/7.7)."""

from __future__ import annotations

from pathlib import Path

from ct.app.canonical_workspace import CanonicalWorkspace
from ct.app.schema_workspace.apply import create_plan
from ct.app.schema_workspace.snapshot import build_snapshot
from ct.web.app import create_app

from _helpers import build_project


def _client(tmp_path: Path):
    root = build_project(
        tmp_path / "gd",
        schemas=[
            {
                "table": "Item",
                "primary": "Id",
                "fields": [{"name": "Id", "type": "int32", "comment": "a"}],
            }
        ],
    )
    return create_app(root).test_client(), CanonicalWorkspace.load(root)


def test_workspace_snapshot_endpoint(tmp_path: Path) -> None:
    client, ws = _client(tmp_path)
    resp = client.get("/api/schema-workspace")
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["revision"] == build_snapshot(ws).revision
    assert any(r["table"] == "Item" for r in data["resources"])


def test_validate_accepts_valid_draft(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    resp = client.post(
        "/api/schema-workspace/validate",
        json={"commands": [{"type": "add_field", "payload": {"owner": "table:Item", "field": {"name": "Price", "type": "int32"}}}]},
    )
    assert resp.status_code == 200
    assert resp.get_json()["data"]["valid"] is True


def test_validate_reports_role_violation(tmp_path: Path) -> None:
    client, ws = _client(tmp_path)
    # a record with an i18n leaf via draft
    record = {"kind": "record", "name": "R", "fields": [{"name": "N", "type": "string"}]}
    (tmp_path / "gd" / "config" / "types" / "R.yaml").write_text(
        "kind: record\nname: R\nfields:\n  - name: N\n    type: string\n",
        encoding="utf-8",
    )
    ws2 = CanonicalWorkspace.load(tmp_path / "gd")
    client2 = create_app(tmp_path / "gd").test_client()
    resp = client2.post(
        "/api/schema-workspace/validate",
        json={"commands": [{"type": "set_property", "payload": {"owner": "record:R", "name": "N", "property": "i18n", "value": True}}]},
    )
    assert resp.status_code == 200
    assert resp.get_json()["data"]["valid"] is False
    assert any("i18n" in issue["message"] for issue in resp.get_json()["data"]["issues"])


def test_change_plan_returns_impacts(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    resp = client.post(
        "/api/schema-workspace/change-plan",
        json={"commands": [{"type": "set_property", "payload": {"owner": "table:Item", "name": "Id", "property": "comment", "value": "b"}}]},
    )
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["risk"] == "safe"
    assert any(impact["artifact"] == "Schema" for impact in data["impacts"])


def test_apply_endpoint_success_and_stale(tmp_path: Path) -> None:
    client, ws = _client(tmp_path)
    schema = tmp_path / "gd" / "config" / "schemas" / "Item.yaml"
    original = schema.read_text(encoding="utf-8")
    manifest = create_plan(
        ws,
        candidate_resources=list(ws.resources.resources),
        candidate_indexes={},
        targets=[("config/schemas/Item.yaml", "Item.yaml")],
        table_fingerprints={},
    )
    (manifest.staging_dir / "Item.yaml").write_text(original.replace("comment: a", "comment: b"), encoding="utf-8")

    # stale base revision -> 409 before writes
    resp = client.post(
        "/api/schema-workspace/apply",
        json={"planId": manifest.plan_id, "baseRevision": "stale", "candidateHash": manifest.candidate_hash},
    )
    assert resp.status_code == 409
    assert schema.read_text(encoding="utf-8") == original

    # correct apply -> success
    resp = client.post(
        "/api/schema-workspace/apply",
        json={"planId": manifest.plan_id, "baseRevision": manifest.base_revision, "candidateHash": manifest.candidate_hash},
    )
    assert resp.status_code == 200
    assert schema.read_text(encoding="utf-8") == original.replace("comment: a", "comment: b")


def test_tasks_endpoint(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    resp = client.get("/api/tasks")
    assert resp.status_code == 200
    assert isinstance(resp.get_json()["data"], list)


def test_prepare_apply_creates_plan_and_applies(tmp_path: Path) -> None:
    client, ws = _client(tmp_path)
    schema = tmp_path / "gd" / "config" / "schemas" / "Item.yaml"
    original = schema.read_text(encoding="utf-8")

    prepared = client.post(
        "/api/schema-workspace/prepare-apply",
        json={"commands": [{"type": "set_property", "payload": {"owner": "table:Item", "name": "Id", "property": "comment", "value": "b"}}]},
    )
    assert prepared.status_code == 200, prepared.get_json()
    plan = prepared.get_json()["data"]

    applied = client.post(
        "/api/schema-workspace/apply",
        json={
            "planId": plan["planId"],
            "baseRevision": plan["baseRevision"],
            "candidateHash": plan["candidateHash"],
        },
    )
    assert applied.status_code == 200, applied.get_json()
    assert schema.read_text(encoding="utf-8") != original
    assert "comment: b" in schema.read_text(encoding="utf-8")


def test_prepare_apply_rejects_blocked_candidate(tmp_path: Path) -> None:
    client, ws = _client(tmp_path)
    # record with i18n leaf -> candidate blocked
    (tmp_path / "gd" / "config" / "types" / "R.yaml").write_text(
        "kind: record\nname: R\nfields:\n  - name: N\n    type: string\n",
        encoding="utf-8",
    )
    client2 = create_app(tmp_path / "gd").test_client()
    resp = client2.post(
        "/api/schema-workspace/prepare-apply",
        json={"commands": [{"type": "set_property", "payload": {"owner": "record:R", "name": "N", "property": "i18n", "value": True}}]},
    )
    assert resp.status_code == 400
    assert "i18n" in resp.get_json()["error"]
