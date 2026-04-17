from __future__ import annotations

import pytest

from ct.export.i18n.state import (
    LangStatus,
    compute_status,
    merge_lang_entry,
    sync_lang_table,
)


class TestComputeStatus:
    def test_orphan_when_not_in_source(self) -> None:
        assert compute_status("any", True, in_source=False) == LangStatus.ORPHAN
        assert compute_status("", False, in_source=False) == LangStatus.ORPHAN

    def test_missing_when_text_empty(self) -> None:
        assert compute_status("", False, in_source=True) == LangStatus.MISSING
        assert compute_status("", True, in_source=True) == LangStatus.MISSING

    def test_translated_when_text_and_confirmed(self) -> None:
        assert compute_status("hello", True, in_source=True) == LangStatus.TRANSLATED

    def test_stale_when_text_but_not_confirmed(self) -> None:
        assert compute_status("hello", False, in_source=True) == LangStatus.STALE


class TestMergeLangEntry:
    def test_new_key_creates_missing_entry(self) -> None:
        out = merge_lang_entry("铁剑", None)
        assert out == {
            "source": "铁剑",
            "text": "",
            "confirmed": False,
            "status": "missing",
        }

    def test_unchanged_source_preserves_translation(self) -> None:
        existing = {"source": "铁剑", "text": "Iron Sword", "confirmed": True, "status": "translated"}
        out = merge_lang_entry("铁剑", existing)
        assert out == {
            "source": "铁剑",
            "text": "Iron Sword",
            "confirmed": True,
            "status": "translated",
        }

    def test_source_change_resets_confirmed_keeps_text(self) -> None:
        existing = {"source": "铁剑", "text": "Iron Sword", "confirmed": True, "status": "translated"}
        out = merge_lang_entry("精铁剑", existing)
        assert out["source"] == "精铁剑"
        assert out["text"] == "Iron Sword"
        assert out["confirmed"] is False
        assert out["status"] == "stale"

    def test_translator_confirms_after_stale(self) -> None:
        # 翻译者把 text 更新并把 confirmed 改 true
        existing = {"source": "精铁剑", "text": "Refined Iron Sword", "confirmed": True, "status": "stale"}
        out = merge_lang_entry("精铁剑", existing)
        assert out["status"] == "translated"
        assert out["confirmed"] is True

    def test_orphan_preserves_source_and_text(self) -> None:
        existing = {"source": "已删除道具", "text": "Deleted", "confirmed": True, "status": "translated"}
        out = merge_lang_entry(None, existing)
        assert out["source"] == "已删除道具"
        assert out["text"] == "Deleted"
        assert out["confirmed"] is True
        assert out["status"] == "orphan"

    def test_orphan_with_no_entry_raises(self) -> None:
        with pytest.raises(ValueError):
            merge_lang_entry(None, None)

    def test_empty_text_in_existing_stays_missing(self) -> None:
        existing = {"source": "铁剑", "text": "", "confirmed": False, "status": "missing"}
        out = merge_lang_entry("铁剑", existing)
        assert out["status"] == "missing"


class TestSyncLangTable:
    def test_first_sync_creates_all_missing(self) -> None:
        source = {"1.name": "甲", "2.name": "乙"}
        out = sync_lang_table(source, {})
        assert set(out.keys()) == {"1.name", "2.name"}
        for entry in out.values():
            assert entry["status"] == "missing"
            assert entry["text"] == ""
            assert entry["confirmed"] is False

    def test_idempotent_no_changes(self) -> None:
        source = {"1.name": "甲"}
        existing = {
            "1.name": {"source": "甲", "text": "A", "confirmed": True, "status": "translated"},
        }
        out1 = sync_lang_table(source, existing)
        out2 = sync_lang_table(source, out1)
        assert out1 == out2

    def test_deleted_row_becomes_orphan(self) -> None:
        source = {"1.name": "甲"}
        existing = {
            "1.name": {"source": "甲", "text": "A", "confirmed": True, "status": "translated"},
            "99.name": {"source": "已删", "text": "Old", "confirmed": True, "status": "translated"},
        }
        out = sync_lang_table(source, existing)
        assert out["1.name"]["status"] == "translated"
        assert out["99.name"]["status"] == "orphan"
        assert out["99.name"]["text"] == "Old"

    def test_source_change_invalidates(self) -> None:
        source = {"1.name": "新原文"}
        existing = {
            "1.name": {"source": "旧原文", "text": "Translation", "confirmed": True, "status": "translated"},
        }
        out = sync_lang_table(source, existing)
        assert out["1.name"]["source"] == "新原文"
        assert out["1.name"]["text"] == "Translation"
        assert out["1.name"]["confirmed"] is False
        assert out["1.name"]["status"] == "stale"

    def test_new_key_added_alongside_existing(self) -> None:
        source = {"1.name": "甲", "2.name": "新增"}
        existing = {
            "1.name": {"source": "甲", "text": "A", "confirmed": True, "status": "translated"},
        }
        out = sync_lang_table(source, existing)
        assert out["1.name"]["status"] == "translated"
        assert out["2.name"]["status"] == "missing"
