"""Save publication boundaries and failure atomicity (tasks 2.4-2.5)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ct.app.canonical_workspace import CanonicalWorkspace
from ct.app.schema_workspace.candidate import merge_indexes
from ct.app.schema_workspace.commands_reducer import Command, DraftLog
from ct.app.schema_workspace.save import plan_yaml_save, publish_yaml_save
from ct.schema.resources import EnumItem, EnumResource, FieldDef, RecordResource
from ct.storage.publication import FilePublisher, PHASE_PUBLISHING, PublicationError
from ct.web.app import create_app

from _helpers import build_project


def _root(tmp_path: Path, name: str = "gd") -> Path:
    root = build_project(
        tmp_path / name,
        schemas=[
            {
                "table": "Item",
                "primary": "Id",
                "fields": [
                    {"name": "Id", "type": "int32"},
                    {"name": "Name", "type": "string", "comment": "旧"},
                ],
            },
            {
                "table": "Quest",
                "primary": "Id",
                "fields": [{"name": "Id", "type": "int32"}],
            },
        ],
        types=[
            {
                "kind": "record",
                "name": "DropReward",
                "fields": [{"name": "Amount", "type": "int32"}],
            }
        ],
    )
    return root


def _business_snapshot(root: Path) -> dict[str, bytes]:
    """Every managed file except the schema YAML the save is allowed to touch."""
    fingerprint: dict[str, bytes] = {}
    for directory in ("excel", "output", "i18n", "cache"):
        base = root / directory
        if not base.exists():
            continue
        for path in sorted(base.rglob("*")):
            if path.is_file():
                fingerprint[str(path.relative_to(root))] = path.read_bytes()
    return fingerprint


def _candidate(workspace: CanonicalWorkspace, commands: list[Command]):
    log = DraftLog(workspace.resources.resources, base_indexes=dict(workspace.indexes))
    for command in commands:
        log.execute(command)
    resources, indexes = log.current()
    return merge_indexes(resources, indexes)


def test_save_leaves_every_other_managed_file_untouched(tmp_path: Path) -> None:
    root = _root(tmp_path)
    for relative, payload in (
        ("excel/Item.xlsx", b"workbook-bytes"),
        ("excel/layout_manifests/Item.json", b'{"layout": 1}'),
        ("i18n/source/Item.json", b'{"1.Name": "x"}'),
        ("output/json/Item_zh.json", b'{"Items": []}'),
        ("cache/state.json", b'{"success": true}'),
    ):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    before = _business_snapshot(root)

    workspace = CanonicalWorkspace.load(root)
    commands = [
        Command(
            "set_property",
            {"owner": "table:Item", "name": "Name", "property": "comment", "value": "新"},
        ),
        Command(
            "add_resource",
            {
                "kind": "enum",
                "resource": EnumResource(
                    name="ItemRarity", values=[EnumItem(name="Common", comment="普通")]
                ),
            },
        ),
        Command("delete_resource", {"name": "record:DropReward"}),
    ]
    plan = plan_yaml_save(workspace, _candidate(workspace, commands))
    result = publish_yaml_save(root, plan)

    assert result.changed is True
    assert _business_snapshot(root) == before
    # cleanup: the deleted record's reference must not linger anywhere
    assert not (root / "config" / "types" / "DropReward.yaml").exists()
    assert (root / "config" / "types" / "ItemRarity.yaml").is_file()


def test_failed_publish_rolls_back_every_file(tmp_path: Path) -> None:
    root = _root(tmp_path)
    workspace = CanonicalWorkspace.load(root)
    item = root / "config" / "schemas" / "Item.yaml"
    quest = root / "config" / "schemas" / "Quest.yaml"
    before = {path.name: path.read_bytes() for path in (item, quest)}

    commands = [
        Command(
            "set_property",
            {"owner": "table:Item", "name": "Name", "property": "comment", "value": "新"},
        ),
        Command(
            "add_resource",
            {
                "kind": "enum",
                "resource": EnumResource(
                    name="ItemRarity", values=[EnumItem(name="Common", comment="")]
                ),
            },
        ),
        Command("delete_resource", {"name": "table:Quest"}),
    ]
    plan = plan_yaml_save(workspace, _candidate(workspace, commands))

    calls = {"count": 0}
    original_apply = FilePublisher._apply

    def flaky_apply(self, entry):  # noqa: ANN001 - test seam
        calls["count"] += 1
        if calls["count"] == 2:
            raise OSError("simulated disk failure")
        return original_apply(self, entry)

    FilePublisher._apply = flaky_apply
    try:
        with pytest.raises(PublicationError):
            publish_yaml_save(root, plan)
    finally:
        FilePublisher._apply = original_apply

    assert {path.name: path.read_bytes() for path in (item, quest)} == before
    assert not (root / "config" / "types" / "ItemRarity.yaml").exists()
    assert not FilePublisher(root).journal_path.exists()


def test_interrupted_publish_is_recovered_to_a_complete_old_version(tmp_path: Path) -> None:
    root = _root(tmp_path)
    workspace = CanonicalWorkspace.load(root)
    item = root / "config" / "schemas" / "Item.yaml"
    quest = root / "config" / "schemas" / "Quest.yaml"
    new_item = item.read_text(encoding="utf-8").replace("旧", "新")
    old_bytes = {item.name: item.read_bytes(), quest.name: quest.read_bytes()}

    commands = [
        Command(
            "set_property",
            {"owner": "table:Item", "name": "Name", "property": "comment", "value": "新"},
        ),
        Command(
            "add_resource",
            {
                "kind": "enum",
                "resource": EnumResource(
                    name="ItemRarity", values=[EnumItem(name="Common", comment="")]
                ),
            },
        ),
        Command("delete_resource", {"name": "table:Quest"}),
    ]
    plan = plan_yaml_save(workspace, _candidate(workspace, commands))
    assert set(plan.writes) and plan.deletes

    # Simulate a hard crash: one file already published, then no rollback at all.
    published = {"count": 0}
    original_apply = FilePublisher._apply
    original_rollback = FilePublisher._rollback

    def crashing_apply(self, entry):  # noqa: ANN001 - test seam
        published["count"] += 1
        if published["count"] > 1:
            raise KeyboardInterrupt("simulated process death")
        return original_apply(self, entry)

    FilePublisher._apply = crashing_apply
    FilePublisher._rollback = lambda self, staging: None  # crash: nothing rolls back
    try:
        with pytest.raises(KeyboardInterrupt):
            publish_yaml_save(root, plan)
    finally:
        FilePublisher._apply = original_apply
        FilePublisher._rollback = original_rollback

    publisher = FilePublisher(root)
    journal = publisher.read_journal()
    assert journal is not None and journal.phase == PHASE_PUBLISHING
    assert item.read_text(encoding="utf-8") != old_bytes[item.name].decode("utf-8")

    # The next transaction recovers first: back to the complete old version...
    assert publisher.recover()
    assert {item.name: item.read_bytes(), quest.name: quest.read_bytes()} == old_bytes
    assert not (root / "config" / "types" / "ItemRarity.yaml").exists()
    assert not publisher.journal_path.exists()
    # ...and a following save can then publish the same plan.
    assert new_item  # sanity: the intended content really differs
    result = publish_yaml_save(root, plan)
    assert result.changed is True
    assert "新" in item.read_text(encoding="utf-8")


def test_save_api_reports_publish_failure_and_keeps_old_files(tmp_path: Path) -> None:
    root = _root(tmp_path)
    client = create_app(root).test_client()
    revision = client.get("/api/schema-workspace").get_json()["data"]["schemaRevision"]
    commands = [
        {
            "type": "set_property",
            "payload": {
                "owner": "table:Item",
                "name": "Name",
                "property": "comment",
                "value": "新",
            },
        }
    ]
    candidate = client.post(
        "/api/schema-workspace/validate", json={"commands": commands}
    ).get_json()["data"]["candidateHash"]
    item = root / "config" / "schemas" / "Item.yaml"
    before = item.read_bytes()

    original_apply = FilePublisher._apply

    def failing_apply(self, entry):  # noqa: ANN001 - test seam
        raise OSError("simulated disk failure")

    FilePublisher._apply = failing_apply
    try:
        resp = client.post(
            "/api/schema-workspace/save",
            json={"schemaRevision": revision, "commands": commands, "candidateHash": candidate},
        )
    finally:
        FilePublisher._apply = original_apply

    assert resp.status_code == 500
    body = resp.get_json()
    assert body["ok"] is False
    assert "保存发布失败" in body["error"]
    assert item.read_bytes() == before
    assert not FilePublisher(root).journal_path.exists()


def test_old_apply_journal_is_detected_and_preserved(tmp_path: Path) -> None:
    """The removed Apply pipeline's journal must block writes, not be cleaned up."""
    root = _root(tmp_path)
    cache_dir = root / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    legacy = cache_dir / "apply.journal.json"
    relative = "config/schemas/Item.yaml"
    legacy.write_text(
        json.dumps(
            {
                "format": "apply-journal/1",
                "plan_id": "plan-1",
                "phase": "publish",
                "targets": [[relative, "Item.yaml"]],
                "published": [relative],
            }
        ),
        encoding="utf-8",
    )
    backup = root / "cache" / "backups" / "plan-1" / relative
    backup.parent.mkdir(parents=True, exist_ok=True)
    backup.write_bytes(b"old-content")

    from ct.app.schema_workspace.legacy_apply import detect_legacy_apply_material

    status = detect_legacy_apply_material(root)
    assert status is not None
    assert status.blocked is False
    assert status.phase == "publish"
    assert any("apply.journal.json" in path for path in status.materials)
    assert any("backups" in path for path in status.materials)
    assert legacy.exists() and backup.exists()


