from __future__ import annotations

import pytest

from ct.schema.name_validation import (
    generated_name_conflicts,
    require_valid_generated_names,
)
from ct.schema.resources import FieldDef, RecordResource, TableResource


def _table(name: str = "Item", fields: list[FieldDef] | None = None) -> TableResource:
    return TableResource(
        table=name,
        primary="Id",
        fields=fields or [FieldDef(name="Id", type="int32")],
    )


def test_generated_container_collision_reports_both_resources() -> None:
    item = _table("Item")
    colliding_record = RecordResource(
        name="ItemTable",
        fields=[FieldDef(name="Value", type="int32")],
    )

    conflicts = generated_name_conflicts((item, colliding_record))

    assert len(conflicts) == 1
    assert conflicts[0].name == "ItemTable"
    assert conflicts[0].locations == (
        "record:ItemTable",
        "table:Item#container",
    )


def test_field_and_named_type_collision_reports_both_locations() -> None:
    item = _table(
        fields=[
            FieldDef(name="Id", type="int32"),
            FieldDef(name="DropReward", type="DropReward"),
        ]
    )
    reward = RecordResource(
        name="DropReward",
        fields=[FieldDef(name="ItemId", type="int32")],
    )

    with pytest.raises(
        ValueError,
        match=r"table:Item/DropReward.*record:DropReward",
    ):
        require_valid_generated_names((item, reward))


def test_fixed_bundle_symbol_collision_is_rejected() -> None:
    table = _table()
    colliding_record = RecordResource(
        name="DataBundle",
        fields=[FieldDef(name="Value", type="int32")],
    )

    with pytest.raises(ValueError, match="DataBundle.*generated:bundle-root"):
        require_valid_generated_names((table, colliding_record))


def test_non_conflicting_workspace_passes() -> None:
    table = _table(
        fields=[
            FieldDef(name="Id", type="int32"),
            FieldDef(name="Reward", type="DropReward"),
        ]
    )
    reward = RecordResource(
        name="DropReward",
        fields=[FieldDef(name="ItemId", type="int32")],
    )

    assert generated_name_conflicts((table, reward)) == ()
