"""Canonical Excel layout + layout manifest tests."""

from __future__ import annotations

from pathlib import Path

from ct.excel.layout import build_layout
from ct.excel.layout_manifest import (
    LayoutManifest,
    load_manifest,
    save_manifest,
)
from ct.schema.resources import EnumResource, FieldDef, RecordResource, TableResource


def _table(fields: list[FieldDef]) -> TableResource:
    return TableResource(table="Item", primary="Id", fields=fields)


def _record(name: str, fields: list[FieldDef]) -> RecordResource:
    return RecordResource(name=name, fields=fields)


def test_flat_table_layout() -> None:
    table = _table(
        [
            FieldDef(name="Id", type="int32"),
            FieldDef(name="Rarity", type="ItemRarity"),
            FieldDef(name="Tags", type="vector<int32>", separator=","),
        ]
    )
    layout = build_layout(
        table,
        schema_hash="abc",
        records={},
    )
    assert layout.column_count == 3
    assert layout.header_rows == 2  # one name/type row + comment row
    paths = [column.stable_path for column in layout.columns]
    assert paths == [
        "table:Item/Id",
        "table:Item/Rarity",
        "table:Item/Tags",
    ]
    assert layout.columns[1].annotation == "ItemRarity"
    assert layout.columns[2].annotation == "vector<int32>"


def test_record_field_expands_to_multiple_columns() -> None:
    table = _table(
        [
            FieldDef(name="Id", type="int32"),
            FieldDef(name="DropRange", type="DropRange"),
        ]
    )
    records = {
        "DropRange": _record(
            "DropRange",
            [FieldDef(name="Min", type="int32"), FieldDef(name="Max", type="int32")],
        )
    }
    layout = build_layout(table, schema_hash="abc", records=records)
    paths = [column.stable_path for column in layout.columns]
    assert paths == [
        "table:Item/Id",
        "table:Item/DropRange/Min",
        "table:Item/DropRange/Max",
    ]
    # field + record leaf + comment row
    assert layout.header_rows == 3


def test_expanded_vector_record_groups() -> None:
    table = _table(
        [
            FieldDef(name="Id", type="int32"),
            FieldDef(name="Rewards", type="vector<DropReward>", excel_columns=3),
        ]
    )
    records = {
        "DropReward": _record(
            "DropReward",
            [FieldDef(name="ItemId", type="int32"), FieldDef(name="Count", type="int32")],
        )
    }
    layout = build_layout(table, schema_hash="abc", records=records)
    assert layout.column_count == 1 + 3 * 2
    assert layout.columns[1].stable_path == "table:Item/Rewards[1]/ItemId"
    assert layout.columns[1].group_index == 1
    assert layout.columns[3].stable_path == "table:Item/Rewards[2]/ItemId"
    assert layout.columns[3].group_index == 2
    # field + group + record leaf + comment row
    assert layout.header_rows == 4


def test_single_cell_vector_record_has_no_groups() -> None:
    table = _table(
        [
            FieldDef(name="Id", type="int32"),
            FieldDef(name="Rewards", type="vector<DropReward>"),
        ]
    )
    records = {
        "DropReward": _record(
            "DropReward", [FieldDef(name="ItemId", type="int32")]
        )
    }
    layout = build_layout(table, schema_hash="abc", records=records)
    assert layout.column_count == 2
    assert layout.columns[1].stable_path == "table:Item/Rewards"
    assert layout.columns[1].group_index is None


def test_logical_path_strips_group_marker() -> None:
    table = _table(
        [
            FieldDef(name="Id", type="int32"),
            FieldDef(name="Rewards", type="vector<DropReward>", excel_columns=2),
        ]
    )
    records = {"DropReward": _record("DropReward", [FieldDef(name="Min", type="int32")])}
    layout = build_layout(table, schema_hash="abc", records=records)
    assert layout.columns[1].logical_path == "table:Item/Rewards/Min"


def test_manifest_create_read_and_revision(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    table = _table([FieldDef(name="Id", type="int32")])
    layout = build_layout(table, schema_hash="abc", records={})

    assert load_manifest(cache, "Item") is None
    save_manifest(cache, "Item", LayoutManifest.from_layout(layout))
    first = load_manifest(cache, "Item")
    assert first is not None and first.layout_revision == 1
    assert first.schema_hash == "abc"
    assert first.columns[0]["stablePath"] == "table:Item/Id"

    save_manifest(cache, "Item", LayoutManifest.from_layout(layout, previous_revision=first.layout_revision))
    second = load_manifest(cache, "Item")
    assert second is not None and second.layout_revision == 2


def test_manifest_missing_and_corruption(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    assert load_manifest(cache, "Item") is None

    path = cache / "template_layouts" / "Item.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ not json", encoding="utf-8")
    assert load_manifest(cache, "Item") is None

    path.write_text('{"format":"template-layout/1","columns":[]}', encoding="utf-8")
    manifest = load_manifest(cache, "Item")
    assert manifest is not None and manifest.columns == ()
