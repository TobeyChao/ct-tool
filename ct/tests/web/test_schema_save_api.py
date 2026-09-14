"""YAML-only save API tests (task 2.3)."""

from __future__ import annotations

import json
from pathlib import Path

from ct.app.canonical_workspace import CanonicalWorkspace
from ct.app.schema_workspace.snapshot import build_schema_revision
from ct.storage.publication import FilePublisher, JOURNAL_FORMAT
from ct.storage.workspace_lock import WorkspaceLock
from ct.web.app import create_app

from web_helpers import build_project


def _root(tmp_path: Path) -> Path:
    root = build_project(
        tmp_path / "gd",
        schemas=[
            {
                "table": "Item",
                "primary": "Id",
                "fields": [
                    {"name": "Id", "type": "int32"},
                    {"name": "Name", "type": "string", "comment": "旧注释"},
                ],
            },
            {
                "table": "Quest",
                "primary": "Id",
                "fields": [{"name": "Id", "type": "int32"}],
            },
        ],
    )
    (root / "excel").mkdir(parents=True, exist_ok=True)
    return root


def _client_and_base(root: Path):
    client = create_app(root).test_client()
    data = client.get("/api/schema-workspace").get_json()["data"]
    return client, data["schemaRevision"], CanonicalWorkspace.load(root)


def _commands(comment: str = "新注释"):
    return [
        {
            "type": "set_property",
            "payload": {
                "owner": "table:Item",
                "name": "Name",
                "property": "comment",
                "value": comment,
            },
        }
    ]


def _candidate_hash(client, commands) -> str:
    return client.post(
        "/api/schema-workspace/validate", json={"commands": commands}
    ).get_json()["data"]["candidateHash"]


def test_save_publishes_yaml_and_returns_new_baseline(tmp_path: Path) -> None:
    root = _root(tmp_path)
    client, revision, ws = _client_and_base(root)
    commands = _commands()
    candidate = _candidate_hash(client, commands)

    item = root / "config" / "schemas" / "Item.yaml"
    quest_before = (root / "config" / "schemas" / "Quest.yaml").read_bytes()

    resp = client.post(
        "/api/schema-workspace/save",
        json={"schemaRevision": revision, "commands": commands, "candidateHash": candidate},
    )
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["isNoOp"] is False
    assert [Path(path).name for path in data["written"]] == ["Item.yaml"]
    assert "新注释" in item.read_text(encoding="utf-8")
    assert (root / "config" / "schemas" / "Quest.yaml").read_bytes() == quest_before
    assert data["schemaRevision"] != revision
    assert data["netDiff"]["isNoOp"] is True
    assert "table:Item" in {r["resourceId"] for r in data["resources"]}


def test_save_noop_writes_nothing(tmp_path: Path) -> None:
    root = _root(tmp_path)
    client, revision, _ = _client_and_base(root)
    commands: list[dict] = []
    candidate = _candidate_hash(client, commands)
    item = root / "config" / "schemas" / "Item.yaml"
    before = item.read_bytes()

    resp = client.post(
        "/api/schema-workspace/save",
        json={"schemaRevision": revision, "commands": commands, "candidateHash": candidate},
    )
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["isNoOp"] is True
    assert data["written"] == [] and data["deleted"] == []
    assert item.read_bytes() == before
    assert not (root / ".ct" / "publish.json").exists()


def test_save_rejects_forged_candidate_hash(tmp_path: Path) -> None:
    root = _root(tmp_path)
    client, revision, _ = _client_and_base(root)
    commands = _commands()
    item = root / "config" / "schemas" / "Item.yaml"
    before = item.read_bytes()

    resp = client.post(
        "/api/schema-workspace/save",
        json={"schemaRevision": revision, "commands": commands, "candidateHash": "0" * 64},
    )
    assert resp.status_code == 409
    body = resp.get_json()
    assert body["conflict"]["kind"] == "candidate-hash"
    assert item.read_bytes() == before


