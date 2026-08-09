"""`ct/export/i18n/compact.py::compact_i18n` 应用层单测。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ct.config import GlobalConfig
from ct.export.i18n.compact import CompactError, compact_i18n
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
        ],
    )


def _lang_with_orphan(tmp_path: Path, schema: TableSchema) -> Path:
    cfg = _cfg(tmp_path, ["en"])
    sync_all(cfg, [schema], {"Item": [{"Id": 1, "Name": "铁剑"}]})
    path = tmp_path / "i18n" / "en" / "Item.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["9999.Name"] = {
        "source": "old",
        "text": "Old",
        "confirmed": True,
        "status": "orphan",
    }
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def test_compact_dry_run_collects_without_writing(tmp_path: Path) -> None:
    schema = _item_schema()
    path = _lang_with_orphan(tmp_path, schema)
    before = path.read_text(encoding="utf-8")

    summary = compact_i18n(_cfg(tmp_path, ["en"]), [schema], dry_run=True)

    assert summary.touched
    assert summary.total_removed == 0
    assert len(summary.files) == 1
    assert summary.files[0].removed_keys == ["9999.Name"]
    assert path.read_text(encoding="utf-8") == before


def test_compact_removes_orphans(tmp_path: Path) -> None:
    schema = _item_schema()
    path = _lang_with_orphan(tmp_path, schema)

    summary = compact_i18n(_cfg(tmp_path, ["en"]), [schema])

    assert summary.touched
    assert summary.total_removed == 1
    after = json.loads(path.read_text(encoding="utf-8"))
    assert "9999.Name" not in after
    assert "1.Name" in after


def test_compact_no_orphans(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, ["en"])
    schema = _item_schema()
    sync_all(cfg, [schema], {"Item": [{"Id": 1, "Name": "铁剑"}]})

    summary = compact_i18n(cfg, [schema])

    assert not summary.touched
    assert summary.files == []


def test_compact_invalid_lang_raises(tmp_path: Path) -> None:
    schema = _item_schema()
    with pytest.raises(CompactError, match="'fr' 不在 secondary_langs"):
        compact_i18n(_cfg(tmp_path, ["en"]), [schema], lang="fr")


def test_compact_table_filter(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, ["en"])
    schema = _item_schema()
    sync_all(cfg, [schema], {"Item": [{"Id": 1, "Name": "铁剑"}]})
    path = tmp_path / "i18n" / "en" / "Item.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["9999.Name"] = {
        "source": "old",
        "text": "Old",
        "confirmed": True,
        "status": "orphan",
    }
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    summary = compact_i18n(cfg, [schema], table="Nonexistent")

    assert not summary.touched
    assert summary.files == []
