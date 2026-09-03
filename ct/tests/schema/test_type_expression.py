from __future__ import annotations

import pytest
from pydantic import ValidationError

from ct.schema.type_expression import (
    NamedType,
    ScalarType,
    TypeExpressionError,
    VectorType,
    parse_type_expression,
    serialize_type_expression,
)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("int32", ScalarType(name="int32")),
        ("string", ScalarType(name="string")),
        ("ItemRarity", NamedType(resource_id="ItemRarity")),
        (
            "vector<DropReward>",
            VectorType(element=NamedType(resource_id="DropReward")),
        ),
        (
            " vector < int64 > ",
            VectorType(element=ScalarType(name="int64")),
        ),
    ],
)
def test_parse_and_canonical_round_trip(source: str, expected: object) -> None:
    parsed = parse_type_expression(source)

    assert parsed == expected
    assert parse_type_expression(serialize_type_expression(parsed)) == parsed


def test_resolved_named_reference_serializes_without_storage_noise() -> None:
    named = NamedType(resource_id="record:DropReward")

    assert named.name == "DropReward"
    assert named.expected_kind == "record"
    assert named.resolved is True
    assert serialize_type_expression(named) == "DropReward"
    assert NamedType(resource_id="DropReward").resolve("enum") == NamedType(
        resource_id="enum:DropReward",
        expected_kind="enum",
    )


@pytest.mark.parametrize(
    "source",
    [
        "",
        "   ",
        "vector",
        "vector<>",
        "vector<int32",
        "vector<int32>>",
        "vector<int32,string>",
        "array<int32>",
        "itemRarity",
        "Item-Rarity",
    ],
)
def test_malformed_expression_is_rejected(source: str) -> None:
    with pytest.raises(TypeExpressionError) as raised:
        parse_type_expression(source)

    assert "无效类型表达式" in str(raised.value)
    assert "位置" in str(raised.value)


def test_nested_vector_is_rejected_with_guidance() -> None:
    with pytest.raises(TypeExpressionError, match="具名 Record"):
        parse_type_expression("vector<vector<int32>>")

    with pytest.raises(ValidationError, match="具名 Record"):
        VectorType(element=VectorType(element=ScalarType(name="int32")))


@pytest.mark.parametrize(
    "resource_id",
    [
        "int32",
        "vector",
        "record:int32",
        "table:Item",
        "record:",
        "record:Drop:Reward",
    ],
)
def test_reserved_or_invalid_named_resource_is_rejected(resource_id: str) -> None:
    with pytest.raises(ValidationError):
        NamedType(resource_id=resource_id)


def test_named_kind_mismatch_is_rejected() -> None:
    with pytest.raises(ValidationError, match="不一致"):
        NamedType(resource_id="record:DropReward", expected_kind="enum")
