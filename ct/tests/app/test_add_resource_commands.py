"""Draft command protocol for structured resource creation (tasks 1.2-1.3)."""

from __future__ import annotations

from pathlib import Path

import pytest

from ct.app.canonical_workspace import CanonicalWorkspace
from ct.app.schema_workspace.commands_reducer import Command, DraftLog
from ct.schema.resource_repository import ResourceDecodeError
from ct.schema.resources import EnumResource, RecordResource, TableResource

from _helpers import build_project


def _workspace(tmp_path: Path) -> CanonicalWorkspace:
    root = build_project(
        tmp_path / "gd",
        schemas=[
            {
                "table": "Item",
                "primary": "Id",
                "fields": [{"name": "Id", "type": "int32"}],
            }
        ],
    )
    return CanonicalWorkspace.load(root)


def _add(kind: str, resource: dict) -> Command:
    return Command("add_resource", {"kind": kind, "resource": resource})


def test_decodes_all_three_kinds(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    log = DraftLog(workspace.resources.resources, base_indexes=dict(workspace.indexes))
    log.execute(
        _add(
            "enum",
            {"kind": "enum", "name": "ItemRarity", "values": [{"name": "Common", "comment": "普通"}]},
        )
    )
    log.execute(
        _add(
            "record",
            {"kind": "record", "name": "DropReward", "fields": [{"name": "Min", "type": "int32"}]},
        )
    )
    log.execute(
        _add(
            "table",
            {"table": "Quest", "primary": "Id", "fields": [{"name": "Id", "type": "int32"}]},
        )
    )
    resources, _indexes = log.current()
    by_id = {resource.resource_id: resource for resource in resources}
    assert isinstance(by_id["enum:ItemRarity"], EnumResource)
    assert isinstance(by_id["record:DropReward"], RecordResource)
    assert isinstance(by_id["table:Quest"], TableResource)
    # 命令历史只存原始 JSON，模型只存在于重放内部
    assert log.commands[-1].payload["resource"]["table"] == "Quest"


def test_table_indexes_are_initialized_with_the_resource(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    log = DraftLog(workspace.resources.resources, base_indexes=dict(workspace.indexes))
    log.execute(
        _add(
            "table",
            {
                "table": "ItemType",
                "primary": "Id",
                "fields": [
                    {"name": "Id", "type": "int32"},
                    {"name": "CodeName", "type": "string"},
                ],
                "indexes": [{"kind": "codename"}],
            },
        )
    )
    _resources, indexes = log.current()
    assert [index.kind for index in indexes["table:ItemType"]] == ["codename"]

    # 新增后编辑索引：清空再声明，草稿索引状态跟随
    log.execute(Command("set_indexes", {"table": "table:ItemType", "indexes": []}))
    _resources, cleared = log.current()
    assert cleared["table:ItemType"] == ()
    log.execute(Command("set_indexes", {"table": "table:ItemType", "indexes": [{"kind": "codename"}]}))
    _resources, restored = log.current()
    assert [index.kind for index in restored["table:ItemType"]] == ["codename"]


def test_duplicate_creation_is_rejected(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    log = DraftLog(workspace.resources.resources, base_indexes=dict(workspace.indexes))
    payload = {"kind": "enum", "name": "ItemRarity", "values": [{"name": "Common", "comment": ""}]}
    log.execute(_add("enum", payload))
    log.execute(_add("enum", payload))
    # DraftLog 是惰性的：重放（current）时才报重复
    with pytest.raises(ValueError, match="已存在"):
        log.current()

    log = DraftLog(workspace.resources.resources, base_indexes=dict(workspace.indexes))
    log.execute(
        _add(
            "table",
            {"table": "Item", "primary": "Id", "fields": [{"name": "Id", "type": "int32"}]},
        )
    )
    with pytest.raises(ValueError, match="已存在"):
        log.current()


def test_creation_replays_and_undoes(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    log = DraftLog(workspace.resources.resources, base_indexes=dict(workspace.indexes))
    log.execute(
        _add(
            "record",
            {"kind": "record", "name": "Reward", "fields": [{"name": "Amount", "type": "int32"}]},
        )
    )
    log.execute(
        Command(
            "set_property",
            {"owner": "record:Reward", "name": "Amount", "property": "comment", "value": "数量"},
        )
    )
    before_undo = {resource.resource_id for resource in log.current()[0]}
    assert "record:Reward" in before_undo

    log.undo()  # 撤销 set_property
    log.undo()  # 撤销创建
    assert "record:Reward" not in {resource.resource_id for resource in log.current()[0]}
    log.redo()
    log.redo()
    resources, _ = log.current()
    reward = next(resource for resource in resources if resource.resource_id == "record:Reward")
    assert reward.fields[0].comment == "数量"


def test_malformed_payloads_report_field_locations(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    log = DraftLog(workspace.resources.resources, base_indexes=dict(workspace.indexes))
    cases = [
        ({"kind": "struct", "resource": {"name": "X"}}, "kind"),
        ({"kind": "enum", "resource": {"kind": "record", "name": "X", "values": []}}, "resource.kind"),
        ({"kind": "table", "resource": {"primary": "Id", "fields": []}}, "resource.table"),
        ({"kind": "record", "resource": {"kind": "record", "fields": []}}, "resource.name"),
        (
            {
                "kind": "table",
                "resource": {
                    "table": "X",
                    "primary": "Id",
                    "fields": [{"name": "Id", "type": "int32", "oops": 1}],
                },
            },
            "resource.fields[0].oops",
        ),
        (
            {"kind": "enum", "resource": {"kind": "enum", "name": "E", "values": ["Common"]}},
            "resource",
        ),
        (
            {
                "kind": "table",
                "resource": {"table": "X", "primary": "Id", "fields": [{"name": "Id", "type": "enum"}]},
            },
            "resource",
        ),
    ]
    for payload, expected_location in cases:
        probe = DraftLog(workspace.resources.resources, base_indexes=dict(workspace.indexes))
        probe.execute(Command("add_resource", payload))
        with pytest.raises(ResourceDecodeError) as excinfo:
            probe.current()
        assert excinfo.value.location == expected_location, payload
        assert excinfo.value.message


def test_missing_resource_key_is_rejected(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    log = DraftLog(workspace.resources.resources, base_indexes=dict(workspace.indexes))
    log.execute(Command("add_resource", {"kind": "enum"}))
    with pytest.raises(ResourceDecodeError, match="缺少 resource"):
        log.current()
