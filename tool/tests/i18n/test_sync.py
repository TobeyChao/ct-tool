from __future__ import annotations

import json
from pathlib import Path

import pytest

from ct.config import GlobalConfig
from ct.export.i18n.sync import sync_all
from ct.schema.models import FieldDef, TableSchema


def _cfg(tmp_path: Path, secondary: list[str]) -> GlobalConfig:
    return GlobalConfig(
        primary_lang="zh",
        secondary_langs=secondary,
        i18n_dir="i18n",
        project_root=tmp_path,
    )


def _item_schema() -> TableSchema:
    return TableSchema(
        table="item",
        primary="id",
        fields=[
            FieldDef(name="id", type="int32"),
            FieldDef(name="name", type="string", i18n=True),
            FieldDef(name="desc", type="string", i18n=True),
        ],
    )


def _no_i18n_schema() -> TableSchema:
    return TableSchema(
        table="config",
        primary="id",
        fields=[FieldDef(name="id", type="int32"), FieldDef(name="value", type="float")],
    )


def test_first_sync_creates_dirs_and_files(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, ["en"])
    schema = _item_schema()
    rows = [{"id": 1, "name": "甲", "desc": "X"}]

    summary = sync_all(cfg, [schema], {"item": rows})

    assert (tmp_path / "i18n" / "source" / "item.json").exists()
    assert (tmp_path / "i18n" / "en" / "item.json").exists()
    assert summary.per_lang_table[("en", "item")].created == 2
    assert summary.per_lang_table[("en", "item")].missing == 2


def test_idempotent(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, ["en"])
    schema = _item_schema()
    rows = [{"id": 1, "name": "甲", "desc": "X"}]

    sync_all(cfg, [schema], {"item": rows})
    src1 = (tmp_path / "i18n" / "source" / "item.json").read_text(encoding="utf-8")
    lang1 = (tmp_path / "i18n" / "en" / "item.json").read_text(encoding="utf-8")

    sync_all(cfg, [schema], {"item": rows})
    src2 = (tmp_path / "i18n" / "source" / "item.json").read_text(encoding="utf-8")
    lang2 = (tmp_path / "i18n" / "en" / "item.json").read_text(encoding="utf-8")

    assert src1 == src2
    assert lang1 == lang2


def test_lang_filter_limits_lang_files(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, ["en", "ja"])
    schema = _item_schema()
    rows = [{"id": 1, "name": "甲", "desc": "X"}]

    sync_all(cfg, [schema], {"item": rows}, lang_filter="en")
    assert (tmp_path / "i18n" / "en" / "item.json").exists()
    assert not (tmp_path / "i18n" / "ja").exists()
    # source 仍然全量刷新
    assert (tmp_path / "i18n" / "source" / "item.json").exists()


def test_table_filter_limits_both(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, ["en"])
    item_schema = _item_schema()
    other = TableSchema(
        table="quest",
        primary="id",
        fields=[
            FieldDef(name="id", type="int32"),
            FieldDef(name="name", type="string", i18n=True),
        ],
    )

    sync_all(
        cfg,
        [item_schema, other],
        {"item": [{"id": 1, "name": "甲", "desc": "X"}], "quest": [{"id": 1, "name": "Q1"}]},
        table_filter="item",
    )
    assert (tmp_path / "i18n" / "source" / "item.json").exists()
    assert not (tmp_path / "i18n" / "source" / "quest.json").exists()


def test_skips_non_i18n_tables(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, ["en"])
    sync_all(cfg, [_no_i18n_schema()], {"config": [{"id": 1, "value": 1.0}]})
    assert not (tmp_path / "i18n").exists() or not list((tmp_path / "i18n").rglob("*.json"))


def test_source_change_marks_existing_translation_stale(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, ["en"])
    schema = _item_schema()

    sync_all(cfg, [schema], {"item": [{"id": 1, "name": "旧", "desc": "x"}]})
    lang_path = tmp_path / "i18n" / "en" / "item.json"
    data = json.loads(lang_path.read_text(encoding="utf-8"))
    data["1.name"]["text"] = "Old"
    data["1.name"]["confirmed"] = True
    data["1.name"]["status"] = "translated"
    lang_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    sync_all(cfg, [schema], {"item": [{"id": 1, "name": "新", "desc": "x"}]})
    data = json.loads(lang_path.read_text(encoding="utf-8"))
    assert data["1.name"]["status"] == "stale"
    assert data["1.name"]["confirmed"] is False
    assert data["1.name"]["text"] == "Old"
    assert data["1.name"]["source"] == "新"


def test_deleted_row_becomes_orphan(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, ["en"])
    schema = _item_schema()

    sync_all(cfg, [schema], {"item": [{"id": 1, "name": "甲", "desc": "X"}, {"id": 2, "name": "乙", "desc": "Y"}]})
    sync_all(cfg, [schema], {"item": [{"id": 1, "name": "甲", "desc": "X"}]})

    data = json.loads((tmp_path / "i18n" / "en" / "item.json").read_text(encoding="utf-8"))
    assert data["2.name"]["status"] == "orphan"
    assert data["2.desc"]["status"] == "orphan"


def test_summary_counts(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, ["en"])
    schema = _item_schema()
    rows = [{"id": 1, "name": "甲", "desc": "X"}, {"id": 2, "name": "乙", "desc": "Y"}]

    summary = sync_all(cfg, [schema], {"item": rows})
    stats = summary.per_lang_table[("en", "item")]
    assert stats.missing == 4
    assert stats.translated == 0
    totals = summary.totals_by_lang()
    assert totals["en"].missing == 4