def test_save_rejects_stale_schema_revision(tmp_path: Path) -> None:
    root = _root(tmp_path)
    client, revision, _ = _client_and_base(root)
    commands = _commands()
    candidate = _candidate_hash(client, commands)

    quest = root / "config" / "schemas" / "Quest.yaml"
    quest.write_text(quest.read_text(encoding="utf-8") + "\n# external edit\n", encoding="utf-8")
    item_before = (root / "config" / "schemas" / "Item.yaml").read_bytes()

    resp = client.post(
        "/api/schema-workspace/save",
        json={"schemaRevision": revision, "commands": commands, "candidateHash": candidate},
    )
    assert resp.status_code == 409
    body = resp.get_json()
    assert body["conflict"]["kind"] == "schema-revision"
    assert body["conflict"]["schemaRevision"]["members"]
    assert (root / "config" / "schemas" / "Item.yaml").read_bytes() == item_before


def test_save_rejects_structural_issues(tmp_path: Path) -> None:
    root = _root(tmp_path)
    client, revision, _ = _client_and_base(root)
    commands = [
        {
            "type": "set_type",
            "payload": {"owner": "table:Quest", "name": "Id", "type_text": "Missing"},
        }
    ]
    # The candidate hash must describe the same (broken) candidate the server builds.
    from ct.app.schema_workspace.candidate import candidate_hash
    from ct.app.schema_workspace.commands_reducer import Command, DraftLog

    ws = CanonicalWorkspace.load(root)
    log = DraftLog(ws.resources.resources, base_indexes=dict(ws.indexes))
    for item in commands:
        log.execute(Command(item["type"], item["payload"]))
    resources, indexes = log.current()
    expected = candidate_hash(resources, indexes)

    item_before = (root / "config" / "schemas" / "Item.yaml").read_bytes()
    resp = client.post(
        "/api/schema-workspace/save",
        json={"schemaRevision": revision, "commands": commands, "candidateHash": expected},
    )
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["ok"] is False
    assert body["issues"]
    assert (root / "config" / "schemas" / "Item.yaml").read_bytes() == item_before


def test_save_succeeds_without_excel_data(tmp_path: Path) -> None:
    root = _root(tmp_path)
    client, revision, _ = _client_and_base(root)
    commands = _commands("无 Excel 也能保存")
    candidate = _candidate_hash(client, commands)

    # missing workbook plus a corrupt one: schema save must not read data at all
    (root / "excel" / "Item.xlsx").write_bytes(b"definitely not a workbook")
    resp = client.post(
        "/api/schema-workspace/save",
        json={"schemaRevision": revision, "commands": commands, "candidateHash": candidate},
    )
    assert resp.status_code == 200
    assert resp.get_json()["data"]["isNoOp"] is False


def test_save_reports_busy_when_workspace_is_locked(tmp_path: Path) -> None:
    root = _root(tmp_path)
    client, revision, _ = _client_and_base(root)
    commands = _commands()
    candidate = _candidate_hash(client, commands)

    with WorkspaceLock(root):
        resp = client.post(
            "/api/schema-workspace/save",
            json={"schemaRevision": revision, "commands": commands, "candidateHash": candidate},
        )
    assert resp.status_code == 409
    body = resp.get_json()
    assert body["busy"] is True
    assert "保存" in body["error"]


def test_save_recovers_an_interrupted_publication(tmp_path: Path) -> None:
    root = _root(tmp_path)
    client, revision, _ = _client_and_base(root)
    publisher = FilePublisher(root)
    publisher.private_dir.mkdir(parents=True, exist_ok=True)
    publisher.journal_path.write_text(
        json.dumps(
            {
                "format": JOURNAL_FORMAT,
                "operation_id": "op-1",
                "root": str(root),
                "phase": "prepared",
                "allowed_dirs": [str(root)],
                "entries": [],
            }
        ),
        encoding="utf-8",
    )
    commands: list[dict] = []
    candidate = _candidate_hash(client, commands)
    resp = client.post(
        "/api/schema-workspace/save",
        json={"schemaRevision": revision, "commands": commands, "candidateHash": candidate},
    )
    assert resp.status_code == 200
    assert resp.get_json()["data"]["recovery"]
    assert not publisher.journal_path.exists()


