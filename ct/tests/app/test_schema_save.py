"""YAML-only save plan and publication tests (tasks 2.2-2.4)."""

from __future__ import annotations

import os

import pytest

from ct.app.canonical_workspace import CanonicalWorkspace
from ct.app.schema_workspace.candidate import merge_indexes
from ct.app.schema_workspace.commands_reducer import Command, DraftLog
from ct.app.schema_workspace.save import (
    YamlSavePlan,
    plan_yaml_save,
    publish_yaml_save,
)
from ct.schema.resources import EnumItem, EnumResource, FieldDef, RecordResource

from _helpers import build_project, write_yaml


def _root(tmp_path, name: str = "gd"):
    return build_project(
        tmp_path / name,
        schemas=[
            {
                "table": "Item",
                "primary": "Id",
                "fields": [
                    {"name": "Id", "type": "int32"},
                    {"name": "Name", "type": "string", "comment": "旧注释"},
                    {"name": "Rewards", "type": "vector<DropReward>", "excel_columns": 3},
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


def _draft(workspace: CanonicalWorkspace) -> DraftLog:
    return DraftLog(workspace.resources.resources, base_indexes=dict(workspace.indexes))


def _candidate(log: DraftLog):
    resources, indexes = log.current()
    return merge_indexes(resources, indexes)


def _mtime(path) -> float:
    return os.stat(path).st_mtime_ns


# --------------------------------------------------------------------------- #
# 2.2 Diff-only file set
# --------------------------------------------------------------------------- #


def test_plan_writes_only_the_changed_resource(tmp_path) -> None:
    root = _root(tmp_path)
    workspace = CanonicalWorkspace.load(root)
    log = _draft(workspace)
    log.execute(
        Command(
            "set_property",
            {"owner": "table:Item", "name": "Name", "property": "comment", "value": "新注释"},
        )
    )
    plan = plan_yaml_save(workspace, _candidate(log))

    assert [path.name for path in plan.writes] == ["Item.yaml"]
    assert plan.deletes == ()
    assert not plan.blocked
    assert {path.name for path in plan.unchanged} == {"Quest.yaml", "DropReward.yaml"}

    quest = root / "config" / "schemas" / "Quest.yaml"
    os.utime(quest, ns=(1_600_000_000_000_000_000, 1_600_000_000_000_000_000))
    before = (quest.read_bytes(), _mtime(quest))

    result = publish_yaml_save(root, plan)
    assert [path.name for path in result.written] == ["Item.yaml"]
    assert result.deleted == ()
    assert (quest.read_bytes(), _mtime(quest)) == before
    assert "新注释" in (root / "config" / "schemas" / "Item.yaml").read_text(encoding="utf-8")


def test_plan_keeps_the_existing_source_filename(tmp_path) -> None:
    root = _root(tmp_path)
    schemas_dir = root / "config" / "schemas"
    custom = schemas_dir / "item-main.yaml"
    custom.write_text((schemas_dir / "Item.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    (schemas_dir / "Item.yaml").unlink()

    workspace = CanonicalWorkspace.load(root)
    log = _draft(workspace)
    log.execute(
        Command(
            "set_property",
            {"owner": "table:Item", "name": "Name", "property": "comment", "value": "改"},
        )
    )
    plan = plan_yaml_save(workspace, _candidate(log))
    assert [path.name for path in plan.writes] == ["item-main.yaml"]
    publish_yaml_save(root, plan)
    assert not (schemas_dir / "Item.yaml").exists()
    assert "改" in custom.read_text(encoding="utf-8")


def test_plan_honors_configured_directories(tmp_path) -> None:
    root = _root(tmp_path)
    write_yaml(
        root / "config" / "global.yaml",
        {
            "primary_lang": "zh",
            "secondary_langs": ["en"],
            "schemas_dir": "config/tables",
            "types_dir": "config/kinds",
        },
    )
    (root / "config" / "tables").mkdir(parents=True)
    (root / "config" / "kinds").mkdir(parents=True)
    for source, target in (
        (root / "config" / "schemas" / "Item.yaml", root / "config" / "tables" / "Item.yaml"),
        (root / "config" / "schemas" / "Quest.yaml", root / "config" / "tables" / "Quest.yaml"),
        (root / "config" / "types" / "DropReward.yaml", root / "config" / "kinds" / "DropReward.yaml"),
    ):
        target.write_bytes(source.read_bytes())
        source.unlink()
    for directory in (root / "config" / "schemas", root / "config" / "types"):
        directory.rmdir()

    workspace = CanonicalWorkspace.load(root)
    log = _draft(workspace)
    log.execute(
        Command(
            "set_property",
            {"owner": "table:Item", "name": "Name", "property": "comment", "value": "自定义目录"},
        )
    )
    plan = plan_yaml_save(workspace, _candidate(log))
    assert plan.writes and all(str(path).startswith(str(root / "config" / "tables")) for path in plan.writes)
    publish_yaml_save(root, plan)
    assert not (root / "config" / "schemas").exists()


def test_rename_writes_new_path_and_deletes_old(tmp_path) -> None:
    root = _root(tmp_path)
    workspace = CanonicalWorkspace.load(root)
    log = _draft(workspace)
    log.execute(Command("rename_resource", {"old": "DropReward", "new": "RewardInfo"}))
    plan = plan_yaml_save(workspace, _candidate(log))

    assert {path.name for path in plan.writes} == {"RewardInfo.yaml", "Item.yaml"}
    assert [path.name for path in plan.deletes] == ["DropReward.yaml"]

    publish_yaml_save(root, plan)
    types_dir = root / "config" / "types"
    assert not (types_dir / "DropReward.yaml").exists()
    assert "RewardInfo" in (types_dir / "RewardInfo.yaml").read_text(encoding="utf-8")
    # the referencing table was rewritten to the final name
    assert "RewardInfo" in (root / "config" / "schemas" / "Item.yaml").read_text(encoding="utf-8")


def test_deleted_resource_removes_its_yaml(tmp_path) -> None:
    root = _root(tmp_path)
    workspace = CanonicalWorkspace.load(root)
    log = _draft(workspace)
    log.execute(Command("delete_resource", {"name": "record:DropReward"}))
    log.execute(
        Command(
            "set_property",
            {"owner": "table:Item", "name": "Name", "property": "comment", "value": "去掉引用"},
        )
    )
    plan = plan_yaml_save(workspace, _candidate(log))
    assert [path.name for path in plan.deletes] == ["DropReward.yaml"]
    publish_yaml_save(root, plan)
    assert not (root / "config" / "types" / "DropReward.yaml").exists()


def test_external_file_at_a_new_target_is_a_conflict(tmp_path) -> None:
    root = _root(tmp_path)
    workspace = CanonicalWorkspace.load(root)
    log = _draft(workspace)
    log.execute(
        Command(
            "add_resource",
            {
                "kind": "record",
                "resource": RecordResource(
                    name="Extra", fields=[FieldDef(name="Amount", type="int32")]
                ),
            },
        )
    )
    target = root / "config" / "types" / "Extra.yaml"
    target.write_text("kind: record\nname: Other\nfields: []\n", encoding="utf-8")

    plan = plan_yaml_save(workspace, _candidate(log))
    assert plan.blocked
    assert "Extra.yaml" in plan.conflicts[0]
    with pytest.raises(ValueError):
        publish_yaml_save(root, plan)
    # the external file keeps its own content
    assert "Other" in target.read_text(encoding="utf-8")


def test_reformatted_yaml_is_not_rewritten(tmp_path) -> None:
    root = _root(tmp_path)
    schemas_dir = root / "config" / "schemas"
    quest = schemas_dir / "Quest.yaml"
    # Same business content, different serialization style (flow mapping + quotes).
    quest.write_text(
        'table: "Quest"\nprimary: "Id"\nfields:\n  - {name: Id, type: int32}\n',
        encoding="utf-8",
    )
    os.utime(quest, ns=(1_600_000_000_000_000_000, 1_600_000_000_000_000_000))
    before = (quest.read_bytes(), _mtime(quest))
    workspace = CanonicalWorkspace.load(root)
    log = _draft(workspace)
    plan = plan_yaml_save(workspace, _candidate(log))
    assert plan.is_empty
    assert not plan.blocked

    result = publish_yaml_save(root, plan)
    assert result.changed is False
    assert (quest.read_bytes(), _mtime(quest)) == before


def test_noop_plan_writes_no_private_state(tmp_path) -> None:
    root = _root(tmp_path)
    workspace = CanonicalWorkspace.load(root)
    log = _draft(workspace)
    plan = plan_yaml_save(workspace, _candidate(log))
    assert isinstance(plan, YamlSavePlan)
    assert plan.is_empty
    publish_yaml_save(root, plan)
    assert not (root / ".ct").exists()


def test_new_resource_is_created_in_the_configured_directory(tmp_path) -> None:
    root = _root(tmp_path)
    workspace = CanonicalWorkspace.load(root)
    log = _draft(workspace)
    log.execute(
        Command(
            "add_resource",
            {
                "kind": "enum",
                "resource": EnumResource(
                    name="ItemRarity", values=[EnumItem(name="Common", comment="普通")]
                ),
            },
        )
    )
    plan = plan_yaml_save(workspace, _candidate(log))
    assert [path.name for path in plan.writes] == ["ItemRarity.yaml"]
    publish_yaml_save(root, plan)
    reloaded = CanonicalWorkspace.load(root)
    assert "enum:ItemRarity" in {resource.resource_id for resource in reloaded.resources.resources}
