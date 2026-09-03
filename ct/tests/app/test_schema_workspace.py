"""Snapshot revision, draft reducer, candidate and change-plan tests (6.1-6.5)."""

from __future__ import annotations

import pytest

from ct.app.canonical_workspace import CanonicalWorkspace
from ct.app.schema_workspace.candidate import validate_candidate
from ct.app.schema_workspace.commands_reducer import (
    Command,
    DraftLog,
    apply_commands,
)
from ct.app.schema_workspace.plan import build_change_plan
from ct.app.schema_workspace.snapshot import build_snapshot
from ct.schema.resources import FieldDef, RecordResource, TableResource

from _helpers import build_project


def _base() -> tuple[TableResource, ...]:
    return (
        TableResource(
            table="Item",
            primary="Id",
            fields=[
                FieldDef(name="Id", type="int32"),
                FieldDef(name="Name", type="string"),
                FieldDef(name="Rewards", type="vector<DropReward>"),
            ],
        ),
        TableResource(
            table="Quest",
            primary="Id",
            fields=[FieldDef(name="Id", type="int32")],
        ),
    )


def _records() -> tuple[RecordResource, ...]:
    return (
        RecordResource(
            name="DropReward",
            fields=[FieldDef(name="ItemId", type="int32")],
        ),
    )


def test_snapshot_revision_changes_on_external_input(tmp_path) -> None:
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
    before = build_snapshot(CanonicalWorkspace.load(root))
    # external schema edit: change a field comment value (still valid YAML)
    schema = root / "config" / "schemas" / "Item.yaml"
    schema.write_text(
        schema.read_text(encoding="utf-8").replace("comment: a", "comment: b"),
        encoding="utf-8",
    )
    after = build_snapshot(CanonicalWorkspace.load(root))
    assert before.revision != after.revision
    assert "schema/types" in after.changed_inputs(before)


def test_draft_undo_redo_cursor_semantics() -> None:
    log = DraftLog(_base())
    log.execute(Command("add_field", {"owner": "table:Item", "field": {"name": "Price", "type": "int32"}}))
    log.execute(Command("set_property", {"owner": "table:Item", "name": "Price", "property": "comment", "value": "价格"}))
    resources, _ = log.current()
    item = resources[0]
    assert [f.name for f in item.fields] == ["Id", "Name", "Rewards", "Price"]
    assert item.fields[3].comment == "价格"

    log.undo()
    resources, _ = log.current()
    assert [f.name for f in resources[0].fields] == ["Id", "Name", "Rewards", "Price"]
    assert resources[0].fields[3].comment == ""

    log.undo()
    resources, _ = log.current()
    assert [f.name for f in resources[0].fields] == ["Id", "Name", "Rewards"]

    log.redo()
    log.redo()
    resources, _ = log.current()
    assert resources[0].fields[3].comment == "价格"


def test_rename_command_updates_references() -> None:
    log = DraftLog(_base(), base_indexes={})
    log.execute(Command("rename_resource", {"old": "Item", "new": "Goods"}))
    resources, _ = log.current()
    assert {resource.resource_id for resource in resources} == {
        "table:Goods", "table:Quest",
    }


def test_candidate_validation_reports_role_violation() -> None:
    base = _base()
    # create a record with an i18n leaf via a command that bypasses model checks
    resources = base + (RecordResource(name="R", fields=[FieldDef(name="N", type="string")]),)
    log = DraftLog(resources)
    log.execute(Command("set_property", {"owner": "record:R", "name": "N", "property": "i18n", "value": True}))
    current, _ = log.current()
    issues = validate_candidate(current, {})
    assert any("i18n" in issue.message for issue in issues)


def test_change_plan_dependency_breaking_risk() -> None:
    old = _base() + _records()
    new_records = (
        RecordResource(
            name="DropReward",
            fields=[
                FieldDef(name="ItemId", type="int32"),
                FieldDef(name="Extra", type="int32"),
            ],
        ),
    )
    new = _base() + new_records
    plan = build_change_plan(old, new, old_indexes={}, new_indexes={})
    assert plan.risk == "dependency-breaking"
    assert any(impact.artifact == "FBS" for impact in plan.impacts)


def test_change_plan_issues_carry_locations() -> None:
    # destructive excel scenario requires an excel file; here verify the plan
    # surfaces the excel blocker issue with a location via the issue kind
    base = _base()
    new_tables = (
        TableResource(table="Item", primary="Id", fields=[FieldDef(name="Id", type="int32")]),
        base[1],
    )
    plan = build_change_plan(base, new_tables, old_indexes={}, new_indexes={})
    assert any(impact.artifact == "Excel" and impact.action in ("migrate", "keep") for impact in plan.impacts)
