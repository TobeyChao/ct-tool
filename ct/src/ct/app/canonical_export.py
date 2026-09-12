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

import shutil
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
from ct.cache.canonical_state import CanonicalCacheState, load_state, record_excel_hashes, save_state
from ct.cache.fingerprints import bundle_fingerprint
from ct.excel.canonical_reader import read_canonical_excel
from ct.excel.canonical_template import generate_canonical_template
from ct.excel.layout import Layout, build_layout
from ct.excel.layout_manifest import LayoutManifest, load_manifest, save_manifest
from ct.export.canonical_accessor import (
    generate_csharp_accessor,
    generate_csharp_enums,
    generate_lua_accessor,
    generate_lua_enums,
)
from ct.export.canonical_accessor_model import build_accessor_model
from ct.export.canonical_binary import (
    build_canonical_bundle,
    build_canonical_table_bytes,
    count_vtables,
    probe_row_layout,
    written_slot_ratio,
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

# 定宽布局（uniform）的启用阈值：字段填充率 >= 此值的表才开。
# 依据：填充率 75% 时体积膨胀 <=1.18x（实测扫描），低于此值稀疏表会明显变大。
# 收益：消除每行访问的 ConfigTable.OffsetsFor（2 种 vtable 约 2.9ns，16 种约 11.2ns）。
UNIFORM_FILL_THRESHOLD = 0.75


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


def _assert_single_vtable(name: str, lang: str, data: bytes, row_count: int) -> None:
    """定宽硬断言：开了 uniform 就必须真的只有 1 种 vtable。

    空表（0 行）没有行对象 ⇒ 自然也没有 vtable；「所有行共享同一 vtable」的
    前提**空真成立**，允许 0 种。有行时仍必须恰好 1 种，否则生成器发射的字面量
    偏移会静默读错位数据。
    """
    n_vt = count_vtables(data)
    if n_vt != 1 and not (n_vt == 0 and row_count == 0):
        raise CanonicalValidationError(
            [
                f"{name}[{lang}]：uniform 布局下出现 {n_vt} 种 vtable（要求恰好 1 种）"
                "——检查是否有字段类型漏了无条件写槽位"
            ]
        )


def _i18n_table(table: TableResource) -> TableResource | None:
    """该表的**稀疏 i18n 表**定义：主键 + i18n 字段（保持主表里的声明顺序）。

    与主表同序是「按下标定位」的前提（否则只能按主键二分查找）。
    没有 i18n 字段的表返回 ``None``（不产出 i18n 表）。
    """
    i18n_fields = [f for f in table.fields if f.i18n and not f.server_only]
    if not i18n_fields:
        return None
    primary = next((f for f in table.fields if f.name == table.primary), None)
    if primary is None:
        return None
    return TableResource(
        table=f"{table.table}_i18n",
        primary=table.primary,
        fields=[primary, *i18n_fields],
    )


def _i18n_rows(
    table: TableResource, i18n_table: TableResource, merged_rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """主表行 → i18n 表行（主键 + i18n 字段），**保持主表行序**。"""
    i18n_names = [f.name for f in i18n_table.fields if f.name != table.primary]
    return [
        {table.primary: row.get(table.primary), **{n: row.get(n) for n in i18n_names}}
        for row in merged_rows
    ]


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
    # 每张表的定宽布局决策与落盘信息（阶段 2 产生，阶段 3 写入 layout manifest）
    layout_info: dict[str, dict[str, Any]] = {}
    # 次级语言的**稀疏 i18n 表**字节：table → lang → bytes
    i18n_table_bytes: dict[str, dict[str, bytes]] = {}
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
            parsed = read_canonical_excel(excel_path, layout, table, records=records, enums=enums)
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

    # ---- B4：校验**通过后**清理「纯生成物」目录 ----
    # 陈旧的 output/fbs、output/generated 会让消费方看到**已废弃格式**的 schema
    # （实例：2026/8/14 的 *_i18n.fbs 与 9/10 的产物并存，而全仓已无代码生成它们）。
    # 只在**全量导出**时清理：带 table/lang 过滤的导出是增量的，不能删别的表。
    # ⚠️ 必须放在校验通过之后：校验失败（重复主键/悬空 ref 等）时，output/ 里的
    #    仍是上次成功导出的完整产物 —— 前置校验闸门承诺失败导出不落脏数据，
    #    更不能反过来把上次的成功产物删掉。
    if table_filter is None and lang_filter is None:
        # json / binary 是**整目录重写**的产物（每张表、每种语言各一份），
        # 删表或删语言后旧文件会残留（实测确认），所以一并清理。
        for stale_dir in ("fbs", "generated", "json", "binary"):
            target = output_dir / stale_dir
            if target.exists():
                shutil.rmtree(target)
                reporter.log(f"清理陈旧产物目录 output/{stale_dir}")

    # ---- 阶段 2：JSON + 各语言 bytes ----
    types_path = output_dir / "fbs" / "types.fbs"
    types_path.parent.mkdir(parents=True, exist_ok=True)
    reporter.step_started(CANONICAL_STEPS[1])
    try:
        for table, _layout, _excel_path, parsed in prepared:
            _check_cancel(cancel_token)
            base_rows = parsed.rows
            table_bytes[table.table] = {}

            # 逐表决定是否启用定宽布局：先用**非 uniform** 产出主语言字节，
            # 直接从字节统计填充率（不复刻写入规则），>= 阈值才开。
            client_count = len([f for f in table.fields if not f.server_only])
            probe = build_canonical_table_bytes(
                base_rows, table, records=records, enums=enums
            )
            fill = written_slot_ratio(probe, client_count)
            use_uniform = fill >= UNIFORM_FILL_THRESHOLD
            layout_info[table.table] = {
                "uniform": use_uniform,
                "fill_rate": fill,
                "bytes_normal": len(probe),
                "slot_offsets": probe_row_layout(table, records=records, enums=enums)
                if use_uniform
                else {},
            }

            # ---- 主语言：主表全量（含原文），随 data_{primary}.bin 一起加载 ----
            primary_rows = _merge_i18n(
                base_rows, table, load_translation(i18n_dir, config.primary_lang, table.table)
            )
            primary_json = output_dir / "json" / f"{table.table}_{config.primary_lang}.json"
            write_canonical_json(primary_rows, table, primary_json)
            written.append(str(primary_json))
            if config.primary_lang in languages:
                data = probe if not use_uniform else build_canonical_table_bytes(
                    primary_rows, table, records=records, enums=enums, uniform=True
                )
                if use_uniform:
                    _assert_single_vtable(table.table, config.primary_lang, data, len(primary_rows))
                    layout_info[table.table]["bytes_uniform"] = len(data)
                table_bytes[table.table][config.primary_lang] = data

            # ---- 次级语言：JSON 仍是「全量行」（可 diff 评审），
            #      bin 走**稀疏 i18n 表**（只含主键 + i18n 字段，行序与主表一致）----
            i18n_table = _i18n_table(table)
            if i18n_table is not None:
                i18n_table_bytes[table.table] = {}
                # i18n 表沿用主表的定宽决策；但它的 slot→offset 是**自己**的表级常量
                layout_info[i18n_table.table] = {
                    "uniform": use_uniform,
                    "fill_rate": fill,
                    "bytes_normal": 0,
                    "slot_offsets": probe_row_layout(
                        i18n_table, records=records, enums=enums
                    )
                    if use_uniform
                    else {},
                }
            for lang in languages:
                if lang == config.primary_lang:
                    continue
                merged = _merge_i18n(
                    base_rows, table, load_translation(i18n_dir, lang, table.table)
                )
                lang_json = output_dir / "json" / f"{table.table}_{lang}.json"
                write_canonical_json(merged, table, lang_json)
                written.append(str(lang_json))
                if i18n_table is None:
                    continue
                i18n_rows = _i18n_rows(table, i18n_table, merged)
                if len(i18n_rows) != len(primary_rows):
                    raise CanonicalValidationError(
                        [
                            f"{table.table}_i18n[{lang}]：{len(i18n_rows)} 行 ≠ 主表 "
                            f"{len(primary_rows)} 行 —— i18n 表与主表必须同序等长"
                        ]
                    )
                i18n_data = build_canonical_table_bytes(
                    i18n_rows, i18n_table, records=records, enums=enums, uniform=use_uniform
                )
                if use_uniform:
                    _assert_single_vtable(f"{table.table}_i18n", lang, i18n_data, len(i18n_rows))
                i18n_table_bytes[table.table][lang] = i18n_data

            info = layout_info[table.table]
            detail = f"填充率 {fill:.1%} → {'定宽' if use_uniform else '变长'}"
            if use_uniform:
                # bytes_uniform 只在主语言被纳入本次导出时才有（--lang 次级语言时
                # 主语言分支不产出字节），日志只报已计算的部分。
                detail += f"（{info['bytes_normal']:,} B"
                if "bytes_uniform" in info:
                    detail += (
                        f" → {info['bytes_uniform']:,} B，"
                        f"{info['bytes_uniform'] / info['bytes_normal']:.3f}x"
                    )
                detail += "）"
            reporter.log(f"{table.table}：{detail}")
    finally:
        reporter.step_finished(CANONICAL_STEPS[1])

    # ---- 阶段 3：Accessor + 模板/manifest ----
    reporter.step_started(CANONICAL_STEPS[2])
    try:
        for table, layout, excel_path, _parsed in prepared:
            _check_cancel(cancel_token)
            info = layout_info.get(table.table) or {}
            sparse_i18n = _i18n_table(table)
            # 稀疏 i18n 表**不再**单独产出 accessor：它的唯一消费者是主表的字段 getter，
            # 读路径已经内联进主 accessor（`_emit_csharp_i18n_support`）。
            # 但它**自己的**定宽偏移仍要交给生成器 —— 那是另一份表级常量。
            i18n_info = (layout_info.get(sparse_i18n.table) or {}) if sparse_i18n is not None else {}
            model = build_accessor_model(
                table,
                # 表级查询索引（Code/Group）：来自 schema（原先硬编码成 () ⇒ 永不生成 ByCode/ByGroupKey）
                tuple(table.indexes),
                records=records,
                # 定宽表：偏移是表级常量，生成器发射字面量（无偏移表）
                uniform_offsets=(info.get("slot_offsets") or None) if info.get("uniform") else None,
                # 多语言字段按行下标去稀疏 i18n 表读当前语言
                i18n_table=sparse_i18n.table if sparse_i18n is not None else None,
                i18n_uniform_offsets=(i18n_info.get("slot_offsets") or None)
                if i18n_info.get("uniform")
                else None,
            )
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
            manifest_dir = excel_dir / "layout_manifests"
            old_manifest = load_manifest(manifest_dir, table.table)
            save_manifest(
                manifest_dir,
                table.table,
                LayoutManifest.from_layout(
                    layout,
                    previous_revision=old_manifest.layout_revision
                    if old_manifest is not None
                    else 0,
                    # 定宽布局决策 + 表级 slot→offset 常量，供生成器读取
                    layout_info=layout_info.get(table.table),
                ),
            )

        # 枚举类型声明：生成物里的 (Enum)WireReader.I8At(...) cast 需要它才能编译
        if enums:
            enum_cs = generated / "csharp" / "Enums.cs"
            enum_lua = generated / "lua" / "Enums.lua"
            enum_cs.parent.mkdir(parents=True, exist_ok=True)
            enum_lua.parent.mkdir(parents=True, exist_ok=True)
            enum_cs.write_text(generate_csharp_enums(enums), encoding="utf-8")
            enum_lua.write_text(generate_lua_enums(enums), encoding="utf-8")
            written.extend([str(enum_cs), str(enum_lua)])
            reporter.log(f"枚举声明 {len(enums)} 个 → Enums.cs / Enums.lua")
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
            if lang == config.primary_lang:
                # 主语言包 = 主表（全量字段）
                name_to_bytes = {
                    name: bytes_by_lang[lang]
                    for name, bytes_by_lang in table_bytes.items()
                    if lang in bytes_by_lang
                }
            else:
                # 次级语言包 = **稀疏 i18n 表**（ItemType_i18n / Item_i18n / ...）
                name_to_bytes = {
                    f"{name}_i18n": bytes_by_lang[lang]
                    for name, bytes_by_lang in i18n_table_bytes.items()
                    if lang in bytes_by_lang
                }
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

    excel_hashes = {
        table.table: _sha(excel_path.read_bytes())
        for table, _layout, excel_path, _parsed in prepared
    }

    return {
        "tables": len(tables),
        "languages": languages,
        "written": written,
        "bundle_hashes": bundle_hashes,
        "excel_hashes": excel_hashes,
        "forced": forced,
        "elapsed": round(time.perf_counter() - started, 2),
    }


def _sha(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


def persist_export_state(
    root: Path,
    excel_hashes: dict[str, str],
    bundle_hashes: dict[str, str],
) -> Path:
    """Commit the export data fingerprint ledger to `cache/state.json`.

    Called only after a fully successful `ct export` (including any deploy):
    a failed run leaves the workspace cache untouched, so `ct status` keeps
    reporting the last-good state. `excel_hashes` keys are table names and
    values are the sha256 of the Excel file at export time; this is what
    `canonical_status` compares to detect a data edit pending re-export.
    Tables absent from `excel_hashes` (e.g. a `--table`-limited export)
    keep their previously recorded hash.
    """
    from ct.config import load_config

    config = load_config(root)
    cache_dir = config.resolve("cache_dir")
    state = load_state(cache_dir) or CanonicalCacheState()
    state = record_excel_hashes(state, excel_hashes)
    state = CanonicalCacheState(
        tables=state.tables,
        bundles={**state.bundles, **bundle_hashes},
        layout_revisions=state.layout_revisions,
        excel_hashes=state.excel_hashes,
    )
    return save_state(cache_dir, state)


def _named_ref(field) -> str | None:
    from ct.schema.type_expression import NamedType, VectorType

    expr = field.type_expr
    if isinstance(expr, NamedType):
        return expr.name
    if isinstance(expr, VectorType) and isinstance(expr.element, NamedType):
        return expr.element.name
    return None
