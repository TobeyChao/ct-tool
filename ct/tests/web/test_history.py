"""panel_history 结果值契约：状态码存储，旧账本展示串读取时归一。"""

from __future__ import annotations

from pathlib import Path

from ct.web.history import append_history, load_history, make_entry


def test_make_entry_writes_status_code() -> None:
    entry = make_entry(scope="全部表 × 全量语言", tables=4, elapsed=0.2)

    assert entry["result"] == "success"


def test_legacy_display_string_result_is_normalized(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    append_history(
        cache,
        {
            "time": "2026-01-01 00:00:00",
            "scope": "全部表 × 全量语言",
            "result": "成功",
            "tables": 1,
            "elapsed": 0.1,
            "forced": False,
            "error": "",
        },
    )

    entries = load_history(cache)

    assert [e["result"] for e in entries] == ["success"]
