from __future__ import annotations

from pathlib import Path

import pytest

from ct.schema.resource_repository import YamlResourceRepository
from ct.schema.resources import (
    EnumResource,
    FieldDef,
    RecordResource,
    TableResource,
    resource_to_data,
)
from ct.schema.type_expression import NamedType, VectorType


TABLE_ITEM = """\
table: Item
primary: Id
fields:
  - name: Id
    type: int32
  - name: Rarity
    type: ItemRarity
  - name: Rewards
    type: vector<DropReward>
    excel_columns: 3
"""

TABLE_QUEST = """\
table: Quest
primary: Id
fields:
  - name: Id
    type: int64
  - name: Reward
    type: DropReward
"""

RECORD_REWARD = """\
kind: record
name: DropReward
fields:
  - name: ItemId
    type: int32
  - name: Rarity
    type: ItemRarity
"""

ENUM_RARITY = """\
kind: enum
name: ItemRarity
values:
  - Common
  - Rare
  - Epic
"""


def _write_workspace(root: Path) -> YamlResourceRepository:
    schemas = root / "config/schemas"
    types = root / "config/types"
    schemas.mkdir(parents=True)
    types.mkdir(parents=True)
    (schemas / "ZQuest.yaml").write_text(TABLE_QUEST, encoding="utf-8")
    (schemas / "AItem.yaml").write_text(TABLE_ITEM, encoding="utf-8")
    (types / "ZItemRarity.yaml").write_text(ENUM_RARITY, encoding="utf-8")
    (types / "ADropReward.yaml").write_text(RECORD_REWARD, encoding="utf-8")
    return YamlResourceRepository(schemas, types)


def test_load_mixed_workspace_deterministically_and_resolve_named_types(
    tmp_path: Path,
) -> None:
    repository = _write_workspace(tmp_path)

    first = repository.load()
    second = repository.load()

    assert [table.name for table in first.tables] == ["Item", "Quest"]
    assert [record.name for record in first.records] == ["DropReward"]
    assert [enum.name for enum in first.enums] == ["ItemRarity"]
    assert tuple(resource.resource_id for resource in first.resources) == tuple(
        resource.resource_id for resource in second.resources
    )

    item = first.by_id["table:Item"]
    assert isinstance(item, TableResource)
    rarity = item.fields[1].type_expr
    assert rarity == NamedType(resource_id="enum:ItemRarity")
    rewards = item.fields[2].type_expr
    assert isinstance(rewards, VectorType)
    assert rewards.element == NamedType(resource_id="record:DropReward")

    reward = first.by_id["record:DropReward"]
    assert isinstance(reward, RecordResource)
    assert reward.fields[1].type_expr == NamedType(resource_id="enum:ItemRarity")
    rarity_resource = first.by_id["enum:ItemRarity"]
    assert isinstance(rarity_resource, EnumResource)
    assert rarity_resource.wire_type == "byte"


def test_canonical_yaml_serialization_contains_one_type_expression() -> None:
    table = TableResource(
        table="Item",
        primary="Id",
        fields=[
            FieldDef(name="Id", type="int32"),
            FieldDef(name="Rewards", type="vector<DropReward>", excel_columns=3),
        ],
    )

    assert resource_to_data(table) == {
        "table": "Item",
        "primary": "Id",
        "fields": [
            {
                "name": "Id",
                "type": "int32",
            },
            {
                "name": "Rewards",
                "type": "vector<DropReward>",
                "excel_columns": 3,
            },
        ],
    }


def test_repository_write_and_reload_round_trip(tmp_path: Path) -> None:
    repository = YamlResourceRepository(
        tmp_path / "config/schemas",
        tmp_path / "config/types",
    )
    enum = EnumResource(name="ItemRarity", values=["Common", "Rare"])
    record = RecordResource(
        name="DropReward",
        fields=[FieldDef(name="Rarity", type="ItemRarity")],
    )
    table = TableResource(
        table="Item",
        primary="Id",
        fields=[
            FieldDef(name="Id", type="int32"),
            FieldDef(name="Rewards", type="vector<DropReward>"),
        ],
    )

    assert repository.write(enum).parent.name == "types"
    repository.write(record)
    assert repository.write(table).parent.name == "schemas"

    loaded = repository.load()
    assert loaded.by_id["table:Item"].fields[1].type_expr == VectorType(
        element=NamedType(resource_id="record:DropReward")
    )
    assert "expected_kind" not in (
        tmp_path / "config/schemas/Item.yaml"
    ).read_text(encoding="utf-8")


def test_unified_resource_name_collision_reports_both_sources(tmp_path: Path) -> None:
    repository = _write_workspace(tmp_path)
    (tmp_path / "config/types/ADropReward.yaml").write_text(
        "kind: record\nname: Item\nfields:\n  - {name: Value, type: int32}\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="AItem.yaml.*ADropReward.yaml"):
        repository.load()


def test_missing_named_target_has_precise_owner_path(tmp_path: Path) -> None:
    repository = _write_workspace(tmp_path)
    item_path = tmp_path / "config/schemas/AItem.yaml"
    item_path.write_text(TABLE_ITEM.replace("DropReward", "MissingReward"), encoding="utf-8")

    with pytest.raises(ValueError, match="table:Item/Rewards.*MissingReward"):
        repository.load()


def test_old_inline_field_shape_fails_without_mutation(tmp_path: Path) -> None:
    schemas = tmp_path / "config/schemas"
    schemas.mkdir(parents=True)
    path = schemas / "Item.yaml"
    original = """\
table: Item
primary: Id
fields:
  - {name: Id, type: int32}
  - name: Rarity
    type: enum
    values: [Common, Rare]
"""
    path.write_text(original, encoding="utf-8")
    repository = YamlResourceRepository(schemas, tmp_path / "config/types")

    with pytest.raises(ValueError, match="具名 Enum/Record.*不会自动迁移"):
        repository.load()

    assert path.read_text(encoding="utf-8") == original


@pytest.mark.parametrize("role", ["i18n", "server_only"])
def test_record_rejects_table_only_field_roles_with_resource_path(
    role: str,
) -> None:
    with pytest.raises(ValueError, match=rf"record:DropReward/Name.*{role}"):
        RecordResource(
            name="DropReward",
            fields=[FieldDef(name="Name", type="string", **{role: True})],
        )
