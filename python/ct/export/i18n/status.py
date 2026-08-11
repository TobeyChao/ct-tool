from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable

from ct.config import GlobalConfig
from ct.export.i18n.counts import StatusCounts, count_entries
from ct.export.i18n.merger import load_translation
from ct.schema.models import TableSchema


@dataclass
class TableCounts:
    counts: StatusCounts = field(default_factory=StatusCounts)

    @property
    def total(self) -> int:
        return self.counts.total()

    @property
    def translated(self) -> int:
        return self.counts.translated

    @property
    def missing(self) -> int:
        return self.counts.missing

    @property
    def stale(self) -> int:
        return self.counts.stale

    @property
    def orphan(self) -> int:
        return self.counts.orphan

    def progress(self) -> float:
        return self.counts.progress()


@dataclass
class LangCounts:
    counts: StatusCounts = field(default_factory=StatusCounts)
    tables: dict[str, TableCounts] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return self.counts.total()

    @property
    def translated(self) -> int:
        return self.counts.translated

    @property
    def missing(self) -> int:
        return self.counts.missing

    @property
    def stale(self) -> int:
        return self.counts.stale

    @property
    def orphan(self) -> int:
        return self.counts.orphan

    def progress(self) -> float:
        return self.counts.progress()


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
            tc = TableCounts(counts=count_entries(entries))
            lc.tables[schema.table] = tc
            lc.counts = lc.counts + tc.counts
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
