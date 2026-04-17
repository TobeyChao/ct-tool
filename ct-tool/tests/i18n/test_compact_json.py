from __future__ import annotations

import json
from pathlib import Path

import pytest

from ct.cli_helpers.i18n_json import dump_lang_file, dump_source_file


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_empty_dict_writes_braces(tmp_path: Path) -> None:
    out = tmp_path / "empty.json"
    dump_source_file({}, out, ["name"])
    assert _read(out) == "{}\n"
    assert json.loads(_read(out)) == {}


def test_source_file_one_line_per_entry(tmp_path: Path) -> None:
    out = tmp_path / "item.json"
    data = {"1001.name": "铁剑", "1001.desc": "锋利的铁制长剑"}
    dump_source_file(data, out, ["name", "desc"])

    lines = _read(out).splitlines()
    assert lines[0] == "{"
    assert lines[-1] == "}"
    # 中间行各占一条 entry
    middle = [ln for ln in lines if ln not in ("{", "}")]
    assert len(middle) == 2
    # 每行内嵌的应该是单行紧凑值
    assert all("\n" not in ln for ln in middle)


def test_lang_file_one_line_per_entry(tmp_path: Path) -> None:
    out = tmp_path / "item_en.json"
    data = {
        "1001.name": {
            "source": "铁剑",
            "text": "Iron Sword",
            "confirmed": True,
            "status": "translated",
        },
    }
    dump_lang_file(data, out, ["name"])
    content = _read(out)
    assert (
        '  "1001.name": {"source": "铁剑", "text": "Iron Sword", "confirmed": true, "status": "translated"}'
        in content
    )


def test_unicode_and_emoji_preserved(tmp_path: Path) -> None:
    out = tmp_path / "item.json"
    data = {"1001.name": "魔晶石💎", "1001.desc": "★稀有道具★"}
    dump_source_file(data, out, ["name", "desc"])
    parsed = json.loads(_read(out))
    assert parsed == data


def test_numeric_id_sort_beats_lexicographic(tmp_path: Path) -> None:
    out = tmp_path / "item.json"
    # 字典序会把 100 排在 11 前面，数值序应保证 2 < 10 < 100
    data = {"100.name": "c", "10.name": "b", "2.name": "a"}
    dump_source_file(data, out, ["name"])
    lines = [ln for ln in _read(out).splitlines() if ln not in ("{", "}")]
    assert lines[0].startswith('  "2.')
    assert lines[1].startswith('  "10.')
    assert lines[2].startswith('  "100.')


def test_field_order_respected_within_same_id(tmp_path: Path) -> None:
    out = tmp_path / "item.json"
    data = {"1001.desc": "d", "1001.name": "n"}
    dump_source_file(data, out, ["name", "desc"])
    lines = [ln for ln in _read(out).splitlines() if ln not in ("{", "}")]
    assert lines[0].startswith('  "1001.name"')
    assert lines[1].startswith('  "1001.desc"')


def test_unknown_field_sorts_last_stably(tmp_path: Path) -> None:
    out = tmp_path / "item.json"
    data = {"1001.unknown": "u", "1001.name": "n"}
    dump_source_file(data, out, ["name"])
    lines = [ln for ln in _read(out).splitlines() if ln not in ("{", "}")]
    assert lines[0].startswith('  "1001.name"')
    assert lines[1].startswith('  "1001.unknown"')


def test_nested_object_value_serialized_inline(tmp_path: Path) -> None:
    out = tmp_path / "lang.json"
    data = {
        "1.f": {"a": 1, "b": [1, 2, 3], "c": {"nested": True}},
    }
    dump_lang_file(data, out, ["f"])
    content = _read(out)
    # 整个 entry 一行，无内部换行
    middle = [ln for ln in content.splitlines() if ln not in ("{", "}")]
    assert len(middle) == 1
    assert "\n" not in middle[0]
    assert json.loads(content) == data


def test_roundtrip_equivalence(tmp_path: Path) -> None:
    out = tmp_path / "lang.json"
    data = {
        "10.name": {"source": "甲", "text": "A", "confirmed": True, "status": "translated"},
        "2.name": {"source": "乙", "text": "", "confirmed": False, "status": "missing"},
    }
    dump_lang_file(data, out, ["name"])
    parsed = json.loads(_read(out))
    assert parsed == data


def test_string_id_falls_back_to_string_compare(tmp_path: Path) -> None:
    """非纯数字 id 也能稳定排序，不抛异常。"""
    out = tmp_path / "lang.json"
    data = {"abc.name": "a", "123.name": "b"}
    dump_source_file(data, out, ["name"])
    parsed = json.loads(_read(out))
    assert parsed == data