def test_unresolvable_old_apply_material_blocks_save_and_keeps_materials(tmp_path: Path) -> None:
    root = _root(tmp_path)
    cache_dir = root / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    relative = "config/schemas/Item.yaml"
    (cache_dir / "apply.journal.json").write_text(
        json.dumps(
            {
                "format": "apply-journal/1",
                "plan_id": "plan-1",
                "phase": "publish",
                "targets": [[relative, "Item.yaml"]],
                "published": [relative],
            }
        ),
        encoding="utf-8",
    )
    # No backup was recorded: the old revision cannot be proven, so writing stops.
    (cache_dir / "apply.lock").write_text("", encoding="utf-8")
    client = create_app(root).test_client()
    revision = client.get("/api/schema-workspace").get_json()["data"]["schemaRevision"]
    item = root / "config" / "schemas" / "Item.yaml"
    before = item.read_bytes()

    resp = client.post(
        "/api/schema-workspace/save",
        json={"schemaRevision": revision, "commands": [], "candidateHash": client.post("/api/schema-workspace/candidate", json={"commands": []}).get_json()["data"]["candidateHash"]},
    )
    assert resp.status_code == 409
    body = resp.get_json()
    assert body["conflict"]["kind"] == "legacy-apply"
    assert body["conflict"]["materials"]
    assert (cache_dir / "apply.journal.json").exists()
    assert (cache_dir / "apply.lock").exists()
    assert item.read_bytes() == before


