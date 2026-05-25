from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from ct.export.i18n.merger import load_translation, merge_translations
from ct.schema.models import FieldDef, TableSchema


def _schema() -> TableSchema:
    return TableSchema(
        table="item",
        primary="id",
        fields=[
            FieldDef(name="id", type="int32"),
            FieldDef(name="name", type="string", i18n=True),
            FieldDef(name="price", type="float"),
        ],
    )


def test_translated_used_when_text_and_confirmed() -> None:
    translations = {
        "1.name": {"source": "甲", "text": "A", "confirmed": True, "status": "translated"},
    }
    rows = [{"id": 1, "name": "甲", "price": 1.0}]
    out = merge_translations(rows, _schema(), "en", translations, "zh")
    assert out[0]["name"] == "A"


def test_stale_falls_back_to_source(caplog: pytest.LogCaptureFixture) -> None:
    translations = {
        "1.name": {"source": "甲", "text": "A", "confirmed": False, "status": "stale"},
    }
    rows = [{"id": 1, "name": "甲", "price": 1.0}]
    with caplog.at_level(logging.WARNING):
        out = merge_translations(rows, _schema(), "en", translations, "zh")
    assert out[0]["name"] == "甲"
    assert any("stale" in rec.message for rec in caplog.records)


def test_missing_text_falls_back(caplog: pytest.LogCaptureFixture) -> None:
    translations = {
        "1.name": {"source": "甲", "text": "", "confirmed": False, "status": "missing"},
    }
    rows = [{"id": 1, "name": "甲", "price": 1.0}]
    with caplog.at_level(logging.WARNING):
        out = merge_translations(rows, _schema(), "en", translations, "zh")
    assert out[0]["name"] == "甲"
    assert any("missing" in rec.message for rec in caplog.records)


def test_missing_entry_falls_back(caplog: pytest.LogCaptureFixture) -> None:
    rows = [{"id": 1, "name": "甲", "price": 1.0}]
    with caplog.at_level(logging.WARNING):
        out = merge_translations(rows, _schema(), "en", {}, "zh")
    assert out[0]["name"] == "甲"
    assert any("缺少 en 翻译条目" in rec.message for rec in caplog.records)


def test_load_translation_missing_file(tmp_path: Path) -> None:
    assert load_translation(tmp_path, "en", "item") == {}


def test_load_translation_returns_dict(tmp_path: Path) -> None:
    (tmp_path / "en").mkdir()
    payload = {"1.name": {"source": "甲", "text": "A", "confirmed": True, "status": "translated"}}
    (tmp_path / "en" / "item.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    assert load_translation(tmp_path, "en", "item") == payload


def test_no_i18n_returns_rows_unchanged() -> None:
    schema = TableSchema(
        table="config",
        primary="id",
        fields=[FieldDef(name="id", type="int32"), FieldDef(name="value", type="float")],
    )
    rows = [{"id": 1, "value": 1.0}]
    assert merge_translations(rows, schema, "en", {}, "zh") == rows


def test_confirmed_false_with_text_treated_stale(caplog: pytest.LogCaptureFixture) -> None:
    translations = {
        "1.name": {"source": "甲", "text": "Old", "confirmed": False, "status": "stale"},
    }
    rows = [{"id": 1, "name": "甲", "price": 1.0}]
    with caplog.at_level(logging.WARNING):
        out = merge_translations(rows, _schema(), "en", translations, "zh")
    assert out[0]["name"] == "甲"
