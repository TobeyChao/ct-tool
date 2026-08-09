from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from ct.export.i18n.counts import StatusCounts, count_entries
from ct.export.i18n.io import dump_lang_file
from ct.config import GlobalConfig
from ct.export.i18n.extractor import (
    extract_source_for_table,
    save_source_file,
)
from ct.export.i18n.merger import load_translation
from ct.export.i18n.state import sync_lang_table
from ct.schema.models import TableSchema
from ct.validate.errors import ValidationIssue


@dataclass
class TableSyncStats:
    counts: StatusCounts = field(default_factory=StatusCounts)
    created: int = 0
    updated: int = 0

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


@dataclass
class SyncSummary:
    per_lang_table: dict[tuple[str, str], TableSyncStats] = field(default_factory=dict)
    elapsed: float = 0.0
    source_files_written: list[Path] = field(default_factory=list)
    lang_files_written: list[Path] = field(default_factory=list)

    def totals_by_lang(self) -> dict[str, StatusCounts]:
        out: dict[str, StatusCounts] = {}
        for (lang, _), stats in self.per_lang_table.items():
            out[lang] = out.get(lang, StatusCounts()) + stats.counts
        return out


def _lang_path(i18n_dir: Path, lang: str, table: str) -> Path:
    return i18n_dir / lang / f"{table}.json"


def sync_all(
    cfg: GlobalConfig,
    schemas: Iterable[TableSchema],
    rows_by_table: dict[str, list[dict[str, Any]]],
    *,
    issues_by_table: dict[str, list[ValidationIssue]] | None = None,
    lang_filter: str | None = None,
    table_filter: str | None = None,
) -> SyncSummary:
    """执行完整 sync：刷新 source，更新每语言每表的 lang 文件。

    - lang_filter 限定 lang 文件处理范围；source 文件始终全量刷新
    - table_filter 同时限定 source 与 lang 文件
    - **不做残留清理**：清理是独立用例 `cleanup_i18n_files`（基于项目
      全量 schema），与本次处理范围解耦——避免按表/增量处理时误删
      其他表的 lang 文件（既有缺陷，功能验证发现）。
    """
    started = time.perf_counter()
    summary = SyncSummary()
    i18n_dir = cfg.resolve("i18n_dir")

    i18n_schemas = [s for s in schemas if s.has_i18n]
    if table_filter:
        i18n_schemas = [s for s in i18n_schemas if s.table == table_filter]

    secondary_langs = cfg.secondary_langs
    if lang_filter:
        if lang_filter not in secondary_langs:
            secondary_langs = []
        else:
            secondary_langs = [lang_filter]

    for schema in i18n_schemas:
        rows = rows_by_table.get(schema.table, [])
        table_issues = (issues_by_table or {}).get(schema.table)
        source_data = extract_source_for_table(
            rows, schema, issues=table_issues
        )
        path = save_source_file(i18n_dir, schema, source_data)
        summary.source_files_written.append(path)

        for lang in secondary_langs:
            lang_existing = load_translation(i18n_dir, lang, schema.table)

            new_lang = sync_lang_table(source_data, lang_existing)
            new_keys = set(new_lang.keys()) - set(lang_existing.keys())
            stats = TableSyncStats(
                counts=count_entries(new_lang),
                created=len(new_keys),
                updated=len(new_lang) - len(new_keys),
            )
            summary.per_lang_table[(lang, schema.table)] = stats

            field_order = [f.name for f in schema.i18n_fields]
            lang_path = _lang_path(i18n_dir, lang, schema.table)
            dump_lang_file(new_lang, lang_path, field_order)
            summary.lang_files_written.append(lang_path)

    summary.elapsed = time.perf_counter() - started
    return summary


def cleanup_i18n_files(
    cfg: GlobalConfig,
    schemas: Iterable[TableSchema],
    *,
    lang_filter: str | None = None,
) -> list[Path]:
    """删除无对应表的 i18n 残留文件（表名变更/删除后的清理）。

    valid 集合基于传入的**全量** schema（调用方应传项目全部 schema，
    而非本次处理子集），保证任何导出/sync 模式都不会误删其他表的
    lang 文件。
    """
    i18n_dir = cfg.resolve("i18n_dir")
    valid_tables = {s.table for s in schemas if s.has_i18n}

    langs = cfg.secondary_langs
    if lang_filter:
        langs = [lang_filter] if lang_filter in langs else []

    cleanup_dirs = [i18n_dir / "source"]
    cleanup_dirs += [i18n_dir / lang for lang in langs]

    removed: list[Path] = []
    for d in cleanup_dirs:
        if not d.exists():
            continue
        for f in d.glob("*.json"):
            if f.stem not in valid_tables:
                f.unlink()
                removed.append(f)
    return removed
