"""Fixed offsets must agree with standard vtable reads regardless of payloads."""
import itertools
import struct

import pytest
from flatbuffers.table import Table
from flatbuffers import number_types as N

from ct.export.canonical_binary import (
    _row_vtables, build_canonical_table_bytes, count_vtables,
    plan_object_layout, probe_row_layout,
)
from ct.schema.resources import FieldDef, RecordResource, TableResource


@pytest.mark.parametrize('order', list(itertools.permutations(['Id', 'Value', 'Text'])))
@pytest.mark.parametrize('kind,fmt,flags', [
    ('double', 'd', N.Float64Flags), ('int64', 'q', N.Int64Flags),
    ('uint64', 'Q', N.Uint64Flags),
])
def test_wide_fields_match_literal_and_standard_reads(order, kind, fmt, flags):
    types = {'Id': 'int32', 'Value': kind, 'Text': 'string'}
    table = TableResource(table='Wide', primary='Id', fields=[
        FieldDef(name=name, type=types[name]) for name in order
    ])
    rows = [{'Id': i + 1, 'Value': (i + .25 if kind == 'double' else 2**60 + i),
             'Text': '字' * i} for i in range(40)]
    rows[0]['Value'] = 0
    data = build_canonical_table_bytes(rows, table, records={}, enums={}, uniform=True)
    layout = plan_object_layout(table.fields, {})
    assert count_vtables(data) == 1
    assert probe_row_layout(table, records={}, enums={}) == layout.slot_offsets
    for expected, (row, vt, _) in zip(rows, _row_vtables(data)):
        assert row % layout.alignment == 0
        assert struct.unpack_from('<H', data, vt + 2)[0] == layout.size
        standard = Table(data, row)
        for name, code, flag in [('Id', 'i', N.Int32Flags), ('Value', fmt, flags)]:
            slot = 4 + 2 * order.index(name)
            off = layout.slot_offsets[slot]
            assert standard.Offset(slot) == off
            assert standard.Get(flag, row + standard.Offset(slot)) == expected[name]
            assert struct.unpack_from('<' + code, data, row + off)[0] == expected[name]
        slot = 4 + 2 * order.index('Text')
        assert standard.String(row + layout.slot_offsets[slot]).decode() == expected['Text']


def test_minimal_double_table_has_stable_layout():
    table = TableResource(table='Wide', primary='Id', fields=[
        FieldDef(name='Id', type='int32'), FieldDef(name='Value', type='double')])
    data = build_canonical_table_bytes(
        [{'Id': i, 'Value': i + .5} for i in range(1, 10)],
        table, records={}, enums={}, uniform=True)
    assert count_vtables(data) == 1
    for row, vt, _ in _row_vtables(data):
        assert struct.unpack_from('<HH', data, vt + 4) == (4, 8)
        assert row % 8 == 0


def test_nested_records_and_wide_vectors_with_variable_payloads():
    record = RecordResource(name='Detail', fields=[
        FieldDef(name='Flag', type='bool'), FieldDef(name='Value', type='double'),
        FieldDef(name='Text', type='string'), FieldDef(name='Small', type='uint16')])
    records = {'Detail': record}
    table = TableResource(table='Wide', primary='Id', fields=[
        FieldDef(name='Id', type='int32'), FieldDef(name='Detail', type='Detail'),
        FieldDef(name='Details', type='vector<Detail>'),
        FieldDef(name='Values', type='vector<double>')])
    rows = [{'Id': i, 'Detail': {'Value': i + .5, 'Text': 'a' * i},
             'Details': [{'Value': j + .25, 'Text': '字' * j} for j in range(i)],
             'Values': [j + .75 for j in range(i)]} for i in range(12)]
    data = build_canonical_table_bytes(rows, table, records=records, enums={}, uniform=True)
    layout = plan_object_layout(record.fields, records)
    assert count_vtables(data) == 1

    def check(pos, expected):
        obj = Table(data, pos)
        assert pos % 8 == 0
        assert [obj.Offset(4 + i * 2) for i in range(4)] == list(layout.offsets)
        assert obj.Get(N.Float64Flags, pos + obj.Offset(6)) == expected['Value']
        assert obj.String(pos + obj.Offset(8)).decode() == expected['Text']

    for expected, (pos, _, _) in zip(rows, _row_vtables(data)):
        obj = Table(data, pos)
        check(obj.Indirect(pos + obj.Offset(6)), expected['Detail'])
        vec = obj.Vector(obj.Offset(8))
        assert obj.VectorLen(obj.Offset(8)) == len(expected['Details'])
        for j, detail in enumerate(expected['Details']):
            check(obj.Indirect(vec + j * 4), detail)
        vec = obj.Vector(obj.Offset(10))
        assert vec % 8 == 0
        for j, value in enumerate(expected['Values']):
            assert struct.unpack_from('<d', data, vec + j * 8)[0] == value
