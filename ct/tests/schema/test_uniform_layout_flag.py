"""表级 `uniform` 键：定宽与否由 schema **声明**（缺省 true），不由数据/填充率判定。

缺省值刻意不进 canonical 持久化表示（`resource_to_data` 用 `exclude_defaults`），
因此默认表的 `schema_hash` 不因本键变化；只有显式 `uniform: false` 才改变它。
"""

from __future__ import annotations

import pytest

from ct.schema.hashing import compute_schema_hash
from ct.schema.resources import FieldDef, TableResource, resource_to_data


def _table(**extra) -> TableResource:
    return TableResource(
        table="Item",
        primary="Id",
        fields=[FieldDef(name="Id", type="int32"), FieldDef(name="Name", type="string")],
        **extra,
    )


def test_default_is_uniform() -> None:
    assert _table().uniform is True


def test_default_value_is_not_persisted() -> None:
    data = resource_to_data(_table())
    assert "uniform" not in data
    # 缺省不改变 hash ⇒ 引入本键不会让全库 schema_hash 漂移
    assert compute_schema_hash(_table()) == compute_schema_hash(_table())


def test_explicit_false_is_persisted_and_changes_hash() -> None:
    data = resource_to_data(_table(uniform=False))
    assert data["uniform"] is False
    assert compute_schema_hash(_table(uniform=False)) != compute_schema_hash(_table())


def test_explicit_true_is_also_dropped_as_default() -> None:
    assert "uniform" not in resource_to_data(_table(uniform=True))


@pytest.mark.parametrize("bad", ["yes-please", "定宽", 1.5])
def test_non_boolean_is_rejected(bad: object) -> None:
    with pytest.raises(ValueError):
        _table(uniform=bad)
