"""Schema Workspace Web API tests (7.5/7.6/7.7)."""

from __future__ import annotations

from pathlib import Path

from ct.app.canonical_workspace import CanonicalWorkspace
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

