from __future__ import annotations

import logging
from collections import defaultdict
from pathlib import Path
from typing import Iterable

from ct.config import GlobalConfig
from ct.export.i18n.merger import load_translation
from ct.schema.models import TableSchema

logger = logging.getLogger(__name__)


def report_stale_summary(
    cfg: GlobalConfig,
    schemas: Iterable[TableSchema],
) -> None:
    """汇总每语言每表中非 translated 状态的条目，输出 stderr。"""
    import sys

    i18n_dir = cfg.resolve("i18n_dir")
    i18n_schemas = [s for s in schemas if s.has_i18n]
    if not i18n_schemas or not cfg.secondary_langs:
        return

    needs_attention = False
    for lang in cfg.secondary_langs:
        per_table_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        any_attention = False
        for schema in i18n_schemas:
            entries = load_translation(i18n_dir, lang, schema.table)
            for entry in entries.values():
                status = entry.get("status", "")
                if status in ("missing", "stale", "orphan"):
                    per_table_counts[schema.table][status] += 1
                    any_attention = True
        if any_attention:
            needs_attention = True
            print(f"\n[i18n] {lang} 待处理:", file=sys.stderr)
            for table, counts in sorted(per_table_counts.items()):
                parts = []
                for s in ("missing", "stale", "orphan"):
                    if counts.get(s):
                        parts.append(f"{s}={counts[s]}")
                print(f"  [{table}] {', '.join(parts)}", file=sys.stderr)
    if not needs_attention:
        return
