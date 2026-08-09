"""导出历史：读写 cache/panel_history.json，保留最近 5 次。"""

from __future__ import annotations

import json
import time
from pathlib import Path

HISTORY_FILE = "panel_history.json"
KEEP = 5


def _history_path(cache_dir: Path) -> Path:
    return cache_dir / HISTORY_FILE


def load_history(cache_dir: Path) -> list[dict]:
    path = _history_path(cache_dir)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data[-KEEP:]
    except (json.JSONDecodeError, OSError):
        pass
    return []


def append_history(cache_dir: Path, entry: dict) -> list[dict]:
    """追加一条历史并裁剪到最近 KEEP 条，返回当前列表。"""
    cache_dir.mkdir(parents=True, exist_ok=True)
    entries = load_history(cache_dir)
    entries.append(entry)
    entries = entries[-KEEP:]
    _history_path(cache_dir).write_text(
        json.dumps(entries, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return entries


def make_entry(
    *,
    scope: str,
    result: str,
    tables: int,
    elapsed: float,
    forced: bool = False,
    error: str = "",
) -> dict:
    return {
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "scope": scope,
        "result": result,
        "tables": tables,
        "elapsed": round(elapsed, 2),
        "forced": forced,
        "error": error,
    }
