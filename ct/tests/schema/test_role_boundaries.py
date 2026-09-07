"""v1 role boundaries: i18n/server_only only on Table top-level fields."""

from __future__ import annotations

from pathlib import Path

import pytest

from ct.schema.resource_repository import YamlResourceRepository
from ct.schema.resources import FieldDef, RecordResource, TableResource


def test_record_i18n_leaf_is_rejected_with_path() -> None:
    with pytest.raises(ValueError, match=r"record:DropReward/Name.*i18n"):
        RecordResource(
            name="DropReward",
            fields=[
                FieldDef(name="Id", type="int32"),
                FieldDef(name="Name", type="string", i18n=True),
            ],
        )


def test_record_server_only_leaf_is_rejected_with_path() -> None:
    with pytest.raises(ValueError, match=r"record:DropReward/Secret.*server_only"):
        RecordResource(
            name="DropReward",
            fields=[
                FieldDef(name="Id", type="int32"),
                FieldDef(name="Secret", type="int32", server_only=True),
            ],
        )


def test_table_top_level_roles_are_accepted() -> None:
    table = TableResource(
        table="Item",
        primary="Id",
        fields=[
            FieldDef(name="Id", type="int32"),
            FieldDef(name="Name", type="string", i18n=True),
            FieldDef(name="DebugNote", type="string", server_only=True),
        ],
    )
    assert table is not None


def test_table_field_cannot_combine_i18n_and_server_only() -> None:
    with pytest.raises(ValueError, match="i18n.*server_only"):
        TableResource(
            table="Item",
            primary="Id",
            fields=[
                FieldDef(name="Id", type="int32"),
                FieldDef(name="Name", type="string", i18n=True, server_only=True),
            ],
        )


def test_i18n_requires_string_type() -> None:
    with pytest.raises(ValueError, match="只有 string"):
        FieldDef(name="Price", type="int32", i18n=True)


def test_separator_on_scalar_field_rejected() -> None:
    with pytest.raises(ValueError, match="separator.*vector"):
        FieldDef(name="Price", type="int32", separator=",")


def test_separator_on_vector_record_rejected_with_owner_path(tmp_path: Path) -> None:
    schemas = tmp_path / "config/schemas"
    types = tmp_path / "config/types"
    schemas.mkdir(parents=True)
    types.mkdir(parents=True)
    (schemas / "Item.yaml").write_text(
        "table: Item\nprimary: Id\nfields:\n"
        "  - name: Id\n    type: int32\n"
        "  - name: Rewards\n    type: vector<DropReward>\n    separator: ';'\n",
        encoding="utf-8",
    )
    (types / "DropReward.yaml").write_text(
        "kind: record\nname: DropReward\nfields:\n"
        "  - name: Min\n    type: int32\n"
        "  - name: Max\n    type: int32\n",
        encoding="utf-8",
    )
    repository = YamlResourceRepository(schemas, types)
    with pytest.raises(ValueError, match=r"Item/Rewards.*separator"):
        repository.load()


def test_primary_key_cannot_be_server_only() -> None:
    with pytest.raises(ValueError, match="主键.*server_only"):
        TableResource(
            table="Item",
            primary="Id",
            fields=[
                FieldDef(name="Id", type="int32", server_only=True),
            ],
        )


def test_non_vector_rejects_excel_columns() -> None:
    with pytest.raises(ValueError, match="excel_columns"):
        FieldDef(name="Price", type="int32", excel_columns=3)


def test_record_vector_without_excel_columns_is_valid(tmp_path: Path) -> None:
    """vector<Record> 在 canonical 模型里合法；excel_columns 是 Excel 录入层配置。"""
    schemas = tmp_path / "config/schemas"
    types = tmp_path / "config/types"
    schemas.mkdir(parents=True)
    types.mkdir(parents=True)
    (schemas / "Item.yaml").write_text(
        "table: Item\nprimary: Id\nfields:\n"
        "  - name: Id\n    type: int32\n"
        "  - name: Rewards\n    type: vector<DropReward>\n",
        encoding="utf-8",
    )
    (types / "DropReward.yaml").write_text(
        "kind: record\nname: DropReward\nfields:\n"
        "  - name: Min\n    type: int32\n"
        "  - name: Max\n    type: int32\n",
        encoding="utf-8",
    )
    repository = YamlResourceRepository(schemas, types)
    workspace = repository.load()
    assert len(workspace.tables) == 1


def test_scalar_vector_accepts_excel_columns(tmp_path: Path) -> None:
    schemas = tmp_path / "config/schemas"
    types = tmp_path / "config/types"
    schemas.mkdir(parents=True)
    types.mkdir(parents=True)
    (schemas / "Item.yaml").write_text(
        "table: Item\nprimary: Id\nfields:\n"
        "  - name: Id\n    type: int32\n"
        "  - name: Tags\n    type: vector<int32>\n    excel_columns: 3\n",
        encoding="utf-8",
    )
    repository = YamlResourceRepository(schemas, types)
    workspace = repository.load()
    assert workspace.tables[0].fields[1].excel_columns == 3


def test_scalar_vector_excel_columns_loads_in_quest_shape(tmp_path: Path) -> None:
    schemas = tmp_path / "config/schemas"
    types = tmp_path / "config/types"
    schemas.mkdir(parents=True)
    types.mkdir(parents=True)
    (schemas / "Quest.yaml").write_text(
        "table: Quest\nprimary: Id\nfields:\n"
        "  - name: Id\n    type: int32\n"
        "  - name: Test\n    type: vector<int32>\n    excel_columns: 2\n",
        encoding="utf-8",
    )
    workspace = YamlResourceRepository(schemas, types).load()
    assert workspace.tables[0].fields[1].type_text == "vector<int32>"
