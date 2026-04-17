from __future__ import annotations

import logging
import sys
from collections import defaultdict

logger = logging.getLogger(__name__)


def report_stale_summary(source_strings: dict) -> None:
    """汇总并输出 stale 条目统计，按表分组。"""
    stale_by_table: dict[str, list[str]] = defaultdict(list)
    for key, entry in source_strings.items():
        if entry.get("status") == "stale":
            stale_by_table[entry["table"]].append(key)

    if not stale_by_table:
        return

    total = sum(len(v) for v in stale_by_table.values())
    print(f"\n⚠ 共 {total} 条 stale 翻译需要更新:", file=sys.stderr)
    for table, keys in sorted(stale_by_table.items()):
        print(f"  [{table}] {len(keys)} 条", file=sys.stderr)
        for k in keys[:5]:
            entry = source_strings[k]
            print(f"    - {entry['field']} (id={entry['id']})", file=sys.stderr)
        if len(keys) > 5:
            print(f"    ... 及其他 {len(keys) - 5} 条", file=sys.stderr)
