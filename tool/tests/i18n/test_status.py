from __future__ import annotations

import json
from pathlib import Path

import pytest

from ct.cli_helpers.i18n_json import dump_lang_file
from ct.config import GlobalConfig
from ct.export.i18n.status import (
    compute_status_report,
    render_by_table,
    render_default,
    render_json,
)
from ct.schema.models import FieldDef, TableSchema


def _cfg(tmp_path: Path, langs: list[str]) -> GlobalConfig:
    return GlobalConfig(
        primary_lang="zh",
        secondary_langs=langs,
        i18n_dir="i18n",
        project_root=tmp_path,
    )


def _schema(name: str = "Item") -> TableSchema:
    return TableSchema(
        table=name,
        primary="Id",
        fields=[
            FieldDef(name="Id", type="int32"),
            FieldDef(name="Name", type="string", i18n=True),
        ],
    )


def _seed(tmp_path: Path, lang: str, table: str, data: dict) -> None:
    dump_lang_file(data, tmp_path / "i18n" / lang / f"{table}.json", ["name"])


def _entry(status: str) -> dict:
    return {
        "source": "甲",
        "text": "A" if status != "missing" else "",
        "confirmed": status == "translated",
        "status": status,
    }


def test_compute_counts_per_lang(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, ["en"])
    _seed(tmp_path, "en", "Item", {
        "1.Name": _entry("translated"),
        "2.Name": _entry("missing"),
        "3.Name": _entry("stale"),
        "4.Name": _entry("orphan"),
    })

    report = compute_status_report(cfg, [_schema()])
    lc = report.langs["en"]
    assert lc.total == 4
    assert lc.translated == 1
    assert lc.missing == 1
    assert lc.stale == 1
    assert lc.orphan == 1
    # progress 排除 orphan：1 / (4-1) = 0.333...
    assert round(lc.progress(), 3) == 0.333


def test_render_default_format(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, ["en"])
    _seed(tmp_path, "en", "Item", {"1.Name": _entry("translated")})
    report = compute_status_report(cfg, [_schema()])
    out = render_default(report)
    assert "[en]" in out
    assert "100%" in out
    assert "translated" in out


def test_render_by_table_lists_each_table(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, ["en"])
    _seed(tmp_path, "en", "Item", {"1.Name": _entry("translated")})
    _seed(tmp_path, "en", "Quest", {"1.Name": _entry("missing")})
    report = compute_status_report(cfg, [_schema("Item"), _schema("Quest")])
    out = render_by_table(report)
    assert "Item" in out
    assert "Quest" in out


def test_render_json_structure(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, ["en"])
    _seed(tmp_path, "en", "Item", {"1.Name": _entry("translated")})
    report = compute_status_report(cfg, [_schema()])
    parsed = json.loads(render_json(report))
    assert "langs" in parsed
    assert "en" in parsed["langs"]
    assert parsed["langs"]["en"]["translated"] == 1
    assert "tables" in parsed["langs"]["en"]


def test_lang_filter(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, ["en", "ja"])
    _seed(tmp_path, "en", "Item", {"1.Name": _entry("translated")})
    _seed(tmp_path, "ja", "Item", {"1.Name": _entry("missing")})
    report = compute_status_report(cfg, [_schema()], lang_filter="en")
    assert "en" in report.langs
    assert "ja" not in report.langs


def test_no_secondary_langs(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, [])
    report = compute_status_report(cfg, [_schema()])
    assert report.langs == {}
    assert "no secondary languages" in render_default(report)


def test_missing_lang_dir_treated_as_zero(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, ["en"])
    report = compute_status_report(cfg, [_schema()])
    lc = report.langs["en"]
    assert lc.total == 0
    assert lc.progress() == 1.0  # no active items → 100%
