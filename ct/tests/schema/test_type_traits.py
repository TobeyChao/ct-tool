"""type_traits 注册表覆盖测试：字段类型闭集无遗漏。"""

from __future__ import annotations

from ct.export.binary_writer import (
    _ELEMENT_VECTOR_WRITERS,
    _OFFSET_BUILDERS,
    _SCALAR_SLOT_WRITERS,
)
from ct.export.csharp_accessor_generator import _ARR_READERS, _SCALAR_READERS
from ct.schema.models import ALL_FIELD_TYPES, BASIC_TYPES
from ct.schema.type_traits import OFFSET_TYPES, TYPE_TRAITS


def test_type_traits_covers_all_field_types() -> None:
    assert set(TYPE_TRAITS) == set(ALL_FIELD_TYPES)


def test_every_trait_has_all_behaviors() -> None:
    behaviors = (
        "coerce",
        "validate",
        "fbs_type",
        "json_value",
        "csharp_type",
        "excel_annotation",
    )
    for type_name in ALL_FIELD_TYPES:
        traits = TYPE_TRAITS[type_name]
        for behavior in behaviors:
            assert callable(getattr(traits, behavior)), (
                f"{type_name}.{behavior} 缺失"
            )


def test_binary_slot_writers_cover_scalar_types() -> None:
    """槽位写入覆盖除 offset 类型外的全部字段类型。"""
    assert set(_SCALAR_SLOT_WRITERS) == set(ALL_FIELD_TYPES) - set(OFFSET_TYPES)


def test_binary_vector_writers_cover_element_types() -> None:
    assert set(_ELEMENT_VECTOR_WRITERS) == set(BASIC_TYPES) | {"enum"}


def test_binary_offset_builders_match_offset_types() -> None:
    assert set(_OFFSET_BUILDERS) == set(OFFSET_TYPES)


def test_csharp_scalar_readers_cover_scalar_types() -> None:
    assert set(_SCALAR_READERS) == (set(BASIC_TYPES) - {"string"}) | {"enum"}


def test_csharp_array_readers_cover_all_element_types() -> None:
    assert set(_ARR_READERS) == set(BASIC_TYPES) | {"enum"}
