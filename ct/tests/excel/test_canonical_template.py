"""Canonical template workbook generation tests (4.2)."""

from __future__ import annotations

from pathlib import Path

from openpyxl import load_workbook

from ct.excel.canonical_template import generate_canonical_template
from ct.excel.layout import build_layout
from ct.schema.resources import EnumResource, FieldDef, RecordResource, TableResource


def _table() -> TableResource:
    return TableResource(
        table="Item",
        primary="Id",
        fields=[
            FieldDef(name="Id", type="int32", comment="主键"),
            FieldDef(name="Rarity", type="ItemRarity", comment="品质"),
            FieldDef(name="DropRange", type="DropRange", comment="掉落区间"),
            FieldDef(
                name="Rewards",
                type="vector<DropReward>",
                excel_columns=2,
                comment="奖励组",
            ),
        ],
    )


def _records() -> dict[str, RecordResource]:
    return {
        "DropRange": RecordResource(
            name="DropRange",
            fields=[
                FieldDef(name="Min", type="int32", comment="下限"),
                FieldDef(name="Max", type="int32", comment="上限"),
            ],
        ),
        "DropReward": RecordResource(
            name="DropReward",
            fields=[
                FieldDef(name="ItemId", type="int32", comment="道具"),
                FieldDef(name="Count", type="int32", comment="数量"),
            ],
        ),
    }


def test_template_headers_follow_layout(tmp_path: Path) -> None:
    table = _table()
    records = _records()
    layout = build_layout(table, schema_hash="sha1", records=records)
    enums = {"ItemRarity": EnumResource(name="ItemRarity", values=["Common", "Rare"])}
    out = generate_canonical_template(
        layout, tmp_path / "item.xlsx", enums=enums, primary=table.primary
    )

    assert out.exists()
    wb = load_workbook(str(out))
    ws = wb.active
    assert ws.max_row == layout.header_rows
    # row 1 top-level fields: Id(1) Rarity(2) DropRange(3-4) Rewards(5-8)
    assert "Rewards" in str(ws.cell(row=2, column=5).value)
    assert "vector<DropReward>" in str(ws.cell(row=2, column=5).value)
    assert "DropRange" in str(ws.cell(row=2, column=3).value)
    assert {"A2:A6", "B2:B6", "C1:D1", "C2:D2", "C4:C6", "D4:D6", "E1:H1", "E2:H2", "E3:F3", "G3:H3", "E4:F4", "G4:H4"}.issubset({str(item) for item in ws.merged_cells.ranges})
    # group header on row 2
    assert "1" in str(ws.cell(row=4, column=5).value)
    # record leaf on row 2 (DropRange depth 2)
    assert "Min" in str(ws.cell(row=4, column=3).value)
    # comment row: per-leaf comments
    assert ws.cell(row=1, column=1).value == "主键"
    assert ws.cell(row=3, column=3).value == "下限"
    assert ws.cell(row=5, column=5).value == "道具"

    # metadata
    props = {prop.name: prop.value for prop in wb.custom_doc_props}
    assert props["ct_schema_hash"] == "sha1"
    assert props["ct_header_rows"] == layout.header_rows

    # The selection belongs to the scrollable pane and must start below the
    # frozen header; otherwise Excel initially renders the header twice.
    selection = ws.sheet_view.selection[0]
    assert selection.pane == "bottomLeft"
    assert selection.activeCell == f"A{layout.header_rows + 1}"
    assert selection.sqref == f"A{layout.header_rows + 1}"

    # enum dropdown on Rarity column (col 2)
    formulas = [dv.formula1 for dv in ws.data_validations.dataValidation]
    assert any("Common" in formula and "Rare" in formula for formula in formulas)
    wb.close()


def test_template_golden_stable_across_runs(tmp_path: Path) -> None:
    table = _table()
    records = _records()
    layout = build_layout(table, schema_hash="sha2", records=records)
    enums = {"ItemRarity": EnumResource(name="ItemRarity", values=["Common", "Rare"])}
    first = tmp_path / "a.xlsx"
    second = tmp_path / "b.xlsx"
    generate_canonical_template(layout, first, enums=enums, primary=table.primary)
    generate_canonical_template(layout, second, enums=enums, primary=table.primary)
    assert first.read_bytes() == second.read_bytes()


def test_template_has_no_data_validation_input_prompts(tmp_path: Path) -> None:
    table = TableResource(
        table="PromptFree",
        primary="Id",
        fields=[
            FieldDef(name="Id", type="int64"),
            FieldDef(name="ItemId", type="int32", ref="Item.Id"),
            FieldDef(name="Enabled", type="bool"),
        ],
    )
    layout = build_layout(table, schema_hash="prompt-free", records={})
    out = generate_canonical_template(
        layout,
        tmp_path / "prompt_free.xlsx",
        enums={},
        primary="Id",
    )

    wb = load_workbook(str(out))
    validations = wb.active.data_validations.dataValidation
    assert validations
    assert all(not validation.showInputMessage for validation in validations)
    wb.close()


def test_fixed_scalar_vector_comment_is_merged(tmp_path: Path) -> None:
    table = TableResource(
        table="Quest",
        primary="Id",
        fields=[
            FieldDef(name="Id", type="int32"),
            FieldDef(name="Test", type="vector<int32>", excel_columns=2, comment="测试字段"),
        ],
    )
    layout = build_layout(table, schema_hash="sha3", records={})
    out = generate_canonical_template(layout, tmp_path / "quest.xlsx", enums={}, primary="Id")

    wb = load_workbook(str(out))
    ws = wb.active
    assert "B2:C2" in {str(item) for item in ws.merged_cells.ranges}
    assert ws.cell(row=1, column=2).value == "测试字段"
    assert ws.cell(row=layout.header_rows - 1, column=2).value == "数据项[1]"
    assert ws.cell(row=layout.header_rows - 1, column=3).value == "数据项[2]"
    wb.close()


def test_nested_record_merges_preserve_node_spans(tmp_path: Path) -> None:
    table = TableResource(
        table="World",
        primary="Id",
        fields=[FieldDef(name="Id", type="int32"), FieldDef(name="Position", type="Position")],
    )
    records = {
        "Position": RecordResource(name="Position", fields=[FieldDef(name="Area", type="Area"), FieldDef(name="Z", type="int32")]),
        "Area": RecordResource(name="Area", fields=[FieldDef(name="X", type="int32"), FieldDef(name="Y", type="int32")]),
    }
    layout = build_layout(table, schema_hash="nested", records=records)
    out = generate_canonical_template(layout, tmp_path / "world.xlsx", enums={}, primary="Id")
    ws = load_workbook(str(out)).active
    merges = {str(item) for item in ws.merged_cells.ranges}
    assert {"A2:A6", "B1:D1", "B2:D2", "B3:C3", "B4:C4", "D4:D6"}.issubset(merges)
