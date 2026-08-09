"""`ct/app/i18n.py::read_i18n_rows` 应用层单测。"""

from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook

from ct.app.i18n import read_i18n_rows
from ct.config import GlobalConfig
from ct.schema.models import FieldDef, TableSchema


def _cfg(tmp_path: Path) -> GlobalConfig:
    return GlobalConfig(
        primary_lang="zh",
        secondary_langs=["en"],
        excel_dir="excel",
        i18n_dir="i18n",
        project_root=tmp_path,
    )


def _i18n_schema(name: str) -> TableSchema:
    return TableSchema(
        table=name,
        primary="Id",
        fields=[
            FieldDef(name="Id", type="int32"),
            FieldDef(name="Name", type="string", i18n=True),
        ],
    )


def _no_i18n_schema(name: str) -> TableSchema:
    return TableSchema(
        table=name,
        primary="Id",
        fields=[FieldDef(name="Id", type="int32")],
    )


def _write_excel(path: Path, schema: TableSchema) -> None:
    (path.parent).mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.append(["id", "name"])
    ws.append(["主键", "名称"])
    ws.append([1, "铁剑"])
    wb.save(str(path))


def test_read_i18n_rows_collects_and_reports_missing(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    item = _i18n_schema("Item")
    quest = _i18n_schema("Quest")
    config = _no_i18n_schema("Config")
    _write_excel(tmp_path / "excel" / "Item.xlsx", item)

    result = read_i18n_rows(cfg, [config, item, quest])

    assert result.rows_by_table["Item"][0]["Id"] == 1
    assert "Config" not in result.rows_by_table
    assert result.missing == [("Quest", tmp_path / "excel" / "Quest.xlsx")]


def test_read_i18n_rows_table_filter(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    item = _i18n_schema("Item")
    quest = _i18n_schema("Quest")
    _write_excel(tmp_path / "excel" / "Item.xlsx", item)

    result = read_i18n_rows(cfg, [item, quest], table="Item")

    assert list(result.rows_by_table) == ["Item"]
    assert result.missing == []
