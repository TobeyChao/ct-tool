"""Canonical CLI command implementations (validate/status/gen-template).

Used when a workspace is canonical; legacy workspaces keep the legacy path.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ct.app.canonical_workspace import CanonicalWorkspace
from ct.diagnostics.errors import Issue, IssueCode, ValidationIssue
from ct.excel.canonical_reader import read_canonical_excel
from ct.excel.canonical_template import generate_canonical_template
from ct.excel.layout import build_layout
from ct.excel.layout_manifest import LayoutManifest, save_manifest
from ct.schema.hashing import compute_schema_hash
from ct.schema.resources import RecordResource


def _records_map(ws: CanonicalWorkspace) -> dict[str, RecordResource]:
    return {r.name: r for r in ws.records}


def canonical_validate(
    root: Path,
    *,
    table_filter: str | None = None,
) -> list[Issue]:
    """Read + validate a canonical workspace; returns structured issues."""
    ws = CanonicalWorkspace.load(root)
    records = _records_map(ws)
    excel_dir = ws.resolve("excel_dir")
    issues: list[Issue] = []
    tables = [t for t in ws.tables if table_filter is None or t.table == table_filter]
    if table_filter is not None and not tables:
        issues.append(WorkspaceIssue("", IssueCode.WORKSPACE, f"表 '{table_filter}' 不存在"))
        return issues
    seen_primary: dict[str, set] = {}
    for table in tables:
        excel_path = excel_dir / (table.excel_file or f"{table.table}.xlsx")
        if not excel_path.exists():
            issues.append(
                WorkspaceIssue(table.table, IssueCode.WORKSPACE, f"Excel 文件不存在: {excel_path}")
            )
            continue
        layout = build_layout(
            table,
            schema_hash=compute_schema_hash(table, tuple(records.values())),
            records=records,
        )
        parsed = read_canonical_excel(excel_path, layout, table, records=records)
        issues.extend(parsed.issues)
        seen_primary[table.table] = set()
        for index, row in enumerate(parsed.rows, start=1):
            pk = row.get(table.primary)
            if pk is None:
                issues.append(
                    ValidationIssue(
                        table.table,
                        IssueCode.TYPE,
                        "主键为空",
                        row_index=index,
                        excel_row=parsed.excel_rows[index - 1] if index - 1 < len(parsed.excel_rows) else None,
                        field=table.primary,
                    )
                )
            elif pk in seen_primary[table.table]:
                issues.append(
                    ValidationIssue(
                        table.table,
                        IssueCode.DUPLICATE_PK,
                        f"主键重复: {pk!r}",
                        row_index=index,
                        excel_row=parsed.excel_rows[index - 1] if index - 1 < len(parsed.excel_rows) else None,
                        field=table.primary,
                        value=pk,
                    )
                )
            else:
                seen_primary[table.table].add(pk)
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


def canonical_i18n_status(root: Path) -> dict[str, dict[str, int]]:
    """Per-language translation counts for a canonical workspace."""
    from ct.export.i18n.state import compute_status

    ws = CanonicalWorkspace.load(root)
    config = ws.config
    i18n_dir = config.resolve("i18n_dir")
    tables = [t.table for t in ws.tables if any(f.i18n for f in t.fields)]
    result: dict[str, dict[str, int]] = {}
    for lang in config.secondary_langs:
        lang_dir = i18n_dir / lang
        counts = {"translated": 0, "missing": 0, "stale": 0, "orphan": 0, "total": 0}
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
        result[lang] = counts
    return result


def _write_compact_json(path: Path, data) -> None:
    import json as _json

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        _json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def canonical_i18n_sync(root: Path, *, table_filter: str | None = None) -> list[str]:
    """Refresh source files and lang skeletons for a canonical workspace."""
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
        _write_compact_json(i18n_dir / "source" / f"{table.table}.json", source)
        for lang in config.secondary_langs:
            lang_path = i18n_dir / lang / f"{table.table}.json"
            existing = (
                json.loads(lang_path.read_text(encoding="utf-8"))
                if lang_path.exists()
                else {}
            )
            _write_compact_json(lang_path, sync_lang_table(source, existing))
        messages.append(f"synced {table.table}")
    return messages


def canonical_i18n_compact(root: Path, *, table_filter: str | None = None) -> int:
    """Physically remove orphan entries from lang files."""
    ws = CanonicalWorkspace.load(root)
    config = ws.config
    i18n_dir = config.resolve("i18n_dir")
    removed = 0
    for table in ws.tables:
        if table_filter is not None and table.table != table_filter:
            continue
        source_path = i18n_dir / "source" / f"{table.table}.json"
        if not source_path.exists():
            continue
        source = set(json.loads(source_path.read_text(encoding="utf-8")).keys())
        for lang in config.secondary_langs:
            lang_path = i18n_dir / lang / f"{table.table}.json"
            if not lang_path.exists():
                continue
            entries = json.loads(lang_path.read_text(encoding="utf-8"))
            orphans = {k for k in entries if k not in source}
            if orphans:
                removed += len(orphans)
                for key in orphans:
                    entries.pop(key, None)
                _write_compact_json(lang_path, entries)
    return removed
