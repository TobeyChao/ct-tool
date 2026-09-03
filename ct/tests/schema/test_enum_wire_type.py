"""Named Enum wire type is fixed to FlatBuffers ``byte`` and not mutable."""

from __future__ import annotations

import pytest

from ct.schema.resources import EnumResource


def test_wire_type_is_always_byte() -> None:
    enum = EnumResource(name="ItemRarity", values=["Common", "Rare"])
    assert enum.wire_type == "byte"


def test_wire_type_cannot_be_supplied() -> None:
    with pytest.raises(ValueError, match="Extra inputs"):
        EnumResource(
            name="ItemRarity",
            values=["Common"],
            wire_type="int32",
        )


def test_more_than_256_values_rejected_for_byte() -> None:
    with pytest.raises(ValueError, match="256"):
        EnumResource(name="TooBig", values=[f"V{i}" for i in range(257)])
