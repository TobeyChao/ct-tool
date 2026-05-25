"""Tests for ct.schema.hashing.compute_schema_hash."""

from __future__ import annotations

from ct.schema.hashing import compute_schema_hash
from ct.schema.models import FieldDef, TableSchema


def _base_schema() -> TableSchema:
    return TableSchema(
        table="item",
        primary="id",
        fields=[
            FieldDef(name="id", type="int32", comment="主键"),
            FieldDef(name="name", type="string", i18n=True, comment="名称"),
            FieldDef(name="price", type="int32", comment="价格"),
        ],
    )


def test_hash_is_deterministic() -> None:
    s1 = _base_schema()
    s2 = _base_schema()
    assert compute_schema_hash(s1) == compute_schema_hash(s2)


def test_hash_changes_when_field_added() -> None:
    base = _base_schema()
    extended = base.model_copy(deep=True)
    extended.fields.append(FieldDef(name="rarity", type="enum", values=["common", "rare"]))
    assert compute_schema_hash(base) != compute_schema_hash(extended)


def test_hash_changes_when_comment_changes() -> None:
    base = _base_schema()
    edited = base.model_copy(deep=True)
    edited.fields[1].comment = "物品名称（多语言）"
    assert compute_schema_hash(base) != compute_schema_hash(edited)


def test_hash_changes_when_fields_reordered() -> None:
    base = _base_schema()
    reordered = TableSchema(
        table=base.table,
        primary=base.primary,
        fields=[base.fields[0], base.fields[2], base.fields[1]],
    )
    assert compute_schema_hash(base) != compute_schema_hash(reordered)


def test_hash_format() -> None:
    h = compute_schema_hash(_base_schema())
    assert len(h) == 16
    int(h, 16)  # raises if not valid hex