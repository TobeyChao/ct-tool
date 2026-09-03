"""Excel data change-planning tests (4.5-4.7)."""

from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook

from ct.excel.layout import build_layout
from ct.excel.layout_manifest import LayoutManifest
from ct.excel.planning import plan_excel_migration


def _tracked_manifest(layout):
    return LayoutManifest.from_layout(layout)
from ct.schema.resources import FieldDef, RecordResource, TableResource


def _make_workbook(path: Path, header_rows: int, rows: list[list]) -> None:
    wb = Workbook()
    ws = wb.active
    for _ in range(header_rows):
        ws.append([""] * 8)
    for row in rows:
        ws.append(row)
    wb.save(str(path))


def _layout(table: TableResource, records: dict[str, RecordResource]):
    return build_layout(table, schema_hash="s", records=records)


def _records() -> dict[str, RecordResource]:
    return {
        "DropReward": RecordResource(
            name="DropReward",
            fields=[FieldDef(name="ItemId", type="int32"), FieldDef(name="Count", type="int32")],
        ),
    }


def test_reorder_maps_by_stable_path_not_position(tmp_path: Path) -> None:
    old_table = TableResource(
        table="Item", primary="Id",
        fields=[
            FieldDef(name="Id", type="int32"),
            FieldDef(name="Name", type="string"),
            FieldDef(name="Price", type="int32"),
        ],
    )
    new_table = TableResource(
        table="Item", primary="Id",
        fields=[
            FieldDef(name="Id", type="int32"),
            FieldDef(name="Price", type="int32"),
            FieldDef(name="Name", type="string"),
        ],
    )
    old_layout = _layout(old_table, {})
    new_layout = _layout(new_table, {})
    _make_workbook(tmp_path / "item.xlsx", old_layout.header_rows, [[1, "剑", 10]])

    plan = plan_excel_migration(
        old_layout, new_layout, tmp_path / "item.xlsx",
        manifest=_tracked_manifest(old_layout),
    )
    assert plan.blocked is False
    by_old = {migration.old_path: migration for migration in plan.migrations}
    assert by_old["table:Item/Name"].new_index == 3  # old col2 -> new col3
    assert by_old["table:Item/Price"].new_index == 2  # old col3 -> new col2
    assert by_old["table:Item/Id"].new_index == 1


def test_explicit_rename_map_wins(tmp_path: Path) -> None:
    old_table = TableResource(
        table="Item", primary="Id",
        fields=[FieldDef(name="Id", type="int32"), FieldDef(name="Name", type="string")],
    )
    new_table = TableResource(
        table="Item", primary="Id",
        fields=[FieldDef(name="Id", type="int32"), FieldDef(name="DisplayName", type="string")],
    )
    old_layout = _layout(old_table, {})
    new_layout = _layout(new_table, {})
    _make_workbook(tmp_path / "item.xlsx", old_layout.header_rows, [[1, "剑"]])

    plan = plan_excel_migration(
        old_layout,
        new_layout,
        tmp_path / "item.xlsx",
        rename_map={"table:Item/Name": "table:Item/DisplayName"},
        manifest=_tracked_manifest(old_layout),
    )
    assert plan.blocked is False
    name = next(m for m in plan.migrations if m.old_path == "table:Item/Name")
    assert name.new_path == "table:Item/DisplayName"


def test_deleted_column_with_data_blocks(tmp_path: Path) -> None:
    old_table = TableResource(
        table="Item", primary="Id",
        fields=[FieldDef(name="Id", type="int32"), FieldDef(name="Legacy", type="string")],
    )
    new_table = TableResource(
        table="Item", primary="Id", fields=[FieldDef(name="Id", type="int32")]
    )
    old_layout = _layout(old_table, {})
    new_layout = _layout(new_table, {})
    _make_workbook(tmp_path / "item.xlsx", old_layout.header_rows, [[1, "老数据"]])

    plan = plan_excel_migration(
        old_layout, new_layout, tmp_path / "item.xlsx",
        manifest=_tracked_manifest(old_layout),
    )
    assert plan.blocked is True
    blocker = next(issue for issue in plan.issues if issue.kind == "blocker")
    assert "Legacy" in blocker.message
    assert blocker.samples == ("老数据",)


