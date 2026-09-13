"""Schema Workspace Web API tests (7.5/7.6/7.7)."""

from __future__ import annotations

from pathlib import Path

from ct.app.canonical_workspace import CanonicalWorkspace
from ct.app.schema_workspace.apply import create_plan
from ct.app.schema_workspace.snapshot import build_snapshot
from ct.web.app import create_app

from web_helpers import build_project


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


def test_generate_template_endpoint_for_table(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    excel = tmp_path / "gd" / "excel" / "Item.xlsx"
    assert not excel.exists()

    resp = client.post("/api/schema-workspace/gen-template", json={"table": "Item"})

    assert resp.status_code == 200, resp.get_json()
    assert "模板已生成: Item" in resp.get_json()["data"]["messages"]
    assert excel.exists()


def test_generate_template_endpoint_rejects_unknown_table(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)

    resp = client.post("/api/schema-workspace/gen-template", json={"table": "Missing"})

    assert resp.status_code == 404
    assert "未找到表" in resp.get_json()["error"]


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


def test_tasks_endpoint_includes_export_projection(tmp_path: Path, monkeypatch) -> None:
    client, _ = _client(tmp_path)
    projected = {
        "id": "canonical-export",
        "kind": "导出",
        "scope": "全部表 × 全量语言",
        "status": "error",
        "message": "校验未通过",
        "target": "/logs",
    }
    monkeypatch.setattr(
        "ct.web.app.canonical_export_task.global_task", lambda root: projected
    )

    resp = client.get("/api/tasks")

    assert resp.status_code == 200
    assert projected in resp.get_json()["data"]


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


# ---------------------------------------------------------------------------
# codename 索引 × web 草稿链路回归（索引是持久化 Table 资源的一部分，不是纯草稿概念）
# ---------------------------------------------------------------------------


def _client_with_codename(tmp_path: Path):
    """Item 声明 codename 索引（含 CodeName 字段），Quest 无索引。"""
    root = build_project(
        tmp_path / "gd",
        schemas=[
            {
                "table": "Item",
                "primary": "Id",
                "fields": [
                    {"name": "Id", "type": "int32", "comment": "a"},
                    {"name": "CodeName", "type": "string", "comment": "b"},
                ],
                "indexes": [{"kind": "codename"}],
            },
            {
                "table": "Quest",
                "primary": "Id",
                "fields": [{"name": "Id", "type": "int32", "comment": "a"}],
            },
        ],
    )
    return create_app(root).test_client(), root


def test_prepare_apply_accepts_index_toggle(tmp_path: Path) -> None:
    """给表勾上 codename 索引后 prepare-apply 必须 200（曾是
    TypeError: QueryIndex is not JSON serializable）。"""
    client, _ = _client_with_codename(tmp_path)
    prepared = client.post(
        "/api/schema-workspace/prepare-apply",
        json={"commands": [
            {"type": "set_indexes", "payload": {"table": "table:Item", "indexes": [{"kind": "codename"}]}},
        ]},
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


def test_deleted_table_index_is_not_inherited_by_reused_name(tmp_path: Path) -> None:
    client, _ = _client_with_codename(tmp_path)
    response = client.post(
        "/api/schema-workspace/validate",
        json={"commands": [
            {"type": "delete_resource", "payload": {"name": "table:Item"}},
            {"type": "rename_resource", "payload": {"old": "Quest", "new": "Item"}},
        ]},
    )
    assert response.status_code == 200
    assert response.get_json()["data"]["valid"] is True


def test_apply_preserves_index_when_table_is_renamed(tmp_path: Path) -> None:
    client, root = _client_with_codename(tmp_path)
    prepared = client.post(
        "/api/schema-workspace/prepare-apply",
        json={"commands": [
            {"type": "rename_resource", "payload": {"old": "Item", "new": "Goods"}},
        ]},
    )
    assert prepared.status_code == 200, prepared.get_json()
    plan = prepared.get_json()["data"]
    applied = client.post(
        "/api/schema-workspace/apply",
        json={key: plan[key] for key in ("planId", "baseRevision", "candidateHash")},
    )
    assert applied.status_code == 200, applied.get_json()
    indexes = CanonicalWorkspace.load(root).indexes
    assert indexes["table:Goods"][0].kind == "codename"


def test_apply_keeps_persisted_index_of_untouched_table(tmp_path: Path) -> None:
    """无关表的编辑不得抹掉已声明索引的表的 indexes（曾是静默丢弃）。"""
    client, root = _client_with_codename(tmp_path)
    prepared = client.post(
        "/api/schema-workspace/prepare-apply",
        json={"commands": [
            {"type": "set_property", "payload": {"owner": "table:Quest", "name": "Id", "property": "comment", "value": "edited"}},
        ]},
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
    item_text = (root / "config" / "schemas" / "Item.yaml").read_text(encoding="utf-8")
    assert "kind: codename" in item_text


def test_change_plan_blocks_breaking_codename_field(tmp_path: Path) -> None:
    """已声明索引的表：删 CodeName 必须被 plan 拦（曾是静默放行）。"""
    client, _ = _client_with_codename(tmp_path)
    for commands in (
        [{"type": "delete_field", "payload": {"owner": "table:Item", "name": "CodeName"}}],
        [{"type": "rename_field", "payload": {"owner": "table:Item", "old": "CodeName", "new": "DisplayName"}}],
        [{"type": "set_type", "payload": {"owner": "table:Item", "name": "CodeName", "type_text": "int32"}}],
    ):
        resp = client.post("/api/schema-workspace/change-plan", json={"commands": commands})
        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert data["plan"] is None
        assert any("codename" in issue["message"] for issue in data["issues"])


def test_change_plan_allows_delete_after_index_removed(tmp_path: Path) -> None:
    """可选语义的正道：先关掉索引再删 CodeName，必须放行。"""
    client, _ = _client_with_codename(tmp_path)
    resp = client.post(
        "/api/schema-workspace/change-plan",
        json={"commands": [
            {"type": "set_indexes", "payload": {"table": "table:Item", "indexes": []}},
            {"type": "delete_field", "payload": {"owner": "table:Item", "name": "CodeName"}},
        ]},
    )
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    # 成功分支不带 plan 键（plan: null 只在被拦分支出现）
    assert "plan" not in data
    assert data["blocked"] is False


def test_change_plan_no_spurious_rebuild_for_untouched_indexed_table(tmp_path: Path) -> None:
    """只动 Quest 时，已声明索引且未触及的 Item 不得虚报 rebuild。"""
    client, _ = _client_with_codename(tmp_path)
    resp = client.post(
        "/api/schema-workspace/change-plan",
        json={"commands": [
            {"type": "set_property", "payload": {"owner": "table:Quest", "name": "Id", "property": "comment", "value": "edited"}},
        ]},
    )
    assert resp.status_code == 200
    impacts = resp.get_json()["data"]["impacts"]
    # 未触及的表会有 Excel keep 记录，属正常；只断言没有非 keep 的 rebuild 虚报
    assert all(
        impact["table"] != "Item"
        for impact in impacts
        if impact["action"] != "keep"
    )
