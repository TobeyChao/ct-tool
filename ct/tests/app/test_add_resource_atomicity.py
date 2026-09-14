"""Transactional creation of several resources (task 2.4)."""

from __future__ import annotations

from pathlib import Path

import pytest

from ct.app.canonical_workspace import CanonicalWorkspace
from ct.app.schema_workspace.candidate import candidate_hash, merge_indexes
from ct.app.schema_workspace.commands_reducer import Command, DraftLog
from ct.app.schema_workspace.save import plan_yaml_save, publish_yaml_save
from ct.storage.publication import PHASE_PUBLISHING, FilePublisher, PublicationError
from ct.web.app import create_app

from _helpers import build_project


def _root(tmp_path: Path) -> Path:
    root = build_project(
        tmp_path / "gd",
        schemas=[
            {"table": "Item", "primary": "Id", "fields": [{"name": "Id", "type": "int32"}]}
        ],
    )
    for relative, payload in (
        ("excel/Item.xlsx", b"workbook"),
        ("i18n/source/Item.json", b'{"1.Id": "1"}'),
        ("output/json/Item_zh.json", b'{"Items": []}'),
        ("cache/state.json", b'{"excel_hashes": {}}'),
    ):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    return root


def _commands() -> list[Command]:
    return [
        Command(
            "add_resource",
            {
                "kind": "enum",
                "resource": {
                    "kind": "enum",
                    "name": "ItemRarity",
                    "values": [{"name": "Common", "comment": "普通"}],
                },
            },
        ),
        Command(
            "add_resource",
            {
                "kind": "record",
                "resource": {
                    "kind": "record",
                    "name": "DropReward",
                    "fields": [{"name": "Min", "type": "int32"}],
                },
            },
        ),
        Command(
            "add_resource",
            {
                "kind": "table",
                "resource": {
                    "table": "Quest",
                    "primary": "Id",
                    "fields": [{"name": "Id", "type": "int32"}],
                },
            },
        ),
    ]


def _business_files(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for directory in ("excel", "i18n", "output", "cache")
        for path in sorted((root / directory).rglob("*"))
        if path.is_file()
    }


def _log(workspace: CanonicalWorkspace, commands: list[Command]) -> DraftLog:
    log = DraftLog(workspace.resources.resources, base_indexes=dict(workspace.indexes))
    for command in commands:
        log.execute(command)
    return log


def test_failed_publish_after_first_new_file_rolls_everything_back(tmp_path: Path) -> None:
    root = _root(tmp_path)
    workspace = CanonicalWorkspace.load(root)
    log = _log(workspace, _commands())
    plan = plan_yaml_save(workspace, merge_indexes(*log.current()))
    assert len(plan.writes) == 3
    item_before = (root / "config" / "schemas" / "Item.yaml").read_bytes()
    business_before = _business_files(root)

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

    types_dir = root / "config" / "types"
    assert not (types_dir / "ItemRarity.yaml").exists()
    assert not (types_dir / "DropReward.yaml").exists()
    assert not (root / "config" / "schemas" / "Quest.yaml").exists()
    assert (root / "config" / "schemas" / "Item.yaml").read_bytes() == item_before
    assert _business_files(root) == business_before
    assert not FilePublisher(root).journal_path.exists()


def test_crash_after_first_new_file_recovers_and_is_idempotent(tmp_path: Path) -> None:
    root = _root(tmp_path)
    workspace = CanonicalWorkspace.load(root)
    log = _log(workspace, _commands())
    plan = plan_yaml_save(workspace, merge_indexes(*log.current()))
    business_before = _business_files(root)

    published = {"count": 0}
    original_apply = FilePublisher._apply
    original_rollback = FilePublisher._rollback

    def crashing_apply(self, entry):  # noqa: ANN001 - test seam
        published["count"] += 1
        if published["count"] > 1:
            raise KeyboardInterrupt("simulated process death")
        return original_apply(self, entry)

    FilePublisher._apply = crashing_apply
    FilePublisher._rollback = lambda self, staging: None  # 崩溃：什么都不回滚
    try:
        with pytest.raises(KeyboardInterrupt):
            publish_yaml_save(root, plan)
    finally:
        FilePublisher._apply = original_apply
        FilePublisher._rollback = original_rollback

    publisher = FilePublisher(root)
    journal = publisher.read_journal()
    assert journal is not None and journal.phase == PHASE_PUBLISHING

    assert publisher.recover()
    types_dir = root / "config" / "types"
    assert not (types_dir / "ItemRarity.yaml").exists()
    assert not (types_dir / "DropReward.yaml").exists()
    assert not (root / "config" / "schemas" / "Quest.yaml").exists()
    assert _business_files(root) == business_before
    # 幂等：再恢复一次什么都不做，现场保持不变
    assert publisher.recover() is None
    assert not (types_dir / "ItemRarity.yaml").exists()

    # 恢复后同一个计划可以正常发布
    result = publish_yaml_save(root, plan)
    assert len(result.written) == 3
    assert (types_dir / "ItemRarity.yaml").is_file()


def test_save_api_reports_publish_failure_without_leaving_new_files(tmp_path: Path) -> None:
    root = _root(tmp_path)
    client = create_app(root).test_client()
    revision = client.get("/api/schema-workspace").get_json()["data"]["schemaRevision"]
    payload_commands = [
        {
            "type": command.type,
            "payload": command.payload,
        }
        for command in _commands()
    ]
    workspace = CanonicalWorkspace.load(root)
    log = _log(workspace, _commands())
    resources, indexes = log.current()
    candidate = candidate_hash(resources, indexes)

    original_apply = FilePublisher._apply

    def failing_apply(self, entry):  # noqa: ANN001 - test seam
        if not (Path(entry.path).parent.name == "types"):
            return original_apply(self, entry)
        raise OSError("simulated failure on new resource")

    FilePublisher._apply = failing_apply
    try:
        resp = client.post(
            "/api/schema-workspace/save",
            json={
                "schemaRevision": revision,
                "commands": payload_commands,
                "candidateHash": candidate,
            },
        )
    finally:
        FilePublisher._apply = original_apply

    assert resp.status_code == 500
    assert "保存发布失败" in resp.get_json()["error"]
    assert not (root / "config" / "types" / "ItemRarity.yaml").exists()
    assert not (root / "config" / "schemas" / "Quest.yaml").exists()
    assert not FilePublisher(root).journal_path.exists()