def test_type_conversion_failure_blocks(tmp_path: Path) -> None:
    old_table = TableResource(
        table="Item", primary="Id",
        fields=[FieldDef(name="Id", type="int32"), FieldDef(name="Level", type="string")],
    )
    new_table = TableResource(
        table="Item", primary="Id",
        fields=[FieldDef(name="Id", type="int32"), FieldDef(name="Level", type="int32")],
    )
    old_layout = _layout(old_table, {})
    new_layout = _layout(new_table, {})
    _make_workbook(tmp_path / "item.xlsx", old_layout.header_rows, [[1, "abc"]])

    plan = plan_excel_migration(
        old_layout, new_layout, tmp_path / "item.xlsx",
        manifest=_tracked_manifest(old_layout),
    )
    blocker = next(issue for issue in plan.issues if issue.kind == "blocker")
    assert "不可转换" in blocker.message
    assert blocker.samples == ("abc",)


def test_enum_removal_with_data_blocks(tmp_path: Path) -> None:
    old_table = TableResource(
        table="Item", primary="Id",
        fields=[FieldDef(name="Id", type="int32"), FieldDef(name="Rarity", type="ItemRarity")],
    )
    new_table = TableResource(
        table="Item", primary="Id",
        fields=[FieldDef(name="Id", type="int32"), FieldDef(name="Rarity", type="ItemRarity")],
    )
    old_layout = _layout(old_table, {})
    new_layout = _layout(new_table, {})
    _make_workbook(tmp_path / "item.xlsx", old_layout.header_rows, [[1, "Legendary"]])

    plan = plan_excel_migration(
        old_layout,
        new_layout,
        tmp_path / "item.xlsx",
        old_enums={"ItemRarity": ("Common", "Rare", "Legendary")},
        new_enums={"ItemRarity": ("Common", "Rare")},
        manifest=_tracked_manifest(old_layout),
    )
    blocker = next(issue for issue in plan.issues if issue.kind == "blocker")
    assert "Legendary" in blocker.message


def test_excel_columns_shrink_with_data_blocks(tmp_path: Path) -> None:
    records = _records()
    old_table = TableResource(
        table="Item", primary="Id",
        fields=[
            FieldDef(name="Id", type="int32"),
            FieldDef(name="Rewards", type="vector<DropReward>", excel_columns=3),
        ],
    )
    new_table = TableResource(
        table="Item", primary="Id",
        fields=[
            FieldDef(name="Id", type="int32"),
            FieldDef(name="Rewards", type="vector<DropReward>", excel_columns=1),
        ],
    )
    old_layout = _layout(old_table, records)
    new_layout = _layout(new_table, records)
    _make_workbook(tmp_path / "item.xlsx", old_layout.header_rows, [[1, None, None, 30, 1, None, None]])

    plan = plan_excel_migration(
        old_layout, new_layout, tmp_path / "item.xlsx",
        manifest=_tracked_manifest(old_layout),
    )
    blocker = next(issue for issue in plan.issues if issue.kind == "blocker")
    assert "Rewards" in blocker.message


def test_untracked_workbook_requires_review(tmp_path: Path) -> None:
    old_table = TableResource(
        table="Item", primary="Id", fields=[FieldDef(name="Id", type="int32")]
    )
    new_table = TableResource(
        table="Item", primary="Id", fields=[FieldDef(name="Id", type="int32")]
    )
    old_layout = _layout(old_table, {})
    new_layout = _layout(new_table, {})
    _make_workbook(tmp_path / "item.xlsx", old_layout.header_rows, [[1]])

    plan = plan_excel_migration(old_layout, new_layout, tmp_path / "item.xlsx", manifest=None)
    assert plan.untracked is True
    assert plan.blocked is True
    assert any(issue.kind == "untracked" for issue in plan.issues)
