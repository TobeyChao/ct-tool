"""主键类型：唯一允许 `int32`（索引向量 / idHash / ByID(int) 均为 32 位承载）。"""

from __future__ import annotations

import pytest

from ct.schema.resources import FieldDef, TableResource
from ct.schema.type_expression import INTEGER_SCALAR_NAMES, PRIMARY_KEY_TYPE


def _table(primary_type: str) -> TableResource:
    return TableResource(
        table="Item",
        primary="Id",
        fields=[FieldDef(name="Id", type=primary_type), FieldDef(name="Name", type="string")],
    )


def test_int32_primary_is_accepted() -> None:
    assert _table("int32").primary == "Id"
    assert PRIMARY_KEY_TYPE == "int32"


@pytest.mark.parametrize(
    "primary_type",
    sorted(INTEGER_SCALAR_NAMES - {PRIMARY_KEY_TYPE}),
)
def test_non_int32_integer_primary_is_rejected(primary_type: str) -> None:
    with pytest.raises(ValueError, match=r"主键字段 'Id' 类型必须为 int32"):
        _table(primary_type)


@pytest.mark.parametrize("primary_type", ["string", "bool", "float", "double"])
def test_non_integer_primary_is_rejected(primary_type: str) -> None:
    with pytest.raises(ValueError, match=r"主键字段 'Id' 类型必须为 int32"):
        _table(primary_type)


def test_error_names_the_current_type_and_the_32bit_reason() -> None:
    with pytest.raises(ValueError) as excinfo:
        _table("uint64")
    message = str(excinfo.value)
    assert "当前: uint64" in message
    assert "ByID(int)" in message
