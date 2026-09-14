"""Structured resource creation over the real API (tasks 1.2-1.3)."""

from __future__ import annotations

from pathlib import Path

from ct.app.canonical_workspace import CanonicalWorkspace
from ct.app.schema_workspace.candidate import candidate_hash
from ct.app.schema_workspace.commands_reducer import Command, DraftLog
from ct.web.app import create_app

from web_helpers import build_project


def _root(tmp_path: Path) -> Path:
    return build_project(
        tmp_path / "gd",
        schemas=[
            {
                "table": "Item",
                "primary": "Id",
                "fields": [{"name": "Id", "type": "int32"}],
            }
        ],
    )


def _candidate(root: Path, commands: list[dict]) -> str:
    workspace = CanonicalWorkspace.load(root)
    log = DraftLog(workspace.resources.resources, base_indexes=dict(workspace.indexes))
    for item in commands:
        log.execute(Command(item["type"], item.get("payload") or {}))
    resources, indexes = log.current()
    return candidate_hash(resources, indexes)


def _add(kind: str, resource: dict) -> dict:
    return {"type": "add_resource", "payload": {"kind": kind, "resource": resource}}


THREE_KINDS = [
    _add(
        "enum",
        {"kind": "enum", "name": "ItemRarity", "values": [{"name": "Common", "comment": "普通"}]},
    ),
    _add(
        "record",
        {"kind": "record", "name": "DropReward", "fields": [{"name": "Min", "type": "int32"}]},
    ),
    _add(
        "table",
        {
            "table": "Quest",
            "primary": "Id",
            "fields": [
                {"name": "Id", "type": "int32"},
                {"name": "Rarity", "type": "ItemRarity"},
                {"name": "Reward", "type": "DropReward"},
            ],
        },
    ),
]


def test_create_three_kinds_in_one_draft_and_save(tmp_path: Path) -> None:
    root = _root(tmp_path)
    client = create_app(root).test_client()
    revision = client.get("/api/schema-workspace").get_json()["data"]["schemaRevision"]

    validate = client.post("/api/schema-workspace/validate", json={"commands": THREE_KINDS}).get_json()
    assert validate["data"]["valid"] is True, validate
    assert validate["data"]["netDiff"]["changedResources"] == 3

    candidate = client.post("/api/schema-workspace/candidate", json={"commands": THREE_KINDS})
    assert candidate.status_code == 200
    resources = candidate.get_json()["data"]["resources"]
    assert {"enum:ItemRarity", "record:DropReward", "table:Quest"} <= {
        item["resourceId"] for item in resources
    }

    resp = client.post(
        "/api/schema-workspace/save",
        json={
            "schemaRevision": revision,
            "commands": THREE_KINDS,
            "candidateHash": _candidate(root, THREE_KINDS),
        },
    )
    assert resp.status_code == 200, resp.get_json()
    assert sorted(Path(path).name for path in resp.get_json()["data"]["written"]) == [
        "DropReward.yaml",
        "ItemRarity.yaml",
        "Quest.yaml",
    ]
    assert (root / "config" / "types" / "ItemRarity.yaml").is_file()
    assert (root / "config" / "types" / "DropReward.yaml").is_file()
    assert (root / "config" / "schemas" / "Quest.yaml").is_file()

    reloaded = CanonicalWorkspace.load(root)
    assert {"enum:ItemRarity", "record:DropReward", "table:Quest"} <= {
        resource.resource_id for resource in reloaded.resources.resources
    }


def test_create_then_delete_is_a_noop(tmp_path: Path) -> None:
    root = _root(tmp_path)
    client = create_app(root).test_client()
    commands = [
        _add(
            "record",
            {"kind": "record", "name": "Temporary", "fields": [{"name": "Amount", "type": "int32"}]},
        ),
        {"type": "delete_resource", "payload": {"name": "record:Temporary"}},
    ]
    validate = client.post("/api/schema-workspace/validate", json={"commands": commands}).get_json()
    assert validate["data"]["valid"] is True
    assert validate["data"]["netDiff"]["isNoOp"] is True

    revision = client.get("/api/schema-workspace").get_json()["data"]["schemaRevision"]
    resp = client.post(
        "/api/schema-workspace/save",
        json={
            "schemaRevision": revision,
            "commands": commands,
            "candidateHash": _candidate(root, commands),
        },
    )
    assert resp.status_code == 200
    assert resp.get_json()["data"]["isNoOp"] is True
    assert not (root / "config" / "types" / "Temporary.yaml").exists()


BAD_PAYLOADS = [
    (_add("struct", {"name": "X"}), "commands[0].payload.kind"),
    (
        _add("enum", {"kind": "record", "name": "X", "values": [{"name": "A", "comment": ""}]}),
        "commands[0].payload.resource.kind",
    ),
    (_add("table", {"primary": "Id", "fields": []}), "commands[0].payload.resource.table"),
    (
        _add("table", {"table": "X", "primary": "Id", "fields": [{"name": "Id", "type": "int32", "oops": 1}]}),
        "commands[0].payload.resource.fields[0].oops",
    ),
    (
        _add("enum", {"kind": "enum", "name": "E", "values": ["Common"]}),
        "commands[0].payload.resource",
    ),
    (
        _add("table", {"table": "X", "primary": "Id", "fields": [{"name": "Id", "type": "enum"}]}),
        "commands[0].payload.resource",
    ),
    (_add("enum", {}), "commands[0].payload.resource.name"),
]


def test_malformed_payloads_are_client_errors_with_locations(tmp_path: Path) -> None:
    root = _root(tmp_path)
    client = create_app(root).test_client()

    for payload, expected_location in BAD_PAYLOADS:
        validate = client.post("/api/schema-workspace/validate", json={"commands": [payload]})
        body = validate.get_json()
        assert validate.status_code == 200
        assert body["data"]["valid"] is False, payload
        issue = body["data"]["issues"][0]
        assert issue["location"] == expected_location, (payload, issue)
        assert issue["message"]

        candidate = client.post("/api/schema-workspace/candidate", json={"commands": [payload]})
        assert candidate.status_code == 400, payload
        assert candidate.get_json()["issues"][0]["location"] == expected_location

        save = client.post(
            "/api/schema-workspace/save",
            json={"schemaRevision": client.get("/api/schema-workspace").get_json()["data"]["schemaRevision"], "commands": [payload], "candidateHash": "invalid-candidate"},
        )
        assert save.status_code == 400, payload
        assert save.get_json()["issues"][0]["location"] == expected_location

    assert sorted(path.name for path in (root / "config" / "types").glob("*.yaml")) == []
    assert sorted(path.name for path in (root / "config" / "schemas").glob("*.yaml")) == ["Item.yaml"]


def test_unknown_command_type_is_reported_not_silently_dropped(tmp_path: Path) -> None:
    root = _root(tmp_path)
    client = create_app(root).test_client()
    resp = client.post(
        "/api/schema-workspace/validate",
        json={"commands": [{"type": "frobnicate", "payload": {}}]},
    )
    body = resp.get_json()
    assert body["data"]["valid"] is False
    assert body["data"]["issues"][0]["location"] == "commands[0]"
    assert "frobnicate" in body["data"]["issues"][0]["message"]
