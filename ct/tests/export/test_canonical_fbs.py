"""Canonical shared types.fbs generation tests (5.2)."""

from __future__ import annotations

import pytest

from ct.export.canonical_fbs import (
    table_fbs_text,
    types_fbs_text,
    validate_canonical_fbs,
)
from ct.schema.resources import (
    EnumResource,
    FieldDef,
    RecordResource,
    TableResource,
)


def _resources() -> dict:
    rarity = EnumResource(name="ItemRarity", values=["Common", "Rare"])
    reward = RecordResource(
        name="DropReward",
        fields=[
            FieldDef(name="ItemId", type="int32"),
            FieldDef(name="Rarity", type="ItemRarity"),
        ],
    )
    item = TableResource(
        table="Item",
        primary="Id",
        fields=[
            FieldDef(name="Id", type="int32"),
            FieldDef(name="Rarity", type="ItemRarity"),
            FieldDef(name="Rewards", type="vector<DropReward>"),
        ],
    )
    return {"enum:ItemRarity": rarity, "record:DropReward": reward, "table:Item": item}


def test_types_fbs_emits_enum_and_table_in_dependency_order() -> None:
    resources = _resources()
    order = ["enum:ItemRarity", "record:DropReward", "table:Item"]
    text = types_fbs_text(order, resources)
    assert "enum ItemRarity : byte { Common = 0, Rare = 1 }" in text
    assert "table DropReward {" in text
    assert text.index("enum ItemRarity") < text.index("table DropReward")
    assert "struct" not in text  # no accidental native struct


def test_table_fbs_includes_shared_types() -> None:
    resources = _resources()
    table = resources["table:Item"]
    text = table_fbs_text(table)
    assert 'include "types.fbs";' in text
    assert "table Item {" in text
    assert "Rarity: ItemRarity;" in text
    assert "Rewards: [DropReward];" in text
    assert "table ItemTable {" in text
    assert "root_type ItemTable;" in text


def test_validate_passes_for_well_formed_workspace() -> None:
    resources = _resources()
    order = ["enum:ItemRarity", "record:DropReward", "table:Item"]
    types_text = types_fbs_text(order, resources)
    table_texts = {"Item": table_fbs_text(resources["table:Item"])}
    validate_canonical_fbs(types_text, table_texts, list(resources.values()))


def test_duplicate_symbol_rejected() -> None:
    with pytest.raises(ValueError, match="重复符号"):
        validate_canonical_fbs(
            "enum A : byte { X = 0 }\nenum A : byte { Y = 0 }",
            {},
            [],
        )


def test_record_must_not_be_native_struct() -> None:
    with pytest.raises(ValueError, match="FlatBuffers table"):
        validate_canonical_fbs(
            "struct DropReward {\n  ItemId: int32;\n}",
            {},
            [RecordResource(name="DropReward", fields=[FieldDef(name="ItemId", type="int32")])],
        )


def test_table_must_not_copy_shared_type() -> None:
    resources = _resources()
    order = ["enum:ItemRarity", "record:DropReward", "table:Item"]
    types_text = types_fbs_text(order, resources)
    copied = "table Item {\n  Rarity: ItemRarity;\n}\ntable DropReward {\n  ItemId: int32;\n}\nroot_type Item;"
    with pytest.raises(ValueError, match="重复定义"):
        validate_canonical_fbs(types_text, {"Item": copied}, list(resources.values()))
