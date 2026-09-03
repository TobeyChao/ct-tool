"""Canonical Excel reader tests (4.4)."""

from __future__ import annotations

from pathlib import Path

from openpyxl import load_workbook

from ct.excel.canonical_reader import read_canonical_excel
from ct.excel.canonical_template import generate_canonical_template
from ct.excel.layout import build_layout
from ct.schema.resources import FieldDef, RecordResource, TableResource


def _records() -> dict[str, RecordResource]:
    return {
        "DropRange": RecordResource(
            name="DropRange",
            fields=[FieldDef(name="Min", type="int32"), FieldDef(name="Max", type="int32")],
        ),
        "DropReward": RecordResource(
            name="DropReward",
            fields=[FieldDef(name="ItemId", type="int32"), FieldDef(name="Count", type="int32")],
        ),
    }


def _table() -> TableResource:
    return TableResource(
        table="Item",
        primary="Id",
        fields=[
            FieldDef(name="Id", type="int32"),
            FieldDef(name="DropRange", type="DropRange"),
            FieldDef(name="Tags", type="vector<int32>", separator=","),
            FieldDef(name="Rewards", type="vector<DropReward>", excel_columns=3),
        ],
    )


def _make_template(tmp_path: Path) -> tuple[Path, TableResource]:
    table = _table()
    layout = build_layout(table, schema_hash="s", records=_records())
    template = generate_canonical_template(
        layout, tmp_path / "item.xlsx", enums={}, primary=table.primary
    )
    return template, table


def _read(path: Path, table: TableResource):
    layout = build_layout(table, schema_hash="s", records=_records())
    return read_canonical_excel(path, layout, table, records=_records())


def _append_row(path: Path, row: list) -> None:
    wb = load_workbook(str(path))
    wb.active.append(row)
    wb.save(str(path))


def test_record_and_expanded_vector_record_reassembled(tmp_path: Path) -> None:
    template, table = _make_template(tmp_path)
    # Id(1) Min(2) Max(3) Tags(4) then 3 Reward groups (2 cols each)
    _append_row(template, [1, 10, 20, "1,2,5", 10, 2, 20, 3, None, None])

    parsed = _read(template, table)
    assert len(parsed.rows) == 1
    row = parsed.rows[0]
    assert row["Id"] == 1
    assert row["DropRange"] == {"Min": 10, "Max": 20}
    assert row["Tags"] == [1, 2, 5]
    assert row["Rewards"] == [{"ItemId": 10, "Count": 2}, {"ItemId": 20, "Count": 3}]
    assert parsed.issues == []


def test_empty_trailing_groups_are_dropped(tmp_path: Path) -> None:
    template, table = _make_template(tmp_path)
    _append_row(template, [2, None, None, "", 30, 1, None, None, None, None])

    parsed = _read(template, table)
    assert parsed.rows[0]["Rewards"] == [{"ItemId": 30, "Count": 1}]
    assert parsed.rows[0]["DropRange"] == {"Min": None, "Max": None}


def test_vector_element_error_is_located(tmp_path: Path) -> None:
    template, table = _make_template(tmp_path)
    _append_row(template, [3, 1, 2, "1,abc", None, None, None, None, None, None])

    parsed = _read(template, table)
    assert len(parsed.issues) == 1
    issue = parsed.issues[0]
    assert "第2个元素" in issue.message
    assert issue.field == "table:Item/Tags"
    assert issue.column == 3  # 0-based column index for Tags
