"""`ct i18n compact` 用例：物理移除 orphan 条目（拆分阶段 6.11）。

文件操作自 cli.i18n_compact 搬移，返回 summary；CLI 只渲染。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ct.config import GlobalConfig
from ct.export.i18n.io import dump_lang_file
from ct.export.i18n.merger import load_translation
from ct.schema.models import TableSchema


class CompactError(ValueError):
    """compact 参数非法（如 lang 不在 secondary_langs）。"""


@dataclass(frozen=True)
class CompactFileResult:
    """一个 lang 文件的清理结果。dry_run 时 removed_keys 为"将移除"的 key。"""

    lang: str
    table: str
    removed_keys: list[str]


@dataclass
class CompactSummary:
    dry_run: bool
    touched: bool = False
    total_removed: int = 0
    files: list[CompactFileResult] = field(default_factory=list)


def compact_i18n(
    cfg: GlobalConfig,
    schemas: list[TableSchema],
    *,
    lang: str | None = None,
    table: str | None = None,
    dry_run: bool = False,
) -> CompactSummary:
    """物理移除所有 lang 文件中 status=orphan 的条目。

    - lang 不在 secondary_langs 时抛 CompactError（消息即现 CLI 文案）；
    - files 只含有 orphan 条目的文件（无 orphan 的文件不产生条目）；
    - dry_run 只收集 removed_keys，不写盘。
    """
    i18n_dir = cfg.resolve("i18n_dir")
    langs = cfg.secondary_langs
    if lang:
        if lang not in langs:
            raise CompactError(f"语言 '{lang}' 不在 secondary_langs 中")
        langs = [lang]

    target_schemas = [s for s in schemas if s.has_i18n]
    if table:
        target_schemas = [s for s in target_schemas if s.table == table]

    summary = CompactSummary(dry_run=dry_run)
    for l in langs:
        for schema in target_schemas:
            entries = load_translation(i18n_dir, l, schema.table)
            orphan_keys = [
                k for k, v in entries.items() if v.get("status") == "orphan"
            ]
            if not orphan_keys:
                continue

            summary.touched = True
            summary.files.append(CompactFileResult(l, schema.table, orphan_keys))
            if dry_run:
                continue

            for k in orphan_keys:
                del entries[k]
            field_order = [f.name for f in schema.i18n_fields]
            dump_lang_file(entries, i18n_dir / l / f"{schema.table}.json", field_order)
            summary.total_removed += len(orphan_keys)
    return summary
