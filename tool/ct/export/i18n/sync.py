from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from ct.export.i18n.io import dump_lang_file
from ct.config import GlobalConfig
from ct.export.i18n.extractor import (
    extract_source_for_table,
    save_source_file,
)
from ct.export.i18n.merger import load_translation
from ct.export.i18n.state import LangStatus, sync_lang_table
from ct.schema.models import TableSchema


@dataclass
class TableSyncStats:
    created: int = 0
    updated: int = 0
    translated: int = 0
    missing: int = 0
    stale: int = 0
    orphan: int = 0


@dataclass
class SyncSummary:
    per_lang_table: dict[tuple[str, str], TableSyncStats] = field(default_factory=dict)
    elapsed: float = 0.0
    source_files_written: list[Path] = field(default_factory=list)
    lang_files_written: list[Path] = field(default_factory=list)

    def totals_by_lang(self) -> dict[str, TableSyncStats]:
        out: dict[str, TableSyncStats] = defaultdict(TableSyncStats)
        for (lang, _), stats in self.per_lang_table.items():
            agg = out[lang]
            agg.created += stats.created
            agg.updated += stats.updated
            agg.translated += stats.translated
            agg.missing += stats.missing
            agg.stale += stats.stale
            agg.orphan += stats.orphan
        return dict(out)


def _lang_path(i18n_dir: Path, lang: str, table: str) -> Path:
    return i18n_dir / lang / f"{table}.json"


def sync_all(
    cfg: GlobalConfig,
    schemas: Iterable[TableSchema],
    rows_by_table: dict[str, list[dict[str, Any]]],
    *,
    lang_filter: str | None = None,
    table_filter: str | None = None,
) -> SyncSummary:
    """执行完整 sync：刷新 source，更新每语言每表的 lang 文件。

    - lang_filter 限定 lang 文件处理范围；source 文件始终全量刷新
    - table_filter 同时限定 source 与 lang 文件
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
        source_data = extract_source_for_table(rows, schema)
        path = save_source_file(i18n_dir, schema, source_data)
        summary.source_files_written.append(path)

        for lang in secondary_langs:
            lang_existing = load_translation(i18n_dir, lang, schema.table)
            existing_count = len(lang_existing)

            new_lang = sync_lang_table(source_data, lang_existing)

            stats = TableSyncStats()
            new_keys = set(new_lang.keys()) - set(lang_existing.keys())
            stats.created = len(new_keys)
            stats.updated = len(new_lang) - stats.created
            for entry in new_lang.values():
                status = entry["status"]
                if status == LangStatus.TRANSLATED.value:
                    stats.translated += 1
                elif status == LangStatus.MISSING.value:
                    stats.missing += 1
                elif status == LangStatus.STALE.value:
                    stats.stale += 1
                elif status == LangStatus.ORPHAN.value:
                    stats.orphan += 1
            summary.per_lang_table[(lang, schema.table)] = stats

            field_order = [f.name for f in schema.i18n_fields]
            lang_path = _lang_path(i18n_dir, lang, schema.table)
            dump_lang_file(new_lang, lang_path, field_order)
            summary.lang_files_written.append(lang_path)

    # 清理：删除无对应表的 i18n 文件（表名变更/删除后的残留）。
    # 仅在非 table_filter 时执行（局部操作不做全局清理）。
    if not table_filter:
        valid_tables = {s.table for s in i18n_schemas}
        cleanup_dirs = [i18n_dir / "source"]
        cleanup_dirs += [i18n_dir / lang for lang in secondary_langs]
        for d in cleanup_dirs:
            if not d.exists():
                continue
            for f in d.glob("*.json"):
                if f.stem not in valid_tables:
                    f.unlink()

    summary.elapsed = time.perf_counter() - started
    return summary
