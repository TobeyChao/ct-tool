"""导出历史：读写 cache/panel_history.json，保留最近 5 次。

``result`` 契约为状态码（当前 ``"success"``），前端负责本地化展示；
读取时把旧账本的中文展示串（``"成功"``）归一为状态码。
"""

from __future__ import annotations

import json
import time
from pathlib import Path

HISTORY_FILE = "panel_history.json"
KEEP = 5
RESULT_SUCCESS = "success"
#: 旧账本直接存展示串，读取时归一为状态码
_LEGACY_RESULT = {"成功": RESULT_SUCCESS}


def _history_path(cache_dir: Path) -> Path:
    return cache_dir / HISTORY_FILE


def _normalize(entry: dict) -> dict:
    result = entry.get("result")
    if result in _LEGACY_RESULT:
        return {**entry, "result": _LEGACY_RESULT[result]}
    return entry


def load_history(cache_dir: Path) -> list[dict]:
    path = _history_path(cache_dir)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return [_normalize(e) for e in data[-KEEP:] if isinstance(e, dict)]
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
    result: str = RESULT_SUCCESS,
    tables: int,
    elapsed: float,
    forced: bool = False,
    error: str = "",
) -> dict:
    """构造历史条目；``result`` 是状态码（当前只有 ``RESULT_SUCCESS``）。"""
    return {
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "scope": scope,
        "result": result,
        "tables": tables,
        "elapsed": round(elapsed, 2),
        "forced": forced,
        "error": error,
    }
