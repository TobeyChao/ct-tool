"""canonical i18n: tables / entries / entry / status / compact round-trip."""

from __future__ import annotations

import json
from pathlib import Path

from openpyxl import Workbook

from _helpers import build_project
from ct.app.canonical_commands import (
    canonical_i18n_compact,
    canonical_i18n_entries,
    canonical_i18n_save_entry,
    canonical_i18n_status,
    canonical_i18n_sync,
    canonical_i18n_tables,
)
from ct.config import load_config


def _item_project(root: Path) -> Path:
    return build_project(
        root,
        schemas=[
            {
                "table": "Item",
                "primary": "Id",
                "fields": [
                    {"name": "Id", "type": "int32"},
                    {"name": "Name", "type": "string", "i18n": True},
                ],
            },
        ],
    )


def _write_item_excel(root: Path) -> None:
    (root / "excel").mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.append(["Id", "Name"])
    ws.append(["主键", "名称"])
    ws.append([1, "铁剑"])
    ws.append([2, "木剑"])
    wb.save(str(root / "excel" / "Item.xlsx"))


def test_i18n_tables_lists_has_i18n(tmp_path: Path) -> None:
    root = _item_project(tmp_path / "gd")
    tables = canonical_i18n_tables(root)
    assert tables[0]["table"] == "Item"
    assert tables[0]["has_i18n"] is True
    assert tables[0]["i18n_count"] == 1


def test_i18n_sync_writes_source_and_skeleton(tmp_path: Path) -> None:
    root = _item_project(tmp_path / "gd")
    _write_item_excel(root)
    messages = canonical_i18n_sync(root)
    assert "synced Item" in messages
    source = (root / "i18n" / "source" / "Item.json").read_text(encoding="utf-8")
    assert '"1.Name": "铁剑"' in source
    lang = (root / "i18n" / "en" / "Item.json").read_text(encoding="utf-8")
    assert "missing" in lang


def test_i18n_entries_computed(tmp_path: Path) -> None:
    root = _item_project(tmp_path / "gd")
    _write_item_excel(root)
    canonical_i18n_sync(root)
    entries = canonical_i18n_entries(root, "Item", "en")
    assert len(entries) == 2
    first = next(e for e in entries if e["id"] == "1")
    assert first["field"] == "Name"
    assert first["source"] == "铁剑"
    assert first["status"] == "missing"


def test_i18n_save_entry_marks_translated(tmp_path: Path) -> None:
    root = _item_project(tmp_path / "gd")
    _write_item_excel(root)
    canonical_i18n_sync(root)
    entry = canonical_i18n_save_entry(root, "Item", "en", "1.Name", "Iron Sword", True)
    assert entry["text"] == "Iron Sword"
    assert entry["confirmed"] is True
    assert entry["status"] == "translated"
    lang = (root / "i18n" / "en" / "Item.json").read_text(encoding="utf-8")
    assert "Iron Sword" in lang


def test_i18n_status_has_tables_and_progress(tmp_path: Path) -> None:
    root = _item_project(tmp_path / "gd")
    _write_item_excel(root)
    canonical_i18n_sync(root)
    status = canonical_i18n_status(root)
    en = status["en"]
    assert en["tables"]["Item"]["missing"] == 2
    assert en["total"] == 2
    assert isinstance(en["progress"], float)


def test_i18n_compact_preview_then_remove(tmp_path: Path) -> None:
    root = _item_project(tmp_path / "gd")
    _write_item_excel(root)
    canonical_i18n_sync(root)
    cfg = load_config(root)
    lang_path = cfg.resolve("i18n_dir") / "en" / "Item.json"
    data = json.loads(lang_path.read_text(encoding="utf-8"))
    data["999.Name"] = {"source": "幽灵", "text": "Ghost", "confirmed": True, "status": "translated"}
    lang_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    preview = canonical_i18n_compact(root, table_filter="Item", dry_run=True)
    assert preview["total_removed"] == 1
    assert preview["files"][0]["removed_keys"] == ["999.Name"]
    # dry_run 不落盘
    after_preview = json.loads(lang_path.read_text(encoding="utf-8"))
    assert "999.Name" in after_preview

    result = canonical_i18n_compact(root, table_filter="Item", dry_run=False)
    assert result["total_removed"] == 1
    after = json.loads(lang_path.read_text(encoding="utf-8"))
    assert "999.Name" not in after
