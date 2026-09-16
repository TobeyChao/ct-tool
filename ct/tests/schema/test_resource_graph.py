"""Canonical dependency graph: named edges, ref edges, cycles, reverse refs."""

from __future__ import annotations

import pytest

from ct.app.canonical_workspace import CanonicalWorkspace
from ct.schema.resource_graph import (
    cross_table_ref_edges,
    named_dependency_edges,
    resource_topological_order,
    reverse_references,
)
from ct.schema.resource_repository import YamlResourceRepository

from _helpers import build_project


def _workspace(tmp_path, schemas, types):
    root = build_project(tmp_path / "gd", schemas=schemas, types=types)
    return YamlResourceRepository(
        root / "config" / "schemas",
        root / "config" / "types",
    ).load()


ITEM = {
    "table": "Item",
    "primary": "Id",
    "fields": [
        {"name": "Id", "type": "int32"},
        {"name": "Rewards", "type": "vector<DropReward>", "excel_columns": 2},
        {"name": "ItemTypeId", "type": "int32", "ref": "ItemType.Id"},
    ],
}
QUEST = {
    "table": "Quest",
    "primary": "Id",
    "fields": [
        {"name": "Id", "type": "int32"},
        {"name": "Rewards", "type": "vector<DropReward>", "excel_columns": 2},
    ],
}
DROPReward = {
    "kind": "record",
    "name": "DropReward",
    "fields": [
        {"name": "ItemId", "type": "int32"},
        {"name": "Rarity", "type": "ItemRarity"},
    ],
}
RARITY = {"kind": "enum", "name": "ItemRarity", "values": [{"name": "Common"}, {"name": "Rare"}]}
ITEMTYPE = {
    "table": "ItemType",
    "primary": "Id",
    "fields": [{"name": "Id", "type": "int32"}],
}


def test_named_dependency_edges_direct_and_indirect(tmp_path) -> None:
    ws = _workspace(
        tmp_path,
        schemas=[ITEM],
        types=[DROPReward, RARITY],
    )
    edges = named_dependency_edges(ws.resources)
    assert edges["table:Item"] == ("record:DropReward",)
    assert edges["record:DropReward"] == ("enum:ItemRarity",)
    assert edges["enum:ItemRarity"] == ()


def test_cross_table_ref_edges_and_deterministic_table_order(tmp_path) -> None:
    ws = _workspace(
        tmp_path,
        schemas=[ITEM, ITEMTYPE],
        types=[DROPReward, RARITY],
    )
    refs = cross_table_ref_edges(ws.resources)
    assert refs["table:Item"] == ("table:ItemType",)
    assert refs["table:ItemType"] == ()

    graph = named_dependency_edges(ws.resources)
    order = resource_topological_order(ws.resources, named_graph=graph)
    assert order.index("table:ItemType") < order.index("table:Item")
    assert order.index("enum:ItemRarity") < order.index("record:DropReward")
    assert order.index("record:DropReward") < order.index("table:Item")

    # deterministic
    assert order == resource_topological_order(ws.resources, named_graph=graph)


def test_missing_ref_target_reports_owner_path(tmp_path) -> None:
    bad = {
        "table": "Bad",
        "primary": "Id",
        "fields": [{"name": "Id", "type": "int32"}, {"name": "X", "type": "int32", "ref": "Nope.Id"}],
    }
    root = build_project(tmp_path / "gd", schemas=[bad], types=None)
    with pytest.raises(ValueError, match="table:Bad/X.*'Nope'"):
        CanonicalWorkspace.load(root)


def test_ref_target_must_be_the_target_primary_key(tmp_path) -> None:
    """ref 是主键外键：目标字段必须等于目标表主键，不能是任意字段。"""
    item_type = {
        "table": "ItemType",
        "primary": "Id",
        "fields": [
            {"name": "Id", "type": "int32"},
            {"name": "CodeName", "type": "string"},
        ],
    }
    bad = {
        "table": "Bad",
        "primary": "Id",
        "fields": [
            {"name": "Id", "type": "int32"},
            {"name": "X", "type": "string", "ref": "ItemType.CodeName"},
        ],
    }
    root = build_project(tmp_path / "gd", schemas=[item_type, bad], types=None)
    with pytest.raises(
        ValueError, match="table:Bad/X.*必须是目标表主键 'ItemType.Id'.*ItemType.CodeName"
    ):
        CanonicalWorkspace.load(root)


def test_ref_target_field_typo_is_rejected(tmp_path) -> None:
    """字段段打错（不存在的字段）同样命中主键规则，不再静默通过。"""
    item_type = {
        "table": "ItemType",
        "primary": "Id",
        "fields": [{"name": "Id", "type": "int32"}],
    }
    bad = {
        "table": "Bad",
        "primary": "Id",
        "fields": [
            {"name": "Id", "type": "int32"},
            {"name": "X", "type": "int32", "ref": "ItemType.Nope"},
        ],
    }
    root = build_project(tmp_path / "gd", schemas=[item_type, bad], types=None)
    with pytest.raises(ValueError, match="table:Bad/X.*必须是目标表主键 'ItemType.Id'"):
        CanonicalWorkspace.load(root)


def test_ref_to_a_primary_key_not_named_id_is_accepted(tmp_path) -> None:
    """规则是「目标表主键」而不是字面量 `.Id`：主键叫 TypeId 时 ref 合法。"""
    item_type = {
        "table": "ItemType",
        "primary": "TypeId",
        "fields": [{"name": "TypeId", "type": "int32"}],
    }
    item = {
        "table": "Item",
        "primary": "Id",
        "fields": [
            {"name": "Id", "type": "int32"},
            {"name": "ItemTypeId", "type": "int32", "ref": "ItemType.TypeId"},
        ],
    }
    root = build_project(tmp_path / "gd", schemas=[item_type, item], types=None)
    ws = CanonicalWorkspace.load(root)
    assert cross_table_ref_edges(ws.resources.resources)["table:Item"] == ("table:ItemType",)
    assert ("table:Item", "table:Item/ItemTypeId") in {
        (reference.owner, reference.field_path)
        for reference in reverse_references(ws.resources.resources)["table:ItemType/TypeId"]
    }


def test_record_cycle_is_rejected_with_path(tmp_path) -> None:
    a = {
        "kind": "record",
        "name": "A",
        "fields": [{"name": "Next", "type": "B"}],
    }
    b = {
        "kind": "record",
        "name": "B",
        "fields": [{"name": "Prev", "type": "A"}],
    }
    root = build_project(tmp_path / "gd", schemas=None, types=[a, b])
    with pytest.raises(ValueError, match="循环依赖"):
        CanonicalWorkspace.load(root)


def test_reverse_references_list_every_use_site(tmp_path) -> None:
    ws = _workspace(
        tmp_path,
        schemas=[ITEM, QUEST],
        types=[DROPReward, RARITY],
    )
    reverse = reverse_references(ws.resources)
    reward_refs = reverse["record:DropReward"]
    owners = {reference.owner for reference in reward_refs}
    assert owners == {"table:Item", "table:Quest"}
    assert any(reference.field_path == "table:Item/Rewards" for reference in reward_refs)
    assert any(reference.kind == "named" for reference in reward_refs)

    rarity_refs = reverse["enum:ItemRarity"]
    assert ("record:DropReward", "record:DropReward/Rarity") in {
        (reference.owner, reference.field_path) for reference in rarity_refs
    }

    item_type_refs = reverse["table:ItemType"]
    assert ("table:Item", "table:Item/ItemTypeId") in {
        (reference.owner, reference.field_path) for reference in item_type_refs
    }
