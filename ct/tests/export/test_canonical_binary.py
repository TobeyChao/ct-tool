"""Canonical binary serialization round-trip tests (5.3).

A small manual wire reader (mirroring the generated-reader layout: slots
follow client-field order, strings/records/vectors are uoffset references)
verifies byte-level round trips for empty, partial and full groups.
"""

from __future__ import annotations

from flatbuffers import encode, number_types as ntypes
from flatbuffers.table import Table

from ct.export.canonical_binary import build_canonical_table_bytes
from ct.schema.resources import (
    EnumResource,
    FieldDef,
    RecordResource,
    TableResource,
)


def _records() -> dict[str, RecordResource]:
    return {
        "DropReward": RecordResource(
            name="DropReward",
            fields=[
                FieldDef(name="ItemId", type="int32"),
                FieldDef(name="Count", type="int32"),
            ],
        ),
    }


def _enums() -> dict[str, EnumResource]:
    return {"ItemRarity": EnumResource(name="ItemRarity", values=["Common", "Rare"])}


def _table() -> TableResource:
    return TableResource(
        table="Item",
        primary="Id",
        fields=[
            FieldDef(name="Id", type="int32"),
            FieldDef(name="Rarity", type="ItemRarity"),
            FieldDef(name="Tags", type="vector<int32>"),
            FieldDef(name="Rewards", type="vector<DropReward>"),
            FieldDef(name="Note", type="string"),
        ],
    )


class _WireReader:
    """Minimal canonical-buffer reader following the writer layout.

    Slots follow client-field order; strings/records/vectors are uoffset
    references stored at ``Pos + field_offset`` (mirrors generated readers).
    """

    U32 = ntypes.UOffsetTFlags.packer_type
    I32 = ntypes.Int32Flags.packer_type

    def __init__(self, data: bytes) -> None:
        self.buf = memoryview(data)
        root_uoff = encode.Get(self.U32, self.buf, 0)
        self.container = Table(self.buf, root_uoff)

    def rows(self) -> list[dict]:
        items_field = self.container.Offset(0)
        if items_field == 0:
            return []
        length = self.container.VectorLen(items_field)
        data_start = self.container.Vector(items_field)
        out: list[dict] = []
        for index in range(length):
            element = data_start + 4 * index
            row_pos = element + encode.Get(self.U32, self.buf, element)
            out.append(self._read_row(row_pos))
        return out

    def _read_row(self, pos: int) -> dict:
        row = Table(self.buf, pos)
        return {
            "Id": self._scalar(row, 0, ntypes.Int32Flags, 0),
            "Rarity": self._scalar(row, 1, ntypes.Int8Flags, 0),
            "Tags": self._vector_int32(row, 2),
            "Rewards": self._vector_records(row, 3),
            "Note": self._string(row, 4),
        }

    def _scalar(self, table: Table, index: int, flags, default):
        field_off = table.Offset(4 + 2 * index)
        if field_off == 0:
            return default
        return table.Get(flags, table.Pos + field_off)

    def _string(self, table: Table, index: int) -> str | None:
        field_off = table.Offset(4 + 2 * index)
        if field_off == 0:
            return None
        return table.String(table.Pos + field_off).decode("utf-8")

    def _vector_int32(self, table: Table, index: int) -> list[int]:
        field_off = table.Offset(4 + 2 * index)
        if field_off == 0:
            return []
        length = table.VectorLen(field_off)
        start = table.Vector(field_off)
        return [
            encode.Get(self.I32, self.buf, start + 4 * i)
            for i in range(length)
        ]

    def _vector_records(self, table: Table, index: int) -> list[dict]:
        field_off = table.Offset(4 + 2 * index)
        if field_off == 0:
            return []
        length = table.VectorLen(field_off)
        start = table.Vector(field_off)
        out: list[dict] = []
        for i in range(length):
            element = start + 4 * i
            child_pos = element + encode.Get(self.U32, self.buf, element)
            record = Table(self.buf, child_pos)
            out.append(
                {
                    "ItemId": self._scalar(record, 0, ntypes.Int32Flags, 0),
                    "Count": self._scalar(record, 1, ntypes.Int32Flags, 0),
                }
            )
        return out


def _read(data: bytes) -> list[dict]:
    return _WireReader(data).rows()


def _build(rows: list[dict]) -> bytes:
    return build_canonical_table_bytes(
        rows, _table(), records=_records(), enums=_enums()
    )


def test_round_trip_full_groups() -> None:
    rows = [
        {
            "Id": 1,
            "Rarity": "Rare",
            "Tags": [1, 2, 5],
            "Rewards": [{"ItemId": 100, "Count": 2}, {"ItemId": 200, "Count": 3}],
            "Note": "主语言",
        },
        {
            "Id": 2,
            "Rarity": "Common",
            "Tags": [],
            "Rewards": [],
            "Note": None,
        },
    ]
    decoded = _read(_build(rows))
    assert decoded[0]["Id"] == 1
    assert decoded[0]["Rarity"] == 1  # Rare
    assert decoded[0]["Tags"] == [1, 2, 5]
    assert decoded[0]["Rewards"] == [{"ItemId": 100, "Count": 2}, {"ItemId": 200, "Count": 3}]
    assert decoded[0]["Note"] == "主语言"
    assert decoded[1]["Rewards"] == []
    assert decoded[1]["Tags"] == []
    assert decoded[1]["Note"] is None


def test_empty_and_partial_groups_round_trip() -> None:
    rows = [
        {"Id": 3, "Rarity": "Common", "Tags": [], "Rewards": [{"ItemId": 7, "Count": 1}], "Note": "x"},
    ]
    decoded = _read(_build(rows))
    assert decoded[0]["Rewards"] == [{"ItemId": 7, "Count": 1}]
    assert decoded[0]["Tags"] == []


def test_server_only_excluded() -> None:
    table = _table().model_copy(
        update={
            "fields": [
                *[f for f in _table().fields],
                FieldDef(name="Secret", type="int32", server_only=True),
            ]
        }
    )
    data = build_canonical_table_bytes(
        [{"Id": 1, "Rarity": "Common", "Tags": [], "Rewards": [], "Note": "", "Secret": 42}],
        table,
        records=_records(),
        enums=_enums(),
    )
    decoded = _read(data)
    assert "Secret" not in decoded[0]
