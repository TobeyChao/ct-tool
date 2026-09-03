"""CanonicalWorkspace: one canonical resource graph for all consumers."""

from __future__ import annotations


def test_load_mixed_workspace_exposes_one_graph(load_v4) -> None:
    ws = load_v4(
        schemas=[
            {
                "table": "Item",
                "primary": "Id",
                "fields": [
                    {"name": "Id", "type": "int32"},
                    {"name": "Rarity", "type": "ItemRarity"},
                ],
            },
            {
                "table": "ItemType",
                "primary": "Id",
                "fields": [{"name": "Id", "type": "int32"}],
            },
        ],
        types=[
            {"kind": "enum", "name": "ItemRarity", "values": ["Common", "Rare"]},
        ],
    )

    assert {table.table for table in ws.tables} == {"Item", "ItemType"}
    assert {enum.name for enum in ws.enums} == {"ItemRarity"}
    # no cross-table ref edge: tables follow deterministic name order
    assert ws.table_order == ("table:Item", "table:ItemType")


def test_table_order_respects_cross_table_refs(load_v4) -> None:
    ws = load_v4(
        schemas=[
            {
                "table": "Quest",
                "primary": "Id",
                "fields": [
                    {"name": "Id", "type": "int32"},
                    {"name": "RewardItemId", "type": "int32", "ref": "Item.Id"},
                ],
            },
            {"table": "Item", "primary": "Id", "fields": [{"name": "Id", "type": "int32"}]},
        ],
    )
    assert ws.table_order == ("table:Item", "table:Quest")


def test_reverse_refs_exposed_on_workspace(load_v4) -> None:
    ws = load_v4(
        schemas=[
            {
                "table": "Item",
                "primary": "Id",
                "fields": [
                    {"name": "Id", "type": "int32"},
                    {"name": "Rewards", "type": "vector<DropReward>"},
                ],
            },
        ],
        types=[
            {
                "kind": "record",
                "name": "DropReward",
                "fields": [{"name": "ItemId", "type": "int32"}],
            },
        ],
    )
    refs = ws.reverse_refs["record:DropReward"]
    assert ("table:Item", "table:Item/Rewards") in {
        (reference.owner, reference.field_path) for reference in refs
    }