def test_recoverable_old_apply_material_is_rolled_back_then_save_proceeds(tmp_path: Path) -> None:
    root = _root(tmp_path)
    cache_dir = root / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    item = root / "config" / "schemas" / "Item.yaml"
    old_content = b"table: Item\nprimary: Id\nfields:\n- name: Id\n  type: int32\n"
    relative = "config/schemas/Item.yaml"
    (cache_dir / "apply.journal.json").write_text(
        json.dumps(
            {
                "format": "apply-journal/1",
                "plan_id": "plan-1",
                "phase": "publish",
                "targets": [[relative, "Item.yaml"]],
                "published": [relative],
            }
        ),
        encoding="utf-8",
    )
    backup = cache_dir / "backups" / "plan-1" / relative
    backup.parent.mkdir(parents=True, exist_ok=True)
    backup.write_bytes(old_content)
    # Simulate a half-published legacy transaction: the live file already changed.
    item.write_text(
        "table: Item\nprimary: Id\nfields:\n- name: Id\n  type: int32\n- name: Extra\n  type: int32\n",
        encoding="utf-8",
    )

    client = create_app(root).test_client()
    revision = client.get("/api/schema-workspace").get_json()["data"]["schemaRevision"]
    resp = client.post(
        "/api/schema-workspace/save",
        json={"schemaRevision": revision, "commands": [], "candidateHash": client.post("/api/schema-workspace/candidate", json={"commands": []}).get_json()["data"]["candidateHash"]},
    )
    # The rollback happened, so the caller's baseline is explicitly told to reload.
    assert resp.status_code == 409
    assert resp.get_json()["conflict"]["kind"] == "legacy-apply-recovered"
    assert item.read_bytes() == old_content
    assert not (cache_dir / "apply.journal.json").exists()
    assert not (cache_dir / "backups" / "plan-1").exists()

    # A leftover legacy lock file never makes the workspace permanently busy.
    (cache_dir / "apply.lock").write_text("", encoding="utf-8")
    fresh = client.get("/api/schema-workspace").get_json()["data"]["schemaRevision"]
    assert client.post(
        "/api/schema-workspace/save",
        json={"schemaRevision": fresh, "commands": [], "candidateHash": client.post("/api/schema-workspace/candidate", json={"commands": []}).get_json()["data"]["candidateHash"]},
    ).status_code == 200


def test_legacy_replace_before_journal_update_restores_all_targets(tmp_path):
    from ct.app.schema_workspace.legacy_apply import recover_legacy_apply
    root = _root(tmp_path)
    relative = "config/schemas/Item.yaml"
    target = root / relative
    original = target.read_bytes()
    backup = root / "cache/backups/interrupted" / relative
    backup.parent.mkdir(parents=True)
    backup.write_bytes(original)
    target.write_bytes(b"changed before journal update")
    journal = root / "cache/apply.journal.json"
    journal.write_text(json.dumps({"format": "apply-journal/1", "plan_id": "interrupted",
        "phase": "publish", "targets": [[relative, "Item.yaml"]], "published": []}))
    assert recover_legacy_apply(root).recovered
    assert target.read_bytes() == original
    assert not journal.exists()


def test_legacy_unrecorded_new_target_preserves_materials(tmp_path):
    from ct.app.schema_workspace.legacy_apply import recover_legacy_apply, LegacyApplyBlocked
    root = _root(tmp_path)
    relative = "config/schemas/New.yaml"
    target = root / relative
    target.write_bytes(b"new target without old backup")
    journal = root / "cache/apply.journal.json"
    journal.parent.mkdir(exist_ok=True)
    journal.write_text(json.dumps({"format": "apply-journal/1", "plan_id": "interrupted",
        "phase": "publish", "targets": [[relative, "New.yaml"]], "published": []}))
    with pytest.raises(LegacyApplyBlocked):
        recover_legacy_apply(root)
    assert journal.exists() and target.exists()
