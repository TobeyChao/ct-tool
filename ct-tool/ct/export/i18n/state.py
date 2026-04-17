from __future__ import annotations

from enum import Enum
from typing import Any


class LangStatus(str, Enum):
    MISSING = "missing"
    TRANSLATED = "translated"
    STALE = "stale"
    ORPHAN = "orphan"


def compute_status(text: str, confirmed: bool, in_source: bool) -> LangStatus:
    """根据 text/confirmed/in_source 计算状态。"""
    if not in_source:
        return LangStatus.ORPHAN
    if not text:
        return LangStatus.MISSING
    if confirmed:
        return LangStatus.TRANSLATED
    return LangStatus.STALE


def merge_lang_entry(
    current_source: str | None,
    lang_entry: dict[str, Any] | None,
) -> dict[str, Any]:
    """根据当前 source 与已有 lang entry 计算更新后的 entry。

    规则：
    - current_source is None：key 已不在 source（orphan）。保留 source/text/confirmed，仅更新 status
    - lang_entry is None：新建条目 source=current, text="", confirmed=False
    - lang_entry.source != current_source：覆盖 source，强制 confirmed=False，保留 text
    - lang_entry.source == current_source：完全保留 source/text/confirmed
    最终始终重新计算 status。
    """
    if current_source is None:
        if lang_entry is None:
            raise ValueError("current_source 与 lang_entry 不能同时为空")
        source = str(lang_entry.get("source", ""))
        text = str(lang_entry.get("text", ""))
        confirmed = bool(lang_entry.get("confirmed", False))
        status = compute_status(text, confirmed, in_source=False)
        return {
            "source": source,
            "text": text,
            "confirmed": confirmed,
            "status": status.value,
        }

    if lang_entry is None:
        return {
            "source": current_source,
            "text": "",
            "confirmed": False,
            "status": LangStatus.MISSING.value,
        }

    existing_source = str(lang_entry.get("source", ""))
    text = str(lang_entry.get("text", ""))
    confirmed = bool(lang_entry.get("confirmed", False))

    if existing_source != current_source:
        source = current_source
        confirmed = False
    else:
        source = existing_source

    status = compute_status(text, confirmed, in_source=True)
    return {
        "source": source,
        "text": text,
        "confirmed": confirmed,
        "status": status.value,
    }


def sync_lang_table(
    source: dict[str, str],
    lang_existing: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """对一张表的所有 key 应用 merge_lang_entry，输出新的 lang dict。

    - 当前 source 中的 key：合并/新建
    - 仅在 lang_existing 中（即被删除的行/字段）：标记为 orphan
    """
    result: dict[str, dict[str, Any]] = {}

    for key, source_text in source.items():
        result[key] = merge_lang_entry(source_text, lang_existing.get(key))

    for key, entry in lang_existing.items():
        if key in source:
            continue
        result[key] = merge_lang_entry(None, entry)

    return result
