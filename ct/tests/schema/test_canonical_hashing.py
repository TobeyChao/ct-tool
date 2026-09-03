from __future__ import annotations

from ct.schema.hashing import compute_resource_hash, compute_schema_hash
from ct.schema.resources import EnumResource, FieldDef, RecordResource, TableResource


def _table(field_type: str = "int32") -> TableResource:
    return TableResource(
        table="Item",
        primary="Id",
        fields=[
            FieldDef(name="Id", type="int32"),
            FieldDef(name="Value", type=field_type),
        ],
    )


def test_canonical_hash_is_deterministic_for_every_expression_node() -> None:
    scalar = _table("string")
    named = _table("ItemRarity")
    vector = _table("vector<DropReward>")

    for resource in (scalar, named, vector):
        assert compute_resource_hash(resource) == compute_resource_hash(
            resource.model_copy(deep=True)
        )
        assert len(compute_resource_hash(resource)) == 64
    assert len(
        {compute_resource_hash(scalar), compute_resource_hash(named), compute_resource_hash(vector)}
    ) == 3


def test_canonical_hash_changes_for_type_and_excel_layout_inputs() -> None:
    single_cell = TableResource(
        table="Item",
        primary="Id",
        fields=[
            FieldDef(name="Id", type="int32"),
            FieldDef(name="Rewards", type="vector<DropReward>", separator=","),
        ],
    )
    expanded = single_cell.model_copy(
        update={
            "fields": [
                single_cell.fields[0],
                single_cell.fields[1].model_copy(
                    update={"separator": None, "excel_columns": 3}
                ),
            ]
        }
    )

    assert compute_schema_hash(single_cell) != compute_schema_hash(expanded)


def test_referenced_named_resource_content_participates_in_table_hash() -> None:
    table = _table("ItemRarity")
    before = EnumResource(name="ItemRarity", values=["Common", "Rare"])
    after = EnumResource(name="ItemRarity", values=["Common", "Rare", "Epic"])

    assert compute_schema_hash(table, (before,)) != compute_schema_hash(table, (after,))


def test_dependency_order_does_not_change_table_hash() -> None:
    table = _table("DropReward")
    reward = RecordResource(
        name="DropReward",
        fields=[FieldDef(name="Rarity", type="ItemRarity")],
    )
    rarity = EnumResource(name="ItemRarity", values=["Common", "Rare"])

    assert compute_schema_hash(table, (reward, rarity)) == compute_schema_hash(
        table,
        (rarity, reward),
    )
