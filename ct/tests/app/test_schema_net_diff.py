"""Schema baseline revision and net-difference tests (tasks 1.1-1.3)."""

from __future__ import annotations

import pytest

from ct.app.canonical_workspace import CanonicalWorkspace
from ct.app.schema_workspace.candidate import candidate_hash, validate_candidate
from ct.app.schema_workspace.commands_reducer import Command, DraftLog
from ct.app.schema_workspace.netdiff import compute_net_diff, rename_identity
from ct.app.schema_workspace.snapshot import (
    build_schema_revision,
    capture_schema_sources,
)
from ct.schema.indexes import QueryIndex
from ct.schema.resources import FieldDef, RecordResource

from _helpers import build_project


def _workspace(tmp_path, name: str = "gd") -> CanonicalWorkspace:
    root = build_project(
        tmp_path / name,
        schemas=[
            {
                "table": "Item",
                "primary": "Id",
                "fields": [
                    {"name": "Id", "type": "int32"},
                    {"name": "Name", "type": "string"},
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
                "fields": [{"name": "ItemId", "type": "int32"}],
            },
            {
                "kind": "enum",
                "name": "ItemRarity",
                "values": [
                    {"name": "Common", "comment": ""},
                    {"name": "Rare", "comment": ""},
                ],
            },
        ],
    )
    (root / "excel").mkdir(parents=True, exist_ok=True)
    (root / "i18n" / "source").mkdir(parents=True, exist_ok=True)
    return CanonicalWorkspace.load(root)


def _draft(workspace: CanonicalWorkspace, commands: list[Command] | None = None) -> DraftLog:
    log = DraftLog(workspace.resources.resources, base_indexes=dict(workspace.indexes))
    for command in commands or []:
        log.execute(command)
    return log


# --------------------------------------------------------------------------- #
# 1.1 Schema revision
# --------------------------------------------------------------------------- #


def test_schema_revision_changes_on_yaml_edit(tmp_path) -> None:
    workspace = _workspace(tmp_path)
    before = build_schema_revision(workspace.config)
    path = workspace.config.resolve("schemas_dir") / "Item.yaml"
    path.write_text(path.read_text(encoding="utf-8") + "\n# formatting noise\n", encoding="utf-8")
    after = build_schema_revision(workspace.config)
    assert before.revision != after.revision
    assert after.changed_members(before) == ["schemas/Item.yaml"]


def test_schema_revision_tracks_member_add_and_delete(tmp_path) -> None:
    workspace = _workspace(tmp_path)
    before = build_schema_revision(workspace.config)
    types_dir = workspace.config.resolve("types_dir")
    (types_dir / "Extra.yaml").write_text(
        "kind: record\nname: Extra\nfields:\n  - {name: Amount, type: int32}\n",
        encoding="utf-8",
    )
    added = build_schema_revision(workspace.config)
    assert added.changed_members(before) == ["types/Extra.yaml"]
    (types_dir / "Extra.yaml").unlink()
    removed = build_schema_revision(workspace.config)
    assert removed.revision == before.revision


def test_schema_revision_changes_with_config_bytes(tmp_path) -> None:
    workspace = _workspace(tmp_path)
    before = build_schema_revision(workspace.config)
    config_file = workspace.config.project_root / "config" / "global.yaml"
    config_file.write_text(
        config_file.read_text(encoding="utf-8") + "primary_lang: zh\n",
        encoding="utf-8",
    )
    after = build_schema_revision(workspace.config)
    assert before.revision != after.revision


def test_schema_revision_ignores_excel_and_i18n(tmp_path) -> None:
    workspace = _workspace(tmp_path)
    before = build_schema_revision(workspace.config)
    (workspace.config.project_root / "excel" / "Item.xlsx").write_bytes(b"not really a workbook")
    i18n = workspace.config.project_root / "i18n" / "source" / "Item.json"
    i18n.write_text('{"1.Name": "x"}', encoding="utf-8")
    after = build_schema_revision(workspace.config)
    assert before.revision == after.revision


def test_capture_schema_sources_loads_the_same_bytes(tmp_path) -> None:
    workspace = _workspace(tmp_path)
    sources = capture_schema_sources(workspace.config)
    loaded = CanonicalWorkspace.load(
        workspace.root, contents=sources.contents, config=workspace.config
    )
    assert loaded.resources.resources == workspace.resources.resources
    assert build_schema_revision(workspace.config, contents=sources.contents) == sources.revision


# --------------------------------------------------------------------------- #
# 1.2 Net difference and rename identity
# --------------------------------------------------------------------------- #


def test_net_diff_is_empty_for_untouched_draft(tmp_path) -> None:
    workspace = _workspace(tmp_path)
    log = _draft(workspace)
    diff = compute_net_diff(
        (workspace.resources.resources, dict(workspace.indexes)), log.current(), log.commands
    )
    assert diff.is_empty
    assert diff.changed_resources == 0


def test_net_diff_codename_round_trip_is_empty(tmp_path) -> None:
    workspace = _workspace(tmp_path)
    log = _draft(workspace)
    log.execute(
        Command(
            "set_property",
            {"owner": "table:Item", "name": "Name", "property": "i18n", "value": True},
        )
    )
    log.execute(
        Command(
            "set_property",
            {"owner": "table:Item", "name": "Name", "property": "i18n", "value": False},
        )
    )
    diff = compute_net_diff(
        (workspace.resources.resources, dict(workspace.indexes)), log.current(), log.commands
    )
    assert diff.is_empty


def test_net_diff_repeated_property_edit_collapses(tmp_path) -> None:
    workspace = _workspace(tmp_path)
    log = _draft(workspace)
    for comment in ("a", "b", "final"):
        log.execute(
            Command(
                "set_property",
                {"owner": "table:Item", "name": "Name", "property": "comment", "value": comment},
            )
        )
    diff = compute_net_diff(
        (workspace.resources.resources, dict(workspace.indexes)), log.current(), log.commands
    )
    assert diff.changed_resources == 1
    assert diff.changes[0].change == "modified"
    assert [item.name for item in diff.changes[0].fields] == ["Name"]
    assert diff.changes[0].fields[0].details == ("comment",)


def test_net_diff_rename_chain_reports_final_identity(tmp_path) -> None:
    workspace = _workspace(tmp_path)
    log = _draft(workspace)
    log.execute(Command("rename_field", {"owner": "table:Item", "old": "Name", "new": "DisplayName"}))
    log.execute(
        Command("rename_field", {"owner": "table:Item", "old": "DisplayName", "new": "Title"})
    )
    diff = compute_net_diff(
        (workspace.resources.resources, dict(workspace.indexes)), log.current(), log.commands
    )
    assert diff.changed_resources == 1
    changed = diff.changes[0]
    assert changed.change == "modified"
    assert [(item.change, item.old_name, item.name) for item in changed.fields] == [
        ("renamed", "Name", "Title")
    ]


def test_net_diff_rename_round_trip_is_empty(tmp_path) -> None:
    workspace = _workspace(tmp_path)
    log = _draft(workspace)
    log.execute(Command("rename_field", {"owner": "table:Item", "old": "Name", "new": "DisplayName"}))
    log.execute(Command("rename_field", {"owner": "table:Item", "old": "DisplayName", "new": "Name"}))
    diff = compute_net_diff(
        (workspace.resources.resources, dict(workspace.indexes)), log.current(), log.commands
    )
    assert diff.is_empty


def test_net_diff_resource_rename_counts_once_and_updates_references(tmp_path) -> None:
    workspace = _workspace(tmp_path)
    log = _draft(workspace)
    log.execute(Command("rename_resource", {"old": "DropReward", "new": "Reward"}))
    log.execute(Command("rename_resource", {"old": "Reward", "new": "DropRewardInfo"}))
    diff = compute_net_diff(
        (workspace.resources.resources, dict(workspace.indexes)), log.current(), log.commands
    )
    renamed = [item for item in diff.changes if item.change == "renamed"]
    assert [(item.old_name, item.name) for item in renamed] == [("DropReward", "DropRewardInfo")]
    # Item.Rewards was rewritten by the rename: it counts as its own changed resource.
    modified = [item for item in diff.changes if item.change == "modified"]
    assert [item.name for item in modified] == ["Item"]
    assert diff.changed_resources == 2


def test_net_diff_delete_then_add_is_not_a_rename(tmp_path) -> None:
    workspace = _workspace(tmp_path)
    log = _draft(workspace)
    log.execute(Command("delete_resource", {"name": "record:DropReward"}))
    log.execute(
        Command(
            "add_resource",
            {
                "kind": "record",
                "resource": RecordResource(
                    name="DropReward", fields=[FieldDef(name="ItemId", type="int32")]
                ),
            },
        )
    )
    diff = compute_net_diff(
        (workspace.resources.resources, dict(workspace.indexes)), log.current(), log.commands
    )
    assert diff.is_empty
    assert rename_identity(
        (workspace.resources.resources, dict(workspace.indexes)), log.commands
    ) == {}


def test_net_diff_added_then_deleted_is_empty(tmp_path) -> None:
    workspace = _workspace(tmp_path)
    log = _draft(workspace)
    log.execute(
        Command(
            "add_resource",
            {
                "kind": "record",
                "resource": RecordResource(
                    name="Temporary", fields=[FieldDef(name="Amount", type="int32")]
                ),
            },
        )
    )
    log.execute(Command("delete_resource", {"name": "record:Temporary"}))
    diff = compute_net_diff(
        (workspace.resources.resources, dict(workspace.indexes)), log.current(), log.commands
    )
    assert diff.is_empty


def test_net_diff_added_then_renamed_reports_final_name(tmp_path) -> None:
    workspace = _workspace(tmp_path)
    log = _draft(workspace)
    log.execute(
        Command(
            "add_resource",
            {
                "kind": "record",
                "resource": RecordResource(
                    name="Reward", fields=[FieldDef(name="Amount", type="int32")]
                ),
            },
        )
    )
    log.execute(Command("rename_resource", {"old": "Reward", "new": "DropReward2"}))
    diff = compute_net_diff(
        (workspace.resources.resources, dict(workspace.indexes)), log.current(), log.commands
    )
    assert [(item.change, item.name) for item in diff.changes] == [("added", "DropReward2")]


def test_net_diff_enum_reorder_is_a_modification(tmp_path) -> None:
    workspace = _workspace(tmp_path)
    log = _draft(workspace)
    log.execute(
        Command(
            "set_enum_values",
            {
                "name": "enum:ItemRarity",
                "values": [
                    {"name": "Rare", "comment": ""},
                    {"name": "Common", "comment": ""},
                ],
            },
        )
    )
    diff = compute_net_diff(
        (workspace.resources.resources, dict(workspace.indexes)), log.current(), log.commands
    )
    assert [(item.change, item.name) for item in diff.changes] == [("modified", "ItemRarity")]


def test_net_diff_ignores_undone_commands(tmp_path) -> None:
    workspace = _workspace(tmp_path)
    log = _draft(workspace)
    log.execute(Command("rename_resource", {"old": "DropReward", "new": "Reward"}))
    log.undo()
    diff = compute_net_diff(
        (workspace.resources.resources, dict(workspace.indexes)),
        log.current(),
        log.commands,
        cursor=log.cursor,
    )
    assert diff.is_empty


def test_net_diff_default_values_are_not_differences(tmp_path) -> None:
    workspace = _workspace(tmp_path)
    log = _draft(workspace)
    log.execute(
        Command(
            "set_property",
            {"owner": "table:Item", "name": "Name", "property": "comment", "value": ""},
        )
    )
    diff = compute_net_diff(
        (workspace.resources.resources, dict(workspace.indexes)), log.current(), log.commands
    )
    assert diff.is_empty


# --------------------------------------------------------------------------- #
# 1.3 Candidate validation, hash and payload
# --------------------------------------------------------------------------- #


def test_candidate_hash_is_order_independent_and_structural(tmp_path) -> None:
    workspace = _workspace(tmp_path)
    resources = workspace.resources.resources
    indexes = dict(workspace.indexes)
    baseline = candidate_hash(resources, indexes)
    assert baseline == candidate_hash(tuple(reversed(resources)), indexes)

    log = _draft(workspace)
    log.execute(Command("rename_field", {"owner": "table:Item", "old": "Name", "new": "DisplayName"}))
    changed_resources, changed_indexes = log.current()
    assert candidate_hash(changed_resources, changed_indexes) != baseline


def test_candidate_hash_reflects_declared_indexes(tmp_path) -> None:
    workspace = _workspace(tmp_path)
    resources = workspace.resources.resources
    with_index = {"table:Item": (QueryIndex(kind="codename"),)}
    assert candidate_hash(resources, with_index) != candidate_hash(resources, {})


def test_validate_candidate_reports_cycle_and_missing_reference(tmp_path) -> None:
    workspace = _workspace(tmp_path)
    log = _draft(workspace)
    log.execute(Command("set_type", {"owner": "table:Quest", "name": "Id", "type_text": "Missing"}))
    issues = validate_candidate(*log.current())
    assert any("Missing" in issue.message for issue in issues)

    log = _draft(workspace)
    log.execute(Command("delete_resource", {"name": "record:DropReward"}))
    issues = validate_candidate(*log.current())
    assert issues, "deleting a referenced Record must fail candidate validation"


def test_validate_candidate_surfaces_illegal_field_role(tmp_path) -> None:
    workspace = _workspace(tmp_path)
    log = _draft(workspace)
    log.execute(
        Command(
            "set_property",
            {"owner": "table:Item", "name": "Id", "property": "server_only", "value": True},
        )
    )
    issues = validate_candidate(*log.current())
    assert any("server_only" in issue.message for issue in issues)


def test_enum_reorder_and_rename_show_ordinals(tmp_path):
    ws = _workspace(tmp_path)
    commands = [Command("set_enum_values", {"name": "enum:ItemRarity", "values": [
        {"name": "Rare"}, {"name": "Common"},
    ]})]
    log = _draft(ws, commands)
    diff = compute_net_diff((ws.resources.resources, dict(ws.indexes)), log.current(), commands)
    fields = diff.to_payload()["resources"][0]["fields"]
    assert any("ordinal 0 → 1" in detail for f in fields for detail in f["details"])
    assert any("ordinal 1 → 0" in detail for f in fields for detail in f["details"])
    commands = [Command("rename_enum_item", {"name": "enum:ItemRarity", "oldName": "Rare",
        "newName": "Epic", "originalOrdinal": 1})]
    log = _draft(ws, commands)
    diff = compute_net_diff((ws.resources.resources, dict(ws.indexes)), log.current(), commands)
    field = diff.to_payload()["resources"][0]["fields"][0]
    assert field["oldName"] == "Rare" and field["name"] == "Epic"
    assert "ordinal 1 不变" in field["details"][0]
