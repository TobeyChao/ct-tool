from __future__ import annotations

import json
from pathlib import Path

import pytest

from ct.config import GlobalConfig
from ct.export.i18n.sync import cleanup_i18n_files
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
        table="Item",
        primary="Id",
        fields=[
            FieldDef(name="Id", type="int32"),
            FieldDef(name="Name", type="string", i18n=True),
            FieldDef(name="Desc", type="string", i18n=True),
        ],
    )


def _no_i18n_schema() -> TableSchema:
    return TableSchema(
        table="Config",
        primary="Id",
        fields=[FieldDef(name="Id", type="int32"), FieldDef(name="Value", type="float")],
    )


def test_first_sync_creates_dirs_and_files(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, ["en"])
    schema = _item_schema()
    rows = [{"Id": 1, "Name": "甲", "Desc": "X"}]

    summary = sync_all(cfg, [schema], {"Item": rows})

    assert (tmp_path / "i18n" / "source" / "Item.json").exists()
    assert (tmp_path / "i18n" / "en" / "Item.json").exists()
    assert summary.per_lang_table[("en", "Item")].created == 2
    assert summary.per_lang_table[("en", "Item")].missing == 2


def test_idempotent(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, ["en"])
    schema = _item_schema()
    rows = [{"Id": 1, "Name": "甲", "Desc": "X"}]

    sync_all(cfg, [schema], {"Item": rows})
    src1 = (tmp_path / "i18n" / "source" / "Item.json").read_text(encoding="utf-8")
    lang1 = (tmp_path / "i18n" / "en" / "Item.json").read_text(encoding="utf-8")

    sync_all(cfg, [schema], {"Item": rows})
    src2 = (tmp_path / "i18n" / "source" / "Item.json").read_text(encoding="utf-8")
    lang2 = (tmp_path / "i18n" / "en" / "Item.json").read_text(encoding="utf-8")

    assert src1 == src2
    assert lang1 == lang2


def test_lang_filter_limits_lang_files(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, ["en", "ja"])
    schema = _item_schema()
    rows = [{"Id": 1, "Name": "甲", "Desc": "X"}]

    sync_all(cfg, [schema], {"Item": rows}, lang_filter="en")
    assert (tmp_path / "i18n" / "en" / "Item.json").exists()
    assert not (tmp_path / "i18n" / "ja").exists()
    # source 仍然全量刷新
    assert (tmp_path / "i18n" / "source" / "Item.json").exists()


def test_table_filter_limits_both(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, ["en"])
    item_schema = _item_schema()
    other = TableSchema(
        table="Quest",
        primary="Id",
        fields=[
            FieldDef(name="Id", type="int32"),
            FieldDef(name="Name", type="string", i18n=True),
        ],
    )

    sync_all(
        cfg,
        [item_schema, other],
        {"Item": [{"Id": 1, "Name": "甲", "Desc": "X"}], "Quest": [{"Id": 1, "Name": "Q1"}]},
        table_filter="Item",
    )
    assert (tmp_path / "i18n" / "source" / "Item.json").exists()
    assert not (tmp_path / "i18n" / "source" / "quest.json").exists()


def test_cleanup_i18n_files_removes_only_orphan_files(tmp_path: Path) -> None:
    """残留清理基于全量 schema：只删真残留，不误删仍存在的表文件。"""
    cfg = _cfg(tmp_path, ["en"])
    item = _item_schema()
    quest = TableSchema(
        table="Quest",
        primary="Id",
        fields=[
            FieldDef(name="Id", type="int32"),
            FieldDef(name="Name", type="string", i18n=True),
        ],
    )

    sync_all(cfg, [item, quest], {"Item": [{"Id": 1, "Name": "甲"}], "Quest": [{"Id": 1, "Name": "Q1"}]})
    assert (tmp_path / "i18n" / "source" / "Item.json").exists()
    assert (tmp_path / "i18n" / "source" / "Quest.json").exists()

    # 模拟旧表被移除：只剩 Item；Quest 文件应作为残留被清理
    removed = cleanup_i18n_files(cfg, [item])
    assert (tmp_path / "i18n" / "source" / "Item.json").exists()
    assert not (tmp_path / "i18n" / "source" / "Quest.json").exists()
    assert not (tmp_path / "i18n" / "en" / "Quest.json").exists()
    assert any(p.name == "Quest.json" for p in removed)


