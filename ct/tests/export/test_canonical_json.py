"""Canonical JSON export tests (5.1)."""

from __future__ import annotations

import json

from ct.export.canonical_json import serialize_table_json
from ct.schema.resources import TableResource


def _table() -> TableResource:
    return TableResource(
        table="Item",
        primary="Id",
        fields=[
            {"name": "Id", "type": "int32"},
            {"name": "Rarity", "type": "ItemRarity"},
            {"name": "DropRange", "type": "DropRange"},
            {"name": "Tags", "type": "vector<int32>"},
            {"name": "Rewards", "type": "vector<DropReward>"},
        ],
    )


def test_json_serializes_canonical_shapes() -> None:
    table = _table()
    rows = [
        {
            "Id": 1,
            "Rarity": "Rare",
            "DropRange": {"Min": 10, "Max": 20},
            "Tags": [1, 2, 5],
            "Rewards": [{"ItemId": 100, "Count": 2}, {"ItemId": 200, "Count": 3}],
        }
    ]
    payload = json.loads(serialize_table_json(rows, table))
    assert payload == {"Items": rows}
    assert payload["Items"][0]["Rarity"] == "Rare"
    assert payload["Items"][0]["DropRange"] == {"Min": 10, "Max": 20}
    assert payload["Items"][0]["Tags"] == [1, 2, 5]
    assert len(payload["Items"][0]["Rewards"]) == 2


def test_json_root_key_uses_json_key_override() -> None:
    table = TableResource(
        table="Quest",
        primary="Id",
        json_key="quests",
        fields=[{"name": "Id", "type": "int32"}],
    )
    payload = json.loads(serialize_table_json([{"Id": 1}], table))
    assert payload == {"quests": [{"Id": 1}]}
