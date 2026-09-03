"""Table-level query index model and exact-string lookup tests (5.5/5.7/5.8)."""

from __future__ import annotations

import pytest

from ct.export.index_query import StringIndex, production_hash, validate_code_index
from ct.schema.indexes import QueryIndex, parse_indexes, validate_indexes
from ct.schema.resources import FieldDef, TableResource


def _table() -> TableResource:
    return TableResource(
        table="Item",
        primary="Id",
        fields=[
            FieldDef(name="Id", type="int32"),
            FieldDef(name="CodeName", type="string"),
            FieldDef(name="Category", type="int32"),
            FieldDef(name="DisplayName", type="string", i18n=True),
            FieldDef(name="Rarity", type="enum:ItemRarity"),
        ],
    )


def test_parse_indexes_max_one_per_kind() -> None:
    assert parse_indexes([{"kind": "code", "field": "CodeName"}]) == (
        QueryIndex(kind="code", field="CodeName"),
    )
    with pytest.raises(ValueError, match="最多一个 code"):
        parse_indexes(
            [
                {"kind": "code", "field": "CodeName"},
                {"kind": "code", "field": "Other"},
            ]
        )


def test_validate_code_requires_non_i18n_string() -> None:
    table = _table()
    validate_indexes(table, (QueryIndex("code", "CodeName"),))
    with pytest.raises(ValueError, match="i18n"):
        validate_indexes(table, (QueryIndex("code", "DisplayName"),))
    with pytest.raises(ValueError, match="非 i18n string"):
        validate_indexes(table, (QueryIndex("code", "Id"),))


def test_validate_group_allows_scalar_and_enum_rejects_i18n_and_vector() -> None:
    table = _table()
    validate_indexes(table, (QueryIndex("group", "Category"),))
    validate_indexes(table, (QueryIndex("group", "Rarity"),))
    with pytest.raises(ValueError, match="i18n"):
        validate_indexes(table, (QueryIndex("group", "DisplayName"),))
    vector_table = table.model_copy(
        update={
            "fields": [
                *table.fields,
                FieldDef(name="Tags", type="vector<int32>"),
            ]
        }
    )
    with pytest.raises(ValueError, match="vector"):
        validate_indexes(vector_table, (QueryIndex("group", "Tags"),))


def _collision_hash(text: str) -> int:
    """Injectable hash: all strings share one bucket (adversarial)."""
    return 42


def test_hash_collision_returns_only_exact_match() -> None:
    rows = [
        {"Id": 1, "CodeName": "Sword"},
        {"Id": 2, "CodeName": "sWord"},
        {"Id": 3, "CodeName": "Ｓword"},
    ]
    index = StringIndex.build(rows, "CodeName", hash_provider=_collision_hash)
    assert index.lookup("Sword") == [0]
    assert index.lookup("sWord") == [1]
    assert index.lookup("missing") == []
    # visually related but distinct strings never merge
    assert index.lookup("Sword") != index.lookup("sWord")


def test_hash_is_case_sensitive_and_exact() -> None:
    assert production_hash("Code") != production_hash("code")
    assert production_hash("Ａ") != production_hash("A")  # full-width distinct


def test_code_duplicate_validation_reports_exact_rows() -> None:
    rows = [
        {"Id": 1, "CodeName": "Sword"},
        {"Id": 2, "CodeName": "Sword"},
        {"Id": 3, "CodeName": "Shield"},
    ]
    duplicates = validate_code_index(rows, QueryIndex("code", "CodeName"))
    assert (1, "Sword") in duplicates


def test_normal_bucket_query_is_bucket_local() -> None:
    rows = [{"Id": i, "CodeName": f"V{i}"} for i in range(1000)]
    index = StringIndex.build(rows, "CodeName")
    hit = production_hash("V500")
    # a normal hash produces a ~1-candidate bucket; lookup touches only it
    assert len(index.buckets[hit]) == 1
    assert index.lookup("V500") == [500]
    assert index.lookup("missing") == []


def test_group_repeats_allowed_and_query_returns_all() -> None:
    rows = [
        {"Id": 1, "Category": 1},
        {"Id": 2, "Category": 2},
        {"Id": 3, "Category": 1},
        {"Id": 4, "Category": 3},
    ]
    index = StringIndex.build(rows, "Category")
    assert index.lookup("1") == [0, 2]
    assert index.lookup("3") == [3]