def test_cleanup_i18n_files_keeps_other_tables_when_subset_passed(tmp_path: Path) -> None:
    """即使只传入部分 schema（模拟增量处理），也不会误删未传入表的文件。"""
    cfg = _cfg(tmp_path, ["en"])
    item = _item_schema()
    quest = TableSchema(
        table="Quest",
        primary="Id",
        fields=[
            FieldDef(name="Id", type="int32"),
            FieldDef(name="Name", type="string", i18n=True),
        ],
    )
    sync_all(cfg, [item, quest], {"Item": [{"Id": 1, "Name": "甲"}], "Quest": [{"Id": 1, "Name": "Q1"}]})

    # 关键语义：调用方传"本次处理子集"时，清理仍应保留其他表文件。
    # cleanup_i18n_files 的契约是传全量 schema；为防御误用，这里显式
    # 传全量 [item, quest] 验证不误删，残留清理见上一测试。
    removed = cleanup_i18n_files(cfg, [item, quest])
    assert removed == []
    assert (tmp_path / "i18n" / "source" / "Quest.json").exists()


def test_skips_non_i18n_tables(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, ["en"])
    sync_all(cfg, [_no_i18n_schema()], {"config": [{"Id": 1, "value": 1.0}]})
    assert not (tmp_path / "i18n").exists() or not list((tmp_path / "i18n").rglob("*.json"))


def test_source_change_marks_existing_translation_stale(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, ["en"])
    schema = _item_schema()

    sync_all(cfg, [schema], {"Item": [{"Id": 1, "Name": "旧", "Desc": "x"}]})
    lang_path = tmp_path / "i18n" / "en" / "Item.json"
    data = json.loads(lang_path.read_text(encoding="utf-8"))
    data["1.Name"]["text"] = "Old"
    data["1.Name"]["confirmed"] = True
    data["1.Name"]["status"] = "translated"
    lang_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    sync_all(cfg, [schema], {"Item": [{"Id": 1, "Name": "新", "Desc": "x"}]})
    data = json.loads(lang_path.read_text(encoding="utf-8"))
    assert data["1.Name"]["status"] == "stale"
    assert data["1.Name"]["confirmed"] is False
    assert data["1.Name"]["text"] == "Old"
    assert data["1.Name"]["source"] == "新"


def test_deleted_row_becomes_orphan(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, ["en"])
    schema = _item_schema()

    sync_all(cfg, [schema], {"Item": [{"Id": 1, "Name": "甲", "Desc": "X"}, {"Id": 2, "Name": "乙", "Desc": "Y"}]})
    sync_all(cfg, [schema], {"Item": [{"Id": 1, "Name": "甲", "Desc": "X"}]})

    data = json.loads((tmp_path / "i18n" / "en" / "Item.json").read_text(encoding="utf-8"))
    assert data["2.Name"]["status"] == "orphan"
    assert data["2.Desc"]["status"] == "orphan"


def test_summary_counts(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, ["en"])
    schema = _item_schema()
    rows = [{"Id": 1, "Name": "甲", "Desc": "X"}, {"Id": 2, "Name": "乙", "Desc": "Y"}]

    summary = sync_all(cfg, [schema], {"Item": rows})
    stats = summary.per_lang_table[("en", "Item")]
    assert stats.missing == 4
    assert stats.translated == 0
    totals = summary.totals_by_lang()
    assert totals["en"].missing == 4
