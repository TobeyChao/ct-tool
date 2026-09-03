"""Canonical v4 export pipeline used when a workspace is canonical.

Reads Excel through the canonical layout/reader, merges i18n translations,
then writes JSON, shared ``types.fbs`` + per-table FBS, a real FlatBuffers
``DataBundle`` per language, C#/Lua accessors and layout manifests. The
legacy pipeline remains for legacy workspaces; ``ct export`` routes by
workspace format.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ct.app.canonical_workspace import CanonicalWorkspace
from ct.cache.canonical_state import CanonicalCacheState
from ct.cache.fingerprints import bundle_fingerprint
from ct.excel.canonical_reader import read_canonical_excel
from ct.excel.canonical_template import generate_canonical_template
from ct.excel.layout import build_layout
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

CODEGEN_VERSION = "v4.1"


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


def run_canonical_export(
    root: Path,
    *,
    table_filter: str | None = None,
    lang_filter: str | None = None,
) -> dict[str, Any]:
    """Run the canonical v4 export for a canonical workspace."""
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

    state = CanonicalCacheState()
    types_path = output_dir / "fbs" / "types.fbs"
    types_path.parent.mkdir(parents=True, exist_ok=True)
    table_fbs: dict[str, str] = {}
    written: list[str] = []
    table_bytes: dict[str, dict[str, bytes]] = {}

    for table in tables:
        layout = build_layout(
            table,
            schema_hash=compute_schema_hash(table, tuple(records.values())),
            records=records,
        )
        excel_path = excel_dir / (table.excel_file or f"{table.table}.xlsx")
        parsed = read_canonical_excel(excel_path, layout, table, records=records)
        base_rows = parsed.rows

        # JSON per language
        for lang in languages:
            rows = base_rows if lang == config.primary_lang else _merge_i18n(
                base_rows, table, load_translation(i18n_dir, lang, table.table)
            )
            lang_json = output_dir / "json" / f"{table.table}_{lang}.json"
            write_canonical_json(rows, table, lang_json)
            written.append(str(lang_json))

        # per-language bytes
        table_bytes[table.table] = {}
        for lang in languages:
            rows = base_rows if lang == config.primary_lang else _merge_i18n(
                base_rows, table, load_translation(i18n_dir, lang, table.table)
            )
            table_bytes[table.table][lang] = build_canonical_table_bytes(
                rows, table, records=records, enums=enums
            )

        # accessors (language-independent)
        model = build_accessor_model(table, ())
        csharp_path = generated / "csharp" / f"{table.table}Accessor.cs"
        lua_path = generated / "lua" / f"{table.table}Accessor.lua"
        csharp_path.parent.mkdir(parents=True, exist_ok=True)
        lua_path.parent.mkdir(parents=True, exist_ok=True)
        csharp_path.write_text(generate_csharp_accessor(model), encoding="utf-8")
        lua_path.write_text(generate_lua_accessor(model), encoding="utf-8")
        written.append(str(csharp_path))

        # template + layout manifest
        template_path = excel_dir / (table.excel_file or f"{table.table}.xlsx")
        if not template_path.exists():
            generate_canonical_template(
                layout, template_path, enums=enums, primary=table.primary
            )
            written.append(str(template_path))
        save_manifest(cache_dir, table.table, LayoutManifest.from_layout(layout))

        # per-table fbs text
        table_fbs[table.table] = table_fbs_text(table)

    # shared types.fbs + container
    order = [
        resource.resource_id
        for resource in sorted(workspace.resources.resources, key=lambda r: r.resource_id)
    ]
    resources_map: dict[str, SchemaResource] = {
        resource.resource_id: resource for resource in workspace.resources.resources
    }
    types_text = types_fbs_text(order, resources_map)
    types_path.write_text(types_text, encoding="utf-8")
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

    # real FlatBuffers DataBundle per language
    bundle_dir = output_dir / "binary"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    bundle_hashes: dict[str, str] = {}
    for lang in languages:
        name_to_bytes = {name: bytes_by_lang[lang] for name, bytes_by_lang in table_bytes.items()}
        bundle = build_canonical_bundle(name_to_bytes)
        bundle_path = bundle_dir / f"data_{lang}.bin"
        bundle_path.write_bytes(bundle)
        written.append(str(bundle_path))
        bundle_hashes[lang] = bundle_fingerprint(
            lang,
            [(name, _sha(data)) for name, data in name_to_bytes.items()],
        )

    return {
        "tables": len(tables),
        "languages": languages,
        "written": written,
        "bundle_hashes": bundle_hashes,
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
