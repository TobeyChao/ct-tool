"""Canonical CLI command implementations (validate/status/gen-template/i18n).

These back the canonical-only CLI and Web; the legacy (pre) path is removed.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ct.app.canonical_workspace import CanonicalWorkspace
from ct.diagnostics.errors import Issue, IssueCode, ValidationIssue, WorkspaceIssue
from ct.excel.canonical_reader import read_canonical_excel
from ct.excel.canonical_template import generate_canonical_template
from ct.excel.layout import build_layout
from ct.excel.layout_manifest import LayoutManifest, save_manifest
from ct.schema.hashing import compute_schema_hash
from ct.schema.resources import RecordResource


def _records_map(ws: CanonicalWorkspace) -> dict[str, RecordResource]:
    return {r.name: r for r in ws.records}


class CanonicalValidationError(ValueError):
    """Canonical 校验失败：携带结构化 issues，供 CLI / Web 渲染。"""

    def __init__(self, issues: list[Issue]) -> None:
        super().__init__(f"校验发现 {len(issues)} 个问题")
        self.issues = issues


def _primary_issues(
    table, parsed, seen: set
) -> list[Issue]:
    """主键为空 / 重复校验，填充 seen（该表主键集合）。"""
    issues: list[Issue] = []
    for index, row in enumerate(parsed.rows, start=1):
        pk = row.get(table.primary)
        excel_row = (
            parsed.excel_rows[index - 1] if index - 1 < len(parsed.excel_rows) else None
        )
        if pk is None:
            issues.append(
                ValidationIssue(
                    table.table,
                    IssueCode.TYPE,
                    "主键为空",
                    row_index=index,
                    excel_row=excel_row,
                    field=table.primary,
                )
            )
        elif pk in seen:
            issues.append(
                ValidationIssue(
                    table.table,
                    IssueCode.DUPLICATE_PK,
                    f"主键重复: {pk!r}",
                    row_index=index,
                    excel_row=excel_row,
                    field=table.primary,
                    value=pk,
                )
            )
        else:
            seen.add(pk)
    return issues


def _ref_issues(
    table, parsed, id_sets: dict[str, set]
) -> list[Issue]:
    """跨表 ref 外键值校验：field.ref 的值必须存在于引用表主键集。"""
    ref_fields = [field for field in table.fields if field.ref]
    if not ref_fields:
        return []
    issues: list[Issue] = []
    for row_index, row in enumerate(parsed.rows, start=1):
        excel_row = (
            parsed.excel_rows[row_index - 1] if row_index - 1 < len(parsed.excel_rows) else None
        )
        for field in ref_fields:
            target_table = field.ref.partition(".")[0]
            target_field = field.ref.partition(".")[2] or "id"
            value = row.get(field.name)
            values = value if isinstance(value, list) else [value]
            target_ids = id_sets.get(target_table)
            if target_ids is None:
                issues.append(
                    ValidationIssue(
                        table.table,
                        IssueCode.REF,
                        f"引用表 {target_table} 的数据未加载，无法校验",
                        row_index=row_index,
                        excel_row=excel_row,
                        field=field.name,
                        value=value,
                    )
                )
                continue
            for v in values:
                if v is None:
                    continue
                if v not in target_ids:
                    issues.append(
                        ValidationIssue(
                            table.table,
                            IssueCode.REF,
                            f"值 {v!r} 在引用表 {target_table}.{target_field} 中不存在",
                            row_index=row_index,
                            excel_row=excel_row,
                            field=field.name,
                            value=v,
                        )
                    )
    return issues


def canonical_validate(
    root: Path,
    *,
    table_filter: str | None = None,
) -> list[Issue]:
    """Read + validate a canonical workspace; returns structured issues.

    Full validation: Excel read (type coercion), primary empty/duplicate and
    cross-table ``ref`` foreign-key values (must exist in the target table's
    primary-key set). The legacy path no longer exists.
    """
    ws = CanonicalWorkspace.load(root)
    records = _records_map(ws)
    excel_dir = ws.resolve("excel_dir")
    issues: list[Issue] = []
    tables = [t for t in ws.tables if table_filter is None or t.table == table_filter]
    if table_filter is not None and not tables:
        issues.append(
            WorkspaceIssue("", IssueCode.WORKSPACE, f"表 '{table_filter}' 不存在")
        )
        return issues

    parsed_by_table: dict[str, object] = {}
    id_sets: dict[str, set] = {}
    for table in tables:
        excel_path = excel_dir / (table.excel_file or f"{table.table}.xlsx")
        if not excel_path.exists():
            issues.append(
                WorkspaceIssue(
                    table.table, IssueCode.WORKSPACE, f"Excel 文件不存在: {excel_path}"
                )
            )
            continue
        layout = build_layout(
            table,
            schema_hash=compute_schema_hash(table, tuple(records.values())),
            records=records,
        )
        parsed = read_canonical_excel(excel_path, layout, table, records=records)
        issues.extend(parsed.issues)
        seen: set = set()
        issues.extend(_primary_issues(table, parsed, seen))
        parsed_by_table[table.table] = parsed
        id_sets[table.table] = seen

    for table in tables:
        parsed = parsed_by_table.get(table.table)
        if parsed is not None:
            issues.extend(_ref_issues(table, parsed, id_sets))
    return issues


def _file_sha256(path: Path) -> str:
    if not path.exists():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_status(root: Path) -> dict[str, list[str]]:
    """Per-table data-change + template-drift status for a canonical workspace."""
    ws = CanonicalWorkspace.load(root)
    records = _records_map(ws)
    excel_dir = ws.resolve("excel_dir")
    cache_dir = ws.resolve("cache_dir")
    changed: list[str] = []
    drifted: list[str] = []
    missing: list[str] = []
    for table in ws.tables:
        excel_path = excel_dir / (table.excel_file or f"{table.table}.xlsx")
        if not excel_path.exists():
            missing.append(table.table)
            continue
        current_hash = _file_sha256(excel_path)
        manifest = _load_manifest(cache_dir, table.table)
        if manifest is None or manifest.schema_hash != _schema_hash(table, records):
            drifted.append(table.table)
        if manifest is None or manifest.schema_hash != _schema_hash(table, records) or _file_sha256(
            cache_dir / "template_layouts" / f"{table.table}.json"
        ) == "":
            changed.append(table.table)
    return {"changed": sorted(set(changed)), "drifted": sorted(set(drifted)), "missing": sorted(missing)}


def _load_manifest(cache_dir: Path, table: str) -> LayoutManifest | None:
    from ct.excel.layout_manifest import load_manifest

    return load_manifest(cache_dir, table)


def _schema_hash(table, records) -> str:
    return compute_schema_hash(table, tuple(records.values()))


def canonical_gen_template(
    root: Path,
    *,
    table_filter: str | None = None,
    all_tables: bool = False,
) -> list[str]:
    """Generate canonical Excel templates + layout manifests."""
    ws = CanonicalWorkspace.load(root)
    records = _records_map(ws)
    excel_dir = ws.resolve("excel_dir")
    excel_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = ws.resolve("cache_dir")
    targets = [t for t in ws.tables if table_filter is None or table_filter == t.table]
    if table_filter is None and not all_tables:
        raise ValueError("请指定 --all 或 --table <表名>")
    messages: list[str] = []
    for table in targets:
        layout = build_layout(
            table,
            schema_hash=compute_schema_hash(table, tuple(records.values())),
            records=records,
        )
        out_path = excel_dir / (table.excel_file or f"{table.table}.xlsx")
        generate_canonical_template(
            layout, out_path, enums={e.name: e for e in ws.enums}, primary=table.primary
        )
        save_manifest(cache_dir, table.table, LayoutManifest.from_layout(layout))
        messages.append(f"模板已生成: {table.table}")
    return messages


def _i18n_progress(counts: dict[str, int]) -> float:
    """进度 = translated / (total - orphan)，无活跃条目视为 100%。"""
    active = counts["total"] - counts["orphan"]
    if active <= 0:
        return 1.0
    return round(counts["translated"] / active, 4)


def canonical_i18n_status(root: Path) -> dict[str, dict]:
    """Per-language + per-table translation counts for a canonical workspace."""
    from ct.export.i18n.state import compute_status

    ws = CanonicalWorkspace.load(root)
    config = ws.config
    i18n_dir = config.resolve("i18n_dir")
    i18n_tables = [t for t in ws.tables if any(f.i18n for f in t.fields)]
    tables = [t.table for t in i18n_tables]
    result: dict[str, dict] = {}
    for lang in config.secondary_langs:
        lang_dir = i18n_dir / lang
        lang_counts = {"translated": 0, "missing": 0, "stale": 0, "orphan": 0, "total": 0}
        table_detail: dict[str, dict] = {}
        for table in tables:
            source_path = i18n_dir / "source" / f"{table}.json"
            if not source_path.exists():
                continue
            source = json.loads(source_path.read_text(encoding="utf-8"))
            lang_path = lang_dir / f"{table}.json"
            entries = (
                json.loads(lang_path.read_text(encoding="utf-8"))
                if lang_path.exists()
                else {}
            )
            counts = {"translated": 0, "missing": 0, "stale": 0, "orphan": 0, "total": 0}
            for key, source_text in source.items():
                entry = entries.get(key) or {}
                text = str(entry.get("text", ""))
                confirmed = bool(entry.get("confirmed", False))
                status = compute_status(text, confirmed, in_source=True).value
                counts[status if status in counts else "missing"] += 1
                counts["total"] += 1
            for key, entry in entries.items():
                if key not in source:
                    counts["orphan"] += 1
                    counts["total"] += 1
            table_detail[table] = {**counts, "progress": _i18n_progress(counts)}
            for stat in ("translated", "missing", "stale", "orphan", "total"):
                lang_counts[stat] += counts[stat]
        result[lang] = {
            **lang_counts,
            "progress": _i18n_progress(lang_counts),
            "tables": table_detail,
        }
    return result


def canonical_i18n_sync(root: Path, *, table_filter: str | None = None) -> list[str]:
    """Refresh source files and lang skeletons for a canonical workspace."""
    from ct.export.i18n.merger import write_lang_file, write_source_file
    from ct.export.i18n.state import sync_lang_table

    ws = CanonicalWorkspace.load(root)
    records = _records_map(ws)
    config = ws.config
    excel_dir = config.resolve("excel_dir")
    i18n_dir = config.resolve("i18n_dir")
    tables = [
        t for t in ws.tables
        if (table_filter is None or t.table == table_filter) and any(f.i18n for f in t.fields)
    ]
    messages: list[str] = []
    for table in tables:
        i18n_fields = [f for f in table.fields if f.i18n]
        field_order = [f.name for f in i18n_fields]
        excel_path = excel_dir / (table.excel_file or f"{table.table}.xlsx")
        if not excel_path.exists():
            continue
        layout = build_layout(
            table,
            schema_hash=compute_schema_hash(table, tuple(records.values())),
            records=records,
        )
        parsed = read_canonical_excel(excel_path, layout, table, records=records)
        source: dict[str, str] = {}
        for row in parsed.rows:
            row_id = row.get(table.primary)
            for field in i18n_fields:
                source[f"{row_id}.{field.name}"] = str(row.get(field.name, ""))
        write_source_file(source, i18n_dir / "source" / f"{table.table}.json", field_order)
        for lang in config.secondary_langs:
            lang_path = i18n_dir / lang / f"{table.table}.json"
            existing = (
                json.loads(lang_path.read_text(encoding="utf-8"))
                if lang_path.exists()
                else {}
            )
            write_lang_file(sync_lang_table(source, existing), lang_path, field_order)
        messages.append(f"synced {table.table}")
    return messages


def canonical_i18n_compact(
    root: Path,
    *,
    table_filter: str | None = None,
    dry_run: bool = False,
) -> dict:
    """Remove orphan entries from lang files.

    dry_run=True 时不落盘，返回即将删除的 files 明细供预览。
    """
    from ct.export.i18n.merger import write_lang_file

    ws = CanonicalWorkspace.load(root)
    config = ws.config
    i18n_dir = config.resolve("i18n_dir")
    removed = 0
    touched = 0
    files: list[dict] = []
    for table in ws.tables:
        if table_filter is not None and table.table != table_filter:
            continue
        if not any(f.i18n for f in table.fields):
            continue
        field_order = [f.name for f in table.fields if f.i18n]
        source_path = i18n_dir / "source" / f"{table.table}.json"
        if not source_path.exists():
            continue
        source = set(json.loads(source_path.read_text(encoding="utf-8")).keys())
        for lang in config.secondary_langs:
            lang_path = i18n_dir / lang / f"{table.table}.json"
            if not lang_path.exists():
                continue
            entries = json.loads(lang_path.read_text(encoding="utf-8"))
            orphans = sorted(k for k in entries if k not in source)
            if not orphans:
                continue
            removed += len(orphans)
            touched += 1
            files.append(
                {"lang": lang, "table": table.table, "removed_keys": orphans}
            )
            if dry_run:
                continue
            for key in orphans:
                entries.pop(key, None)
            write_lang_file(entries, lang_path, field_order)
    return {
        "dry_run": dry_run,
        "touched": touched,
        "total_removed": removed,
        "files": files,
    }


def canonical_i18n_tables(root: Path) -> list[dict]:
    """List all tables with their i18n field metadata (for the picker)."""
    ws = CanonicalWorkspace.load(root)
    return [
        {
            "table": t.table,
            "field_count": len(t.fields),
            "i18n_count": len(t.i18n_fields),
            "has_i18n": t.has_i18n,
        }
        for t in ws.tables
    ]


def _i18n_table(ws: CanonicalWorkspace, table: str) -> object:
    """Find an i18n-capable table by name, raising a friendly error otherwise."""
    t = next((t for t in ws.tables if t.table == table), None)
    if t is None:
        raise ValueError(f"表 '{table}' 不存在")
    if not t.has_i18n:
        raise ValueError(f"表 '{table}' 没有 i18n 字段")
    return t


def canonical_i18n_entries(root: Path, table: str, lang: str) -> list[dict]:
    """Return computed translation entries for a table+lang (source + text + status)."""
    from ct.export.i18n.merger import load_translation
    from ct.export.i18n.state import sync_lang_table

    ws = CanonicalWorkspace.load(root)
    config = ws.config
    target = _i18n_table(ws, table)
    if lang not in config.secondary_langs:
        raise ValueError(f"语言 '{lang}' 不在 secondary_langs 中")
    i18n_dir = config.resolve("i18n_dir")
    source_path = i18n_dir / "source" / f"{table}.json"
    source = (
        json.loads(source_path.read_text(encoding="utf-8"))
        if source_path.exists()
        else {}
    )
    computed = sync_lang_table(source, load_translation(i18n_dir, lang, table))
    entries: list[dict] = []
    for key, entry in computed.items():
        id_part, _, field = key.partition(".")
        entries.append(
            {
                "key": key,
                "id": id_part,
                "field": field,
                "source": str(entry.get("source", "")),
                "text": str(entry.get("text", "")),
                "confirmed": bool(entry.get("confirmed", False)),
                "status": str(entry.get("status", "missing")),
            }
        )
    return entries


def canonical_i18n_save_entry(
    root: Path,
    table: str,
    lang: str,
    key: str,
    text: str,
    confirmed: bool,
) -> dict:
    """Save a single translation entry, recompute its status, and re-dump the lang file."""
    from ct.export.i18n.merger import load_translation, write_lang_file
    from ct.export.i18n.state import compute_status

    ws = CanonicalWorkspace.load(root)
    config = ws.config
    target = _i18n_table(ws, table)
    if lang not in config.secondary_langs:
        raise ValueError(f"语言 '{lang}' 不在 secondary_langs 中")
    i18n_dir = config.resolve("i18n_dir")
    entries = load_translation(i18n_dir, lang, table)
    if key not in entries:
        raise ValueError(f"条目 {key} 不存在，请先同步骨架")
    entries[key]["text"] = str(text)
    entries[key]["confirmed"] = bool(confirmed)
    entries[key]["status"] = compute_status(
        entries[key]["text"], entries[key]["confirmed"], in_source=True
    ).value
    field_order = [f.name for f in target.i18n_fields]
    write_lang_file(entries, i18n_dir / lang / f"{table}.json", field_order)
    return entries[key]
