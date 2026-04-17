from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable

from ct.config import GlobalConfig
from ct.export.i18n.merger import load_translation
from ct.schema.models import TableSchema


@dataclass
class TableCounts:
    total: int = 0
    translated: int = 0
    missing: int = 0
    stale: int = 0
    orphan: int = 0

    def progress(self) -> float:
        active = self.total - self.orphan
        if active <= 0:
            return 1.0
        return self.translated / active


@dataclass
class LangCounts:
    total: int = 0
    translated: int = 0
    missing: int = 0
    stale: int = 0
    orphan: int = 0
    tables: dict[str, TableCounts] = field(default_factory=dict)

    def progress(self) -> float:
        active = self.total - self.orphan
        if active <= 0:
            return 1.0
        return self.translated / active


@dataclass
class StatusReport:
    langs: dict[str, LangCounts] = field(default_factory=dict)


def compute_status_report(
    cfg: GlobalConfig,
    schemas: Iterable[TableSchema],
    *,
    lang_filter: str | None = None,
) -> StatusReport:
    """读取所有 lang 文件，按语言/表聚合状态计数。"""
    i18n_dir = cfg.resolve("i18n_dir")
    i18n_schemas = [s for s in schemas if s.has_i18n]
    langs = cfg.secondary_langs
    if lang_filter:
        langs = [lang_filter] if lang_filter in langs else []

    report = StatusReport()
    for lang in langs:
        lc = LangCounts()
        for schema in i18n_schemas:
            entries = load_translation(i18n_dir, lang, schema.table)
            tc = TableCounts()
            for entry in entries.values():
                tc.total += 1
                status = entry.get("status", "")
                if status == "translated":
                    tc.translated += 1
                elif status == "missing":
                    tc.missing += 1
                elif status == "stale":
                    tc.stale += 1
                elif status == "orphan":
                    tc.orphan += 1
            lc.tables[schema.table] = tc
            lc.total += tc.total
            lc.translated += tc.translated
            lc.missing += tc.missing
            lc.stale += tc.stale
            lc.orphan += tc.orphan
        report.langs[lang] = lc
    return report


def _bar(progress: float, width: int = 10) -> str:
    filled = round(progress * width)
    filled = max(0, min(width, filled))
    return "[" + "#" * filled + "." * (width - filled) + "]"


def render_default(report: StatusReport) -> str:
    if not report.langs:
        return "(no secondary languages configured)\n"
    lines = []
    for lang, lc in report.langs.items():
        pct = round(lc.progress() * 100)
        lines.append(
            f"[{lang}]  {pct:3d}% {_bar(lc.progress())} "
            f"{lc.translated}/{lc.total} translated, "
            f"{lc.missing} missing, {lc.stale} stale, {lc.orphan} orphan"
        )
    return "\n".join(lines) + "\n"


def render_by_table(report: StatusReport) -> str:
    if not report.langs:
        return "(no secondary languages configured)\n"
    lines = []
    for lang, lc in report.langs.items():
        lines.append(f"[{lang}]")
        for table, tc in lc.tables.items():
            pct = round(tc.progress() * 100)
            lines.append(
                f"  {table:20s} {pct:3d}% {_bar(tc.progress())} "
                f"{tc.translated}/{tc.total} translated, "
                f"{tc.missing} missing, {tc.stale} stale, {tc.orphan} orphan"
            )
    return "\n".join(lines) + "\n"


def render_json(report: StatusReport) -> str:
    out = {"langs": {}}
    for lang, lc in report.langs.items():
        out["langs"][lang] = {
            "total": lc.total,
            "translated": lc.translated,
            "missing": lc.missing,
            "stale": lc.stale,
            "orphan": lc.orphan,
            "progress": round(lc.progress(), 4),
            "tables": {
                table: {
                    "total": tc.total,
                    "translated": tc.translated,
                    "missing": tc.missing,
                    "stale": tc.stale,
                    "orphan": tc.orphan,
                    "progress": round(tc.progress(), 4),
                }
                for table, tc in lc.tables.items()
            },
        }
    return json.dumps(out, ensure_ascii=False, indent=2) + "\n"
