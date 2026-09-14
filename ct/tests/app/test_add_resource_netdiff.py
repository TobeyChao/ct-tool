"""Net difference for created resources (task 2.2)."""

from __future__ import annotations

from pathlib import Path

from ct.app.canonical_workspace import CanonicalWorkspace
from ct.app.schema_workspace.candidate import merge_indexes
from ct.app.schema_workspace.commands_reducer import Command, DraftLog
from ct.app.schema_workspace.netdiff import compute_net_diff
from ct.app.schema_workspace.save import plan_yaml_save

from _helpers import build_project


def _workspace(tmp_path: Path) -> CanonicalWorkspace:
    root = build_project(
        tmp_path / "gd",
        schemas=[
            {
                "table": "Item",
                "primary": "Id",
                "fields": [
                    {"name": "Id", "type": "int32"},
                    {"name": "Name", "type": "string"},
                ],
            }
        ],
    )
    return CanonicalWorkspace.load(root)


def _log(workspace: CanonicalWorkspace) -> DraftLog:
    return DraftLog(workspace.resources.resources, base_indexes=dict(workspace.indexes))


def _add(kind: str, resource: dict) -> Command:
    return Command("add_resource", {"kind": kind, "resource": resource})


def _diff(workspace: CanonicalWorkspace, log: DraftLog):
    resources, indexes = log.current()
    return compute_net_diff(
        (workspace.resources.resources, dict(workspace.indexes)),
        (resources, indexes),
        log.commands,
        cursor=log.cursor,
    )


def test_create_edit_rename_is_one_addition_with_the_final_name(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    log = _log(workspace)
    log.execute(
        _add(
            "record",
            {"kind": "record", "name": "Reward", "fields": [{"name": "Amount", "type": "int32"}]},
        )
    )
    log.execute(
        Command(
            "add_field",
            {"owner": "record:Reward", "field": {"name": "Weight", "type": "float"}},
        )
    )
    log.execute(Command("rename_resource", {"old": "Reward", "new": "DropReward"}))

    diff = _diff(workspace, log)
    assert diff.changed_resources == 1
    change = diff.changes[0]
    assert (change.change, change.name) == ("added", "DropReward")

    plan = plan_yaml_save(workspace, merge_indexes(*log.current()))
    assert [path.name for path in plan.writes] == ["DropReward.yaml"]


def test_create_then_delete_is_a_noop_that_writes_nothing(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    log = _log(workspace)
    log.execute(
        _add(
            "record",
            {"kind": "record", "name": "Temporary", "fields": [{"name": "Amount", "type": "int32"}]},
        )
    )
    log.execute(Command("delete_resource", {"name": "record:Temporary"}))

    diff = _diff(workspace, log)
    assert diff.is_empty
    plan = plan_yaml_save(workspace, merge_indexes(*log.current()))
    assert plan.is_empty
    # 历史仍然保留，可撤销回来
    assert len(log.commands) == 2
    log.undo()
    assert not _diff(workspace, log).is_empty


def test_rename_round_trip_of_a_creation_is_still_one_addition(tmp_path: Path) -> None:
    """往返改名只对**已有**资源归零；新建的资源本身就是净新增。"""
    workspace = _workspace(tmp_path)
    log = _log(workspace)
    log.execute(
        _add(
            "enum",
            {"kind": "enum", "name": "Rarity", "values": [{"name": "Common", "comment": ""}]},
        )
    )
    log.execute(Command("rename_resource", {"old": "Rarity", "new": "ItemRarity"}))
    log.execute(Command("rename_resource", {"old": "ItemRarity", "new": "Rarity"}))
    diff = _diff(workspace, log)
    assert [(change.change, change.name) for change in diff.changes] == [("added", "Rarity")]

    # 已有资源（Item）的往返改名才归零
    log.execute(Command("rename_resource", {"old": "Item", "new": "ItemInfo"}))
    log.execute(Command("rename_resource", {"old": "ItemInfo", "new": "Item"}))
    assert [change.name for change in _diff(workspace, log).changes] == ["Rarity"]


def test_existing_resource_referencing_a_new_type_counts_separately(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    log = _log(workspace)
    log.execute(
        _add(
            "enum",
            {"kind": "enum", "name": "ItemRarity", "values": [{"name": "Common", "comment": ""}]},
        )
    )
    log.execute(
        Command(
            "set_type",
            {"owner": "table:Item", "name": "Name", "type_text": "ItemRarity"},
        )
    )
    diff = _diff(workspace, log)
    assert diff.changed_resources == 2
    by_change = {change.change: change for change in diff.changes}
    assert by_change["added"].name == "ItemRarity"
    assert by_change["modified"].name == "Item"


def test_new_table_with_index_is_planned_with_its_declaration(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    log = _log(workspace)
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
    resources, indexes = log.current()
    merged = merge_indexes(resources, indexes)
    plan = plan_yaml_save(workspace, merged)
    payload = plan.writes[next(iter(plan.writes))]
    assert "indexes" in payload.decode("utf-8")
    assert "codename" in payload.decode("utf-8")
