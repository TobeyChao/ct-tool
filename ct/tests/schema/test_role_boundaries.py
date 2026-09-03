"""v1 role boundaries: i18n/server_only only on Table top-level fields."""

from __future__ import annotations

import pytest

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
