"""Canonical  export pipeline.

Reads Excel through the canonical layout/reader, merges i18n translations,
then writes JSON, shared ``types.fbs`` + per-table FBS, a real FlatBuffers
``DataBundle`` per language, C#/Lua accessors and layout manifests. The legacy
(pre) pipeline has been removed; ``ct export`` always runs this pipeline.

Progress reporting is phase-based (``CANONICAL_STEPS``): each phase covers
the full table set so the step index only moves forward, which keeps the
web progress cells stable during an export. ``forced`` is accepted and
recorded for parity with the legacy pipeline; the current  pipeline
always rebuilds every artifact (incremental reuse via the layered
fingerprints is not wired up yet).
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from ct.app.canonical_commands import (
    CanonicalValidationError,
    _primary_issues,
    _ref_issues,
)
from ct.app.canonical_workspace import CanonicalWorkspace
from ct.app.events import CancelledError, CancelToken, ProgressReporter
from ct.cache.fingerprints import bundle_fingerprint
from ct.excel.canonical_reader import read_canonical_excel
from ct.excel.canonical_template import generate_canonical_template
from ct.excel.layout import Layout, build_layout
from ct.excel.layout_manifest import LayoutManifest, save_manifest
from ct.export.canonical_accessor import (
    generate_csharp_accessor,
    generate_lua_accessor,
)
from ct.export.canonical_accessor_model import build_accessor_model
from ct.export.canonical_binary import (
    build_canonical_bundle,
    build_canonical_table_bytes,
)
from ct.export.canonical_fbs import (
    table_fbs_text,
    types_fbs_text,
    validate_canonical_fbs,
)
from ct.export.canonical_json import write_canonical_json
from ct.export.i18n.merger import load_translation
from ct.schema.hashing import compute_schema_hash
from ct.schema.resources import (
    EnumResource,
    RecordResource,
    SchemaResource,
    TableResource,
)

CODEGEN_VERSION = "1.0"

CANONICAL_STEPS = ("解析校验", "JSON", "Accessor", "FBS", "Bundle")


class _NullReporter:
    """No-op progress reporter for CLI/synchronous callers."""

    def step_started(self, step: str) -> None:
        pass

    def step_finished(self, step: str) -> None:
        pass

    def log(self, line: str, *, err: bool = False) -> None:
        pass


def _records_map(workspace: CanonicalWorkspace) -> dict[str, RecordResource]:
    return {record.name: record for record in workspace.records}


def _enums_map(workspace: CanonicalWorkspace) -> dict[str, EnumResource]:
    return {enum.name: enum for enum in workspace.enums}


def _merge_i18n(
    rows: list[dict[str, Any]],
    table: TableResource,
    translations: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Replace confirmed translated strings for i18n top-level fields."""
    i18n_fields = [field for field in table.fields if field.i18n]
    if not i18n_fields:
        return rows
    merged: list[dict[str, Any]] = []
    for row in rows:
        new_row = dict(row)
        row_id = row.get(table.primary)
        for field in i18n_fields:
            key = f"{row_id}.{field.name}"
            entry = translations.get(key)
            if entry and entry.get("text") and entry.get("confirmed"):
                new_row[field.name] = entry["text"]
        merged.append(new_row)
    return merged


def _check_cancel(token: CancelToken | None) -> None:
    if token is not None:
        token.raise_if_cancelled()


