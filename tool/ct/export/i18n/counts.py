"""i18n 状态计数共享模型（函数组合成类 6.9）。

sync / status / writer 三处此前各自数 translated/missing/stale/orphan；
此处收拢为 `StatusCounts` + `count_entries()`，状态比较统一走
`LangStatus` 枚举。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ct.export.i18n.state import LangStatus


@dataclass(frozen=True)
class StatusCounts:
    """一种语言/一张表的翻译状态计数（值对象，聚合用 __add__）。"""

    translated: int = 0
    missing: int = 0
    stale: int = 0
    orphan: int = 0

    def total(self) -> int:
        return self.translated + self.missing + self.stale + self.orphan

    def progress(self) -> float:
        """与现状一致：active = total - orphan，无活跃条目视为 100%。"""
        active = self.total() - self.orphan
        if active <= 0:
            return 1.0
        return self.translated / active

    def __add__(self, other: "StatusCounts") -> "StatusCounts":
        return StatusCounts(
            translated=self.translated + other.translated,
            missing=self.missing + other.missing,
            stale=self.stale + other.stale,
            orphan=self.orphan + other.orphan,
        )


def count_entries(entries: dict[str, dict[str, Any]]) -> StatusCounts:
    """统计 lang 文件条目的状态计数（status 字段缺失视为 0）。"""
    translated = missing = stale = orphan = 0
    for entry in entries.values():
        status = entry.get("status", "")
        if status == LangStatus.TRANSLATED.value:
            translated += 1
        elif status == LangStatus.MISSING.value:
            missing += 1
        elif status == LangStatus.STALE.value:
            stale += 1
        elif status == LangStatus.ORPHAN.value:
            orphan += 1
    return StatusCounts(
        translated=translated,
        missing=missing,
        stale=stale,
        orphan=orphan,
    )
