"""E2E safety for the YAML-only save: baseline conflict, blocked candidate,
interrupted publish and index preservation (13.2, ported from the Apply era)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import yaml

from ct.app.canonical_workspace import CanonicalWorkspace
from ct.app.schema_workspace.candidate import candidate_hash
from ct.app.schema_workspace.commands_reducer import Command, DraftLog
from ct.storage.publication import JOURNAL_FORMAT, FilePublisher
from ct.web.app import create_app

FIXTURE = Path(__file__).parents[2] / "tests/fixtures/repository_cutover/workspace"


def _canonical_workspace(tmp_path: Path) -> Path:
    root = tmp_path / "gd"
    for section in ("config", "excel", "i18n"):
        shutil.copytree(FIXTURE / section, root / section)
    schemas = {
        "Item": {
            "table": "Item",
            "primary": "Id",
            "fields": [
                {"name": "Id", "type": "int32"},
                {"name": "Name", "type": "string", "i18n": True},
            ],
        },
    }
    for name, schema in schemas.items():
        (root / "config" / "schemas" / f"{name}.yaml").write_text(
            yaml.safe_dump(schema, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )
    for old in (root / "config" / "schemas").glob("*.yaml"):
        if old.stem not in schemas:
            old.unlink()
    for table in ("ItemType", "Quest", "UIConfig"):
        (root / "excel" / f"{table}.xlsx").unlink(missing_ok=True)
        (root / "excel" / "layout_manifests" / f"{table}.json").unlink(missing_ok=True)
    return root


def _commands_for_candidate(root: Path, commands: list[dict]) -> str:
    workspace = CanonicalWorkspace.load(root)
    log = DraftLog(workspace.resources.resources, base_indexes=dict(workspace.indexes))
    for item in commands:
        log.execute(Command(item["type"], item["payload"]))
    resources, indexes = log.current()
    return candidate_hash(resources, indexes)


def _baseline(client) -> str:
    return client.get("/api/schema-workspace").get_json()["data"]["schemaRevision"]


def test_external_data_edit_does_not_invalidate_the_draft(tmp_path: Path) -> None:
    """Excel / 译文变化不属于 Schema 基线：草稿仍然可保存。"""
    root = _canonical_workspace(tmp_path)
    client = create_app(root).test_client()
    revision = _baseline(client)
    commands = [
        {
            "type": "set_property",
            "payload": {"owner": "table:Item", "name": "Name", "property": "comment", "value": "改"},
        }
    ]
    candidate = _commands_for_candidate(root, commands)

    (root / "i18n" / "en").mkdir(parents=True, exist_ok=True)
    (root / "i18n" / "en" / "Item.json").write_text('{"1.Name": "Sword"}', encoding="utf-8")
    (root / "excel" / "Item.xlsx").write_bytes(b"external-edit")

    resp = client.post(
        "/api/schema-workspace/save",
        json={"schemaRevision": revision, "commands": commands, "candidateHash": candidate},
    )
    assert resp.status_code == 200
    assert resp.get_json()["data"]["isNoOp"] is False


def test_external_schema_edit_blocks_save_without_overwriting(tmp_path: Path) -> None:
    root = _canonical_workspace(tmp_path)
    client = create_app(root).test_client()
    revision = _baseline(client)
    commands = [
        {
            "type": "set_property",
            "payload": {"owner": "table:Item", "name": "Name", "property": "comment", "value": "改"},
        }
    ]
    candidate = _commands_for_candidate(root, commands)

    schema = root / "config" / "schemas" / "Item.yaml"
    schema.write_text(schema.read_text(encoding="utf-8") + "\n# external\n", encoding="utf-8")

    resp = client.post(
        "/api/schema-workspace/save",
        json={"schemaRevision": revision, "commands": commands, "candidateHash": candidate},
    )
    assert resp.status_code == 409
    assert resp.get_json()["conflict"]["kind"] == "schema-revision"
    assert "# external" in schema.read_text(encoding="utf-8")


def test_blocked_candidate_never_reaches_disk(tmp_path: Path) -> None:
    root = _canonical_workspace(tmp_path)
    client = create_app(root).test_client()
    revision = _baseline(client)
    commands = [
        {
            "type": "set_type",
            "payload": {"owner": "table:Item", "name": "Name", "type_text": "MissingType"},
        }
    ]
    candidate = _commands_for_candidate(root, commands)

    resp = client.post(
        "/api/schema-workspace/save",
        json={"schemaRevision": revision, "commands": commands, "candidateHash": candidate},
    )
    assert resp.status_code == 400
    assert resp.get_json()["issues"]
    assert "MissingType" not in (root / "config" / "schemas" / "Item.yaml").read_text("utf-8")


def test_interrupted_publish_is_recovered_before_the_next_save(tmp_path: Path) -> None:
    root = _canonical_workspace(tmp_path)
    client = create_app(root).test_client()
    item = root / "config" / "schemas" / "Item.yaml"
    original = item.read_bytes()

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

    revision = _baseline(client)
    commands: list[dict] = []
    candidate = _commands_for_candidate(root, commands)
    resp = client.post(
        "/api/schema-workspace/save",
        json={"schemaRevision": revision, "commands": commands, "candidateHash": candidate},
    )
    assert resp.status_code == 200
    assert resp.get_json()["data"]["recovery"]
    assert item.read_bytes() == original
    assert not publisher.journal_path.exists()


def test_persisted_index_survives_a_rename_and_untouched_tables(tmp_path: Path) -> None:
    root = _canonical_workspace(tmp_path)
    schema = root / "config" / "schemas" / "Item.yaml"
    data = yaml.safe_load(schema.read_text(encoding="utf-8"))
    data["fields"].append({"name": "CodeName", "type": "string"})
    data["indexes"] = [{"kind": "codename"}]
    schema.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")

    client = create_app(root).test_client()
    revision = _baseline(client)
    commands = [
        {"type": "rename_resource", "payload": {"old": "Item", "new": "ItemInfo"}},
    ]
    candidate = _commands_for_candidate(root, commands)
    resp = client.post(
        "/api/schema-workspace/save",
        json={"schemaRevision": revision, "commands": commands, "candidateHash": candidate},
    )
    assert resp.status_code == 200, resp.get_json()

    reloaded = CanonicalWorkspace.load(root)
    table = next(item for item in reloaded.tables if item.table == "ItemInfo")
    assert [index.kind for index in table.indexes] == ["codename"]
    assert not (root / "config" / "schemas" / "Item.yaml").exists()