def run_canonical_export(
    root: Path,
    *,
    table_filter: str | None = None,
    lang_filter: str | None = None,
    forced: bool = False,
    reporter: ProgressReporter | None = None,
    cancel_token: CancelToken | None = None,
) -> dict[str, Any]:
    """Run the canonical  export for a canonical workspace.

    ``reporter`` receives phase events (``step_started`` / ``step_finished``);
    ``cancel_token`` is checked between tables/phases and raises
    ``CancelledError`` when cancelled.
    """
    started = time.perf_counter()
    reporter = reporter or _NullReporter()
    workspace = CanonicalWorkspace.load(root)
    config = workspace.config
    records = _records_map(workspace)
    enums = _enums_map(workspace)

    tables = [
        table
        for table in workspace.tables
        if table_filter is None or table.table == table_filter
    ]
    if not tables:
        raise ValueError(f"表 '{table_filter}' 不存在")

    output_dir = config.resolve("output_dir")
    excel_dir = config.resolve("excel_dir")
    i18n_dir = config.resolve("i18n_dir")
    cache_dir = config.resolve("cache_dir")
    generated = output_dir / "generated"
    languages = [lang for lang in config.all_langs if lang_filter is None or lang == lang_filter]

    written: list[str] = []
    table_bytes: dict[str, dict[str, bytes]] = {}
    bundle_hashes: dict[str, str] = {}

    # ---- 阶段 1：解析校验（所有表） ----
    reporter.step_started(CANONICAL_STEPS[0])
    try:
        prepared: list[tuple[TableResource, Layout, Path, Any]] = []
        parsed_by_table: dict[str, Any] = {}
        id_sets: dict[str, set] = {}
        validation_issues: list[Any] = []
        for table in tables:
            _check_cancel(cancel_token)
            layout = build_layout(
                table,
                schema_hash=compute_schema_hash(table, tuple(records.values())),
                records=records,
            )
            excel_path = excel_dir / (table.excel_file or f"{table.table}.xlsx")
            parsed = read_canonical_excel(excel_path, layout, table, records=records)
            validation_issues.extend(parsed.issues)
            seen: set = set()
            validation_issues.extend(_primary_issues(table, parsed, seen))
            prepared.append((table, layout, excel_path, parsed))
            parsed_by_table[table.table] = parsed
            id_sets[table.table] = seen
            reporter.log(f"解析 {table.table}（{len(parsed.rows)} 行）")
        # 跨表 ref 外键值校验（需要全部表的主键集）
        for table, _layout, _excel_path, parsed in prepared:
            validation_issues.extend(_ref_issues(table, parsed, id_sets))
        if validation_issues:
            raise CanonicalValidationError(validation_issues)
    finally:
        reporter.step_finished(CANONICAL_STEPS[0])

    # ---- 阶段 2：JSON + 各语言 bytes ----
    types_path = output_dir / "fbs" / "types.fbs"
    types_path.parent.mkdir(parents=True, exist_ok=True)
    reporter.step_started(CANONICAL_STEPS[1])
    try:
        for table, _layout, _excel_path, parsed in prepared:
            _check_cancel(cancel_token)
            base_rows = parsed.rows
            table_bytes[table.table] = {}
            for lang in languages:
                rows = base_rows if lang == config.primary_lang else _merge_i18n(
                    base_rows, table, load_translation(i18n_dir, lang, table.table)
                )
                lang_json = output_dir / "json" / f"{table.table}_{lang}.json"
                write_canonical_json(rows, table, lang_json)
                written.append(str(lang_json))
                table_bytes[table.table][lang] = build_canonical_table_bytes(
                    rows, table, records=records, enums=enums
                )
    finally:
        reporter.step_finished(CANONICAL_STEPS[1])

    # ---- 阶段 3：Accessor + 模板/manifest ----
    reporter.step_started(CANONICAL_STEPS[2])
    try:
        for table, layout, excel_path, _parsed in prepared:
            _check_cancel(cancel_token)
            model = build_accessor_model(table, ())
            csharp_path = generated / "csharp" / f"{table.table}Accessor.cs"
            lua_path = generated / "lua" / f"{table.table}Accessor.lua"
            csharp_path.parent.mkdir(parents=True, exist_ok=True)
            lua_path.parent.mkdir(parents=True, exist_ok=True)
            csharp_path.write_text(generate_csharp_accessor(model), encoding="utf-8")
            lua_path.write_text(generate_lua_accessor(model), encoding="utf-8")
            written.append(str(csharp_path))

            if not excel_path.exists():
                generate_canonical_template(
                    layout, excel_path, enums=enums, primary=table.primary
                )
                written.append(str(excel_path))
            save_manifest(cache_dir, table.table, LayoutManifest.from_layout(layout))
    finally:
        reporter.step_finished(CANONICAL_STEPS[2])

    # ---- 阶段 4：共享 types.fbs + 各表 FBS + container ----
    reporter.step_started(CANONICAL_STEPS[3])
    try:
        order = [
            resource.resource_id
            for resource in sorted(workspace.resources.resources, key=lambda r: r.resource_id)
        ]
        resources_map: dict[str, SchemaResource] = {
            resource.resource_id: resource for resource in workspace.resources.resources
        }
        types_text = types_fbs_text(order, resources_map)
        types_path.write_text(types_text, encoding="utf-8")
        table_fbs = {table.table: table_fbs_text(table) for table, *_ in prepared}
        validate_canonical_fbs(types_text, table_fbs, list(workspace.resources.resources))
        written.append(str(types_path))

        for table_name, text in table_fbs.items():
            path = output_dir / "fbs" / f"{table_name}.fbs"
            path.write_text(text, encoding="utf-8")
            written.append(str(path))

        container = output_dir / "fbs" / "container.fbs"
        container.write_text(
            "table BundledTable {\n  name: string;\n  data: [ubyte];\n}\n"
            "table DataBundle {\n  tables: [BundledTable];\n}\n\nroot_type DataBundle;\n",
            encoding="utf-8",
        )
        written.append(str(container))
    finally:
        reporter.step_finished(CANONICAL_STEPS[3])

    # ---- 阶段 5：Binary Bundle ----
    reporter.step_started(CANONICAL_STEPS[4])
    try:
        bundle_dir = output_dir / "binary"
        bundle_dir.mkdir(parents=True, exist_ok=True)
        for lang in languages:
            _check_cancel(cancel_token)
            name_to_bytes = {name: bytes_by_lang[lang] for name, bytes_by_lang in table_bytes.items()}
            bundle = build_canonical_bundle(name_to_bytes)
            bundle_path = bundle_dir / f"data_{lang}.bin"
            bundle_path.write_bytes(bundle)
            written.append(str(bundle_path))
            bundle_hashes[lang] = bundle_fingerprint(
                lang,
                [(name, _sha(data)) for name, data in name_to_bytes.items()],
            )
    finally:
        reporter.step_finished(CANONICAL_STEPS[4])

    return {
        "tables": len(tables),
        "languages": languages,
        "written": written,
        "bundle_hashes": bundle_hashes,
        "forced": forced,
        "elapsed": round(time.perf_counter() - started, 2),
    }


def _sha(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


def _named_ref(field) -> str | None:
    from ct.schema.type_expression import NamedType, VectorType

    expr = field.type_expr
    if isinstance(expr, NamedType):
        return expr.name
    if isinstance(expr, VectorType) and isinstance(expr.element, NamedType):
        return expr.element.name
    return None
