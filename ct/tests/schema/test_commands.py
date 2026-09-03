"""Deletion protection and explicit rename commands over the canonical graph."""

from __future__ import annotations

import pytest

from ct.app.canonical_workspace import CanonicalWorkspace
from ct.schema.commands import rename_field, rename_resource
from ct.schema.resource_graph import require_deletable

from _helpers import build_project


ITEM = {
    "table": "Item",
    "primary": "Id",
    "fields": [
        {"name": "Id", "type": "int32"},
        {"name": "Rewards", "type": "vector<DropReward>"},
        {"name": "ItemTypeId", "type": "int32", "ref": "ItemType.Id"},
    ],
}
QUEST = {
    "table": "Quest",
    "primary": "Id",
    "fields": [
        {"name": "Id", "type": "int32"},
        {"name": "Rewards", "type": "vector<DropReward>"},
    ],
}
DROPreWARD = {
    "kind": "record",
    "name": "DropReward",
    "fields": [
        {"name": "ItemId", "type": "int32"},
        {"name": "Rarity", "type": "ItemRarity"},
    ],
}
RARITY = {"kind": "enum", "name": "ItemRarity", "values": ["Common", "Rare"]}
ITEMTYPE = {
    "table": "ItemType",
    "primary": "Id",
    "fields": [{"name": "Id", "type": "int32"}],
}


def _ws(tmp_path, schemas=None, types=None) -> CanonicalWorkspace:
    root = build_project(
        tmp_path / "gd",
        schemas=schemas if schemas is not None else [ITEM, QUEST, ITEMTYPE],
        types=types if types is not None else [DROPreWARD, RARITY],
    )
    return CanonicalWorkspace.load(root)


def test_deletion_of_referenced_record_is_blocked_with_all_use_sites(tmp_path) -> None:
    ws = _ws(tmp_path)
    with pytest.raises(ValueError, match="record:DropReward.*table:Item/Rewards.*table:Quest/Rewards"):
        require_deletable("record:DropReward", ws.reverse_refs)


def test_deletion_of_referenced_field_is_blocked(tmp_path) -> None:
    ws = _ws(tmp_path, schemas=[ITEM, ITEMTYPE], types=[DROPreWARD, RARITY])
    with pytest.raises(ValueError, match="table:ItemType/Id.*table:Item/ItemTypeId"):
        require_deletable("table:ItemType/Id", ws.reverse_refs)


def test_deletion_of_unreferenced_resource_is_allowed(tmp_path) -> None:
    orphan = {
        "table": "Orphan",
        "primary": "Id",
        "fields": [{"name": "Id", "type": "int32"}],
    }
    ws = _ws(tmp_path, schemas=[ITEM, ITEMTYPE, orphan], types=[DROPreWARD, RARITY])
    require_deletable("table:Orphan", ws.reverse_refs)  # no references


def test_resource_rename_updates_all_named_references_atomically(tmp_path) -> None:
    ws = _ws(tmp_path)
    result = rename_resource(ws.resources.resources, "DropReward", "DropBonus")
    assert result.mapping == {"record:DropReward": "record:DropBonus"}

    item = next(r for r in result.resources if isinstance(r, type(ws.tables[0])) and r.table == "Item")
    quest = next(r for r in result.resources if r.resource_id == "table:Quest")
    assert item.fields[1].type_text == "vector<DropBonus>"
    assert quest.fields[1].type_text == "vector<DropBonus>"


def test_table_rename_updates_cross_table_refs(tmp_path) -> None:
    ws = _ws(tmp_path, schemas=[ITEM, ITEMTYPE], types=[DROPreWARD, RARITY])
    result = rename_resource(ws.resources.resources, "ItemType", "ItemCategory")
    item = next(r for r in result.resources if r.resource_id == "table:Item")
    ref = next(field for field in item.fields if field.name == "ItemTypeId")
    assert ref.ref == "ItemCategory.Id"


def test_field_rename_updates_cross_table_ref_targets(tmp_path) -> None:
    ws = _ws(tmp_path, schemas=[ITEM, ITEMTYPE], types=[DROPreWARD, RARITY])
    result = rename_field(ws.resources.resources, "table:ItemType", "Id", "TypeId")
    assert result.mapping == {"table:ItemType/Id": "table:ItemType/TypeId"}
    item = next(r for r in result.resources if r.resource_id == "table:Item")
    ref = next(field for field in item.fields if field.name == "ItemTypeId")
    assert ref.ref == "ItemType.TypeId"


def test_rename_then_undo_restores_original_workspace(tmp_path) -> None:
    ws = _ws(tmp_path)
    forward = rename_resource(ws.resources.resources, "DropReward", "DropBonus")
    backward = rename_resource(forward.resources, "DropBonus", "DropReward")
    original = {resource.resource_id: resource for resource in ws.resources.resources}
    restored = {resource.resource_id: resource for resource in backward.resources}
    assert original.keys() == restored.keys()
    for resource_id, resource in original.items():
        assert resource.model_dump() == restored[resource_id].model_dump()
