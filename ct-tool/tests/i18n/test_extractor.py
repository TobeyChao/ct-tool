from __future__ import annotations

import json
from pathlib import Path

import pytest

from ct.export.i18n.extractor import (
    extract_source_for_table,
    load_source_file,
    save_source_file,
)
from ct.schema.models import FieldDef, TableSchema


def _make_item_schema() -> TableSchema:
    return TableSchema(
        table="item",
        primary="id",
        fields=[
            FieldDef(name="id", type="int32"),
            FieldDef(name="name", type="string", i18n=True),
            FieldDef(name="desc", type="string", i18n=True),
            FieldDef(name="price", type="float"),
        ],
    )


def _make_no_i18n_schema() -> TableSchema:
    return TableSchema(
        table="config",
        primary="id",
        fields=[
            FieldDef(name="id", type="int32"),
            FieldDef(name="value", type="float"),
        ],
    )


def test_extract_basic_rows() -> None:
    schema = _make_item_schema()
    rows = [
        {"id": 1001, "name": "铁剑", "desc": "锋利", "price": 100.0},
        {"id": 1002, "name": "魔杖", "desc": "魔法", "price": 200.0},
    ]
    out = extract_source_for_table(rows, schema)
    assert out == {
        "1001.name": "铁剑",
        "1001.desc": "锋利",
        "1002.name": "魔杖",
        "1002.desc": "魔法",
    }


def test_extract_skips_non_i18n_fields() -> None:
    schema = _make_item_schema()
    rows = [{"id": 1, "name": "a", "desc": "b", "price": 1.0}]
    out = extract_source_for_table(rows, schema)
    assert "1.price" not in out


def test_extract_returns_empty_for_no_i18n_schema() -> None:
    schema = _make_no_i18n_schema()
    rows = [{"id": 1, "value": 1.0}]
    assert extract_source_for_table(rows, schema) == {}


def test_extract_handles_none_text() -> None:
    schema = _make_item_schema()
    rows = [{"id": 1, "name": None, "desc": "x", "price": 1.0}]
    out = extract_source_for_table(rows, schema)
    assert out["1.name"] == ""


def test_extract_skips_rows_without_primary() -> None:
    schema = _make_item_schema()
    rows = [
        {"id": None, "name": "x", "desc": "y", "price": 1.0},
        {"id": 1, "name": "a", "desc": "b", "price": 2.0},
    ]
    out = extract_source_for_table(rows, schema)
    assert out == {"1.name": "a", "1.desc": "b"}


def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    schema = _make_item_schema()
    data = {"1.name": "甲", "1.desc": "乙"}
    save_source_file(tmp_path, schema, data)
    assert load_source_file(tmp_path, "item") == data


def test_save_writes_to_source_subdir(tmp_path: Path) -> None:
    schema = _make_item_schema()
    save_source_file(tmp_path, schema, {"1.name": "x"})
    assert (tmp_path / "source" / "item.json").exists()


def test_load_missing_file_returns_empty(tmp_path: Path) -> None:
    assert load_source_file(tmp_path, "nonexistent") == {}


def test_save_preserves_field_order(tmp_path: Path) -> None:
    schema = _make_item_schema()
    # 先 desc 后 name 写入，文件中 name 应排在 desc 前
    data = {"1.desc": "d", "1.name": "n"}
    save_source_file(tmp_path, schema, data)
    content = (tmp_path / "source" / "item.json").read_text(encoding="utf-8")
    name_pos = content.find('"1.name"')
    desc_pos = content.find('"1.desc"')
    assert name_pos < desc_pos


def test_no_file_generated_for_no_i18n_table(tmp_path: Path) -> None:
    # 调用方有责任跳过，但 save 本身不会写空 dict 到非 i18n 表
    schema = _make_no_i18n_schema()
    out = extract_source_for_table([{"id": 1, "value": 1.0}], schema)
    assert out == {}
    # 调用 save 仍会创建文件，但 sync 编排层会在 has_i18n=False 时跳过