def test_save_retry_after_conflict_succeeds(tmp_path: Path) -> None:
    root = _root(tmp_path)
    client, revision, _ = _client_and_base(root)
    commands = _commands()
    candidate = _candidate_hash(client, commands)

    quest = root / "config" / "schemas" / "Quest.yaml"
    quest.write_text(quest.read_text(encoding="utf-8") + "\n# external edit\n", encoding="utf-8")
    first = client.post(
        "/api/schema-workspace/save",
        json={"schemaRevision": revision, "commands": commands, "candidateHash": candidate},
    )
    assert first.status_code == 409

    fresh = client.get("/api/schema-workspace").get_json()["data"]["schemaRevision"]
    retry = client.post(
        "/api/schema-workspace/save",
        json={"schemaRevision": fresh, "commands": commands, "candidateHash": candidate},
    )
    assert retry.status_code == 200
    assert retry.get_json()["data"]["isNoOp"] is False
    assert build_schema_revision(CanonicalWorkspace.load(root).config).revision


def test_save_requires_both_guards(tmp_path):
    root = _root(tmp_path)
    client, revision, _ = _client_and_base(root)
    commands = _commands()
    candidate = _candidate_hash(client, commands)
    before = (root / "config/schemas/Item.yaml").read_bytes()
    for guards in ({}, {"schemaRevision": revision}, {"candidateHash": candidate}):
        response = client.post("/api/schema-workspace/save", json={"commands": commands, **guards})
        assert response.status_code == 400
    assert (root / "config/schemas/Item.yaml").read_bytes() == before


def test_save_malformed_commands_return_located_client_errors(tmp_path: Path) -> None:
    root = _root(tmp_path)
    client, revision, _ = _client_and_base(root)
    candidate = _candidate_hash(client, [])
    before = (root / "config/schemas/Item.yaml").read_bytes()
    for commands, location in (("invalid", "commands"), ([42], "commands[0]"), ([{}], "commands[0]")):
        response = client.post("/api/schema-workspace/save", json={
            "schemaRevision": revision, "candidateHash": candidate, "commands": commands,
        })
        assert response.status_code == 400
        assert response.get_json()["issues"][0]["location"] == location
    assert (root / "config/schemas/Item.yaml").read_bytes() == before


def test_save_response_never_reads_excel(tmp_path, monkeypatch):
    root = _root(tmp_path)
    client, revision, _ = _client_and_base(root)
    commands = _commands()
    candidate = _candidate_hash(client, commands)
    (root / "excel/Item.xlsx").write_bytes(b"occupied")
    original = Path.read_bytes
    def reject_excel(path):
        if path.suffix == ".xlsx":
            raise PermissionError("workbook is unreadable")
        return original(path)
    monkeypatch.setattr(Path, "read_bytes", reject_excel)
    response = client.post("/api/schema-workspace/save", json={
        "schemaRevision": revision, "candidateHash": candidate, "commands": commands,
    })
    assert response.status_code == 200
    assert "新注释" in (root / "config/schemas/Item.yaml").read_text()


def test_candidate_rejects_old_baseline(tmp_path):
    root = _root(tmp_path)
    client, revision, _ = _client_and_base(root)
    path = root / "config/schemas/Item.yaml"
    path.write_text(path.read_text() + "\n# external change\n")
    response = client.post("/api/schema-workspace/candidate", json={
        "schemaRevision": revision, "commands": _commands(),
    })
    assert response.status_code == 409
    assert response.get_json()["conflict"]["kind"] == "schema-revision"
