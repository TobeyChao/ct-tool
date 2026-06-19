from __future__ import annotations

import hashlib
import json
import logging
import sys
from pathlib import Path
from typing import Optional

import typer

from ct.cache.state import (
    load_cache,
    load_fbs_bytes,
    save_cache,
    save_fbs_bytes,
    update_schema_hash,
    update_table_cache,
)
from ct.cli_helpers.template_action import Action, decide_template_action
from ct.config import load_config
from ct.excel.diff import file_hash, get_changed_tables
from ct.excel.reader import read_excel
from ct.excel.template import generate_template, read_template_metadata, update_template
from ct.export.binary_writer import (
    build_i18n_table_bytes,
    build_table_bytes,
    write_i18n_bundle,
    write_primary_bundle,
)
from ct.export.fbs_generator import generate_container_fbs, generate_fbs
from ct.export.i18n.merger import load_translation, merge_translations
from ct.export.i18n.status import (
    compute_status_report,
    render_by_table,
    render_default,
    render_json,
)
from ct.export.i18n.sync import sync_all
from ct.export.i18n.writer import report_stale_summary
from ct.export.json_writer import write_json
from ct.schema.hashing import compute_schema_hash
from ct.schema.loader import load_and_sort_schemas
from ct.validate.errors import report_errors
from ct.validate.refs import validate_refs
from ct.validate.types import validate_table

app = typer.Typer(help="配表导出工具")
i18n_app = typer.Typer(help="i18n 翻译骨架与状态管理")
app.add_typer(i18n_app, name="i18n")
logger = logging.getLogger("ct")


def _setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(message)s",
        stream=sys.stderr,
    )


def _print_sync_summary(summary, *, prefix: str = "[i18n sync]") -> None:
    totals = summary.totals_by_lang()
    if not totals:
        typer.echo(f"{prefix} 无 secondary 语言或无 i18n 表，跳过", err=True)
        return
    parts = []
    for lang, counts in sorted(totals.items()):
        parts.append(
            f"{lang}: translated={counts.translated}, missing={counts.missing}, "
            f"stale={counts.stale}, orphan={counts.orphan}"
        )
    typer.echo(f"{prefix} " + "; ".join(parts), err=True)


@app.command()
def export(
    all_tables: bool = typer.Option(False, "--all", help="强制全量导出"),
    table: Optional[str] = typer.Option(None, "--table", help="只导出指定表"),
    lang: Optional[str] = typer.Option(None, "--lang", help="只导出指定语言"),
    verbose: bool = typer.Option(False, "--verbose", help="显示详细日志"),
    project_root: Optional[str] = typer.Option(None, "--root", help="项目根目录"),
) -> None:
    """增量导出主流程。"""
    _setup_logging(verbose)
    root = Path(project_root) if project_root else Path(".")
    cfg = load_config(root)

    schemas, order = load_and_sort_schemas(cfg.resolve("schemas_dir"))
    if not schemas:
        typer.echo("未找到任何 schema", err=True)
        raise typer.Exit(1)

    schema_map = {s.table: s for s in schemas}
    cache = load_cache(cfg.resolve("cache_dir"))
    excel_dir = cfg.resolve("excel_dir")
    output_dir = cfg.resolve("output_dir")
    i18n_dir = cfg.resolve("i18n_dir")
    cache_dir = cfg.resolve("cache_dir")

    # 确定导出范围
    if table:
        if table not in schema_map:
            typer.echo(f"表 '{table}' 不存在", err=True)
            raise typer.Exit(1)
        tables_to_export = [table]
    elif all_tables:
        tables_to_export = order
    else:
        tables_to_export = get_changed_tables(schemas, cache, excel_dir)
        if not tables_to_export:
            typer.echo("所有表均无变化，跳过导出")
            return

    # 确定语言范围
    if lang:
        langs = [lang]
    else:
        langs = cfg.all_langs

    # 解析和校验
    parsed_data: dict[str, list[dict]] = {}
    id_sets: dict[str, set] = {}
    all_errors: list[str] = []

    # 先从 cache 加载未变化表的 id 集合
    for name in order:
        if name not in tables_to_export:
            cached_ids = cache.tables.get(name)
            if cached_ids:
                id_sets[name] = set(cached_ids.ids)

    # 解析变化的表
    for name in order:
        if name not in tables_to_export:
            continue
        schema = schema_map[name]
        xlsx_path = excel_dir / schema.resolved_excel_file
        if not xlsx_path.exists():
            typer.echo(f"[error] {xlsx_path} 不存在，跳过 {name}", err=True)
            continue

        typer.echo(f"[parse] {name}")
        rows = read_excel(xlsx_path, schema)
        parsed_data[name] = rows

        # 收集 id 集合
        pk = schema.primary
        id_sets[name] = {row[pk] for row in rows if pk in row}

        # 类型校验
        errors = validate_table(rows, schema)
        all_errors.extend(errors)

    # 引用校验（按拓扑顺序）
    for name in order:
        if name not in parsed_data:
            continue
        schema = schema_map[name]
        if schema.all_refs():
            errors = validate_refs(parsed_data[name], schema, id_sets)
            all_errors.extend(errors)

    if all_errors:
        report_errors(all_errors, verbose)
        raise typer.Exit(1)

    # i18n sync：只对本次解析的变更表刷新 source 与各 lang 骨架
    changed_i18n_schemas = [schema_map[name] for name in parsed_data]
    sync_summary = sync_all(cfg, changed_i18n_schemas, parsed_data)
    if verbose:
        _print_sync_summary(sync_summary)

    # 导出
    # 收集所有表的 FlatBuffers bytes（用于 Bundle 全量重写）
    all_table_bytes: dict[str, bytes] = {}
    # {lang: {table_i18n_key: bytes}}  每种语言独立存，避免多语言覆盖
    all_i18n_bytes: dict[str, dict[str, bytes]] = {}

    for name in order:
        schema = schema_map[name]
        if name in parsed_data:
            rows = parsed_data[name]

            # JSON 导出（每种语言）
            for l in langs:
                if l == cfg.primary_lang:
                    json_rows = rows
                else:
                    translations = load_translation(i18n_dir, l, schema.table)
                    json_rows = merge_translations(
                        rows, schema, l, translations, cfg.primary_lang
                    )
                path = write_json(json_rows, schema, l, output_dir)
                typer.echo(f"[json] {path.name}")

            # FlatBuffers bytes（不含 server_only）
            fbs_bytes = build_table_bytes(rows, schema, exclude_server_only=True)
            all_table_bytes[name] = fbs_bytes

            # 缓存 fbs bytes
            save_fbs_bytes(cache_dir, name, fbs_bytes)
            fbs_hash = hashlib.md5(fbs_bytes).hexdigest()

            # i18n bytes（只缓存 secondary 语言，主语言已在主线 bundle 中）
            if schema.has_i18n:
                for l in langs:
                    if l == cfg.primary_lang:
                        continue  # 主语言 i18n 数据已在 data_{primary}.bin 中，无需单独缓存
                    translations = load_translation(i18n_dir, l, schema.table)
                    merged = merge_translations(
                        rows, schema, l, translations, cfg.primary_lang
                    )
                    i18n_bytes = build_i18n_table_bytes(merged, schema)
                    all_i18n_bytes.setdefault(l, {})[f"{name}_i18n"] = i18n_bytes
                    # 按语言缓存 i18n bytes，供增量导出时复用
                    save_fbs_bytes(cache_dir, f"{name}_i18n_{l}", i18n_bytes)

            # 更新 cache
            xlsx_path = excel_dir / schema.resolved_excel_file
            h = file_hash(xlsx_path)
            update_table_cache(
                cache, name,
                hash=h,
                ids=sorted(id_sets.get(name, set())),
                fbs_bytes_hash=fbs_hash,
            )
        else:
            # 未变化的表：从 cache 复用 bytes
            cached_bytes = load_fbs_bytes(cache_dir, name)
            if cached_bytes:
                all_table_bytes[name] = cached_bytes
                typer.echo(f"[skip] {name} (unchanged)")
            # 同时尝试加载各 secondary 语言的 i18n bytes 缓存
            if schema.has_i18n:
                for l in langs:
                    if l == cfg.primary_lang:
                        continue
                    cached_i18n = load_fbs_bytes(cache_dir, f"{name}_i18n_{l}")
                    if cached_i18n:
                        all_i18n_bytes.setdefault(l, {})[f"{name}_i18n"] = cached_i18n

    # 生成 .fbs 文件
    for name in order:
        schema = schema_map[name]
        fbs_path = generate_fbs(schema, output_dir)
        typer.echo(f"[fbs] {fbs_path.name}")
    generate_container_fbs(output_dir)
    typer.echo("[fbs] container.fbs")

    # 调用 flatc
    flatc_path = cfg.resolve("flatc_path")
    if flatc_path.exists():
        from ct.export.flatc_runner import compile_fbs
        fbs_dir = output_dir / "fbs"
        compile_fbs(flatc_path, fbs_dir, output_dir)
    else:
        typer.echo(f"[warn] flatc 未找到 ({flatc_path})，跳过编译", err=True)

    # 生成 Accessor
    try:
        from ct.export.csharp_accessor_generator import generate_csharp_accessor
        from ct.export.lua_accessor_generator import generate_lua_accessor
        for name in order:
            schema = schema_map[name]
            cs_path = generate_csharp_accessor(schema, output_dir / "generated" / "csharp")
            typer.echo(f"[accessor] {cs_path.name}")
            lua_path = generate_lua_accessor(schema, output_dir / "generated" / "lua")
            typer.echo(f"[accessor] {lua_path.name}")
    except ImportError:
        pass

    # 写入 Binary Bundle
    if all_table_bytes:
        path = write_primary_bundle(all_table_bytes, cfg.primary_lang, output_dir)
        typer.echo(f"[bundle] {path.name}")

    for l in langs:
        if l != cfg.primary_lang:
            path = write_i18n_bundle(all_i18n_bytes.get(l, {}), l, output_dir)
            if path:
                typer.echo(f"[bundle] {path.name}")

    # stale 报告（基于 lang 文件聚合）
    report_stale_summary(cfg, schemas)

    save_cache(cache, cache_dir)
    typer.echo(f"\n导出完成: {len(tables_to_export)} 张表")


@app.command()
def validate(
    table: Optional[str] = typer.Option(None, "--table", help="只校验指定表"),
    verbose: bool = typer.Option(False, "--verbose", help="显示详细日志"),
    project_root: Optional[str] = typer.Option(None, "--root", help="项目根目录"),
) -> None:
    """只走解析和校验，不输出产物。"""
    _setup_logging(verbose)
    root = Path(project_root) if project_root else Path(".")
    cfg = load_config(root)

    schemas, order = load_and_sort_schemas(cfg.resolve("schemas_dir"))
    schema_map = {s.table: s for s in schemas}
    cache = load_cache(cfg.resolve("cache_dir"))
    excel_dir = cfg.resolve("excel_dir")

    targets = [table] if table else order
    all_errors: list[str] = []
    id_sets: dict[str, set] = {}

    for name in order:
        if name not in targets:
            cached = cache.tables.get(name)
            if cached:
                id_sets[name] = set(cached.ids)
            continue

        schema = schema_map[name]
        xlsx_path = excel_dir / schema.resolved_excel_file
        if not xlsx_path.exists():
            typer.echo(f"[error] {xlsx_path} 不存在", err=True)
            continue

        rows = read_excel(xlsx_path, schema)
        pk = schema.primary
        id_sets[name] = {row[pk] for row in rows if pk in row}

        errors = validate_table(rows, schema)
        all_errors.extend(errors)

        if schema.all_refs():
            errors = validate_refs(rows, schema, id_sets)
            all_errors.extend(errors)

    if all_errors:
        report_errors(all_errors, verbose)
        raise typer.Exit(1)
    else:
        typer.echo("校验通过")


@app.command("gen-template")
def gen_template(
    all_tables: bool = typer.Option(False, "--all", help="生成所有表模板"),
    table: Optional[str] = typer.Option(None, "--table", help="只生成指定表模板"),
    force: bool = typer.Option(
        False, "--force",
        help="强制全量覆盖（数据丢失）。无元数据 / hash 一致 / hash 不同有数据 时需要。",
    ),
    update_header: bool = typer.Option(
        False, "--update-header",
        help="重建表头并保留旧数据行原样追加（推荐用于 schema 变更）。",
    ),
    project_root: Optional[str] = typer.Option(None, "--root", help="项目根目录"),
) -> None:
    """根据 schema 生成 Excel 模板头部。"""
    _setup_logging()
    root = Path(project_root) if project_root else Path(".")
    cfg = load_config(root)

    schemas, _ = load_and_sort_schemas(cfg.resolve("schemas_dir"))
    schema_map = {s.table: s for s in schemas}
    excel_dir = cfg.resolve("excel_dir")
    excel_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = cfg.resolve("cache_dir")
    cache = load_cache(cache_dir)

    targets = [table] if table else [s.table for s in schemas] if all_tables else []
    if not targets:
        typer.echo("请指定 --all 或 --table <表名>", err=True)
        raise typer.Exit(1)

    refused = 0
    cache_dirty = False
    for name in targets:
        if name not in schema_map:
            typer.echo(f"表 '{name}' 不存在", err=True)
            refused += 1
            continue
        schema = schema_map[name]
        out_path = excel_dir / schema.resolved_excel_file

        decision = decide_template_action(
            schema, out_path, force=force, update_header=update_header,
        )

        if decision.action == Action.REFUSE:
            typer.echo(decision.message, err=True)
            refused += 1
            continue

        if decision.action == Action.SKIP:
            typer.echo(decision.message)
            continue

        if decision.action == Action.UPDATE_PRESERVE:
            preserved = update_template(schema, out_path)
            typer.echo(f"{decision.message} (保留 {preserved} 行数据)")
            update_schema_hash(cache, name, compute_schema_hash(schema))
            cache_dirty = True
            continue

        # CREATE_NEW or REBUILD: same code path, different message.
        generate_template(schema, out_path)
        typer.echo(decision.message)
        update_schema_hash(cache, name, compute_schema_hash(schema))
        cache_dirty = True

    if cache_dirty:
        save_cache(cache, cache_dir)

    if refused > 0:
        raise typer.Exit(1)


@app.command()
def status(
    project_root: Optional[str] = typer.Option(None, "--root", help="项目根目录"),
) -> None:
    """对比当前 hash 与缓存，列出变更和未变更的表。

    输出两类状态：
      - 数据变更：Excel 文件 hash 与缓存不一致（待导出）
      - 模板漂移：当前 schema_hash 与模板元数据不一致（建议重建模板）
    """
    _setup_logging()
    root = Path(project_root) if project_root else Path(".")
    cfg = load_config(root)

    schemas, _ = load_and_sort_schemas(cfg.resolve("schemas_dir"))
    cache = load_cache(cfg.resolve("cache_dir"))
    excel_dir = cfg.resolve("excel_dir")

    changed = get_changed_tables(schemas, cache, excel_dir)
    changed_set = set(changed)

    # Classify each table's template state.
    drifted: list[str] = []
    untracked: list[str] = []
    missing: list[str] = []
    for s in schemas:
        xlsx_path = excel_dir / s.resolved_excel_file
        if not xlsx_path.exists():
            missing.append(s.table)
            continue
        current_hash = compute_schema_hash(s)
        cached = cache.tables.get(s.table)
        # Fast path: cached hash matches → template is up-to-date, no Excel read needed.
        if cached is not None and cached.schema_hash == current_hash:
            continue
        # Slow path: confirm by reading the file's metadata.
        meta = read_template_metadata(xlsx_path)
        if meta is None:
            untracked.append(s.table)
            continue
        if meta.schema_hash != current_hash:
            drifted.append(s.table)

    # Render output: each section only appears if it has entries.
    has_anything = bool(changed_set or drifted or untracked or missing)

    if missing:
        typer.echo("缺失文件:")
        for name in missing:
            typer.echo(f"  [missing] {name}")

    if changed_set:
        typer.echo("数据变更（待导出）:")
        for s in schemas:
            if s.table in changed_set:
                typer.echo(f"  [changed] {s.table}")

    if drifted:
        typer.echo("模板已过时（schema 修改后未重建）:")
        for name in drifted:
            typer.echo(
                f"  [template-stale] {name}  "
                f"(建议: ct gen-template --table {name} --update-header)"
            )

    if untracked:
        typer.echo("未跟踪元数据（legacy 文件）:")
        for name in untracked:
            typer.echo(f"  [template-untracked] {name}")

    if not has_anything:
        typer.echo("[OK] 所有表已是最新（数据 + 模板）")


# ---------------------------------------------------------------- ct i18n group


def _read_all_rows_for_sync(cfg, schemas) -> dict[str, list[dict]]:
    """为 sync 命令读取所有 i18n 表的 Excel 行数据。"""
    excel_dir = cfg.resolve("excel_dir")
    rows_by_table: dict[str, list[dict]] = {}
    for schema in schemas:
        if not schema.has_i18n:
            continue
        xlsx_path = excel_dir / schema.resolved_excel_file
        if not xlsx_path.exists():
            typer.echo(f"[warn] {xlsx_path} 不存在，跳过 {schema.table}", err=True)
            continue
        rows_by_table[schema.table] = read_excel(xlsx_path, schema)
    return rows_by_table


@i18n_app.command("sync")
def i18n_sync(
    lang: Optional[str] = typer.Option(None, "--lang", help="只处理指定语言的 lang 文件"),
    table: Optional[str] = typer.Option(None, "--table", help="只处理指定表"),
    project_root: Optional[str] = typer.Option(None, "--root", help="项目根目录"),
    verbose: bool = typer.Option(False, "--verbose", help="显示详细日志"),
) -> None:
    """刷新 i18n source 文件并为每个 secondary 语言生成/更新 lang 骨架。"""
    _setup_logging(verbose)
    root = Path(project_root) if project_root else Path(".")
    cfg = load_config(root)
    schemas, _ = load_and_sort_schemas(cfg.resolve("schemas_dir"))

    target_schemas = schemas
    if table:
        target_schemas = [s for s in schemas if s.table == table]
        if not target_schemas:
            typer.echo(f"表 '{table}' 不存在", err=True)
            raise typer.Exit(1)

    rows_by_table = _read_all_rows_for_sync(cfg, target_schemas)
    summary = sync_all(
        cfg,
        target_schemas,
        rows_by_table,
        lang_filter=lang,
        table_filter=table,
    )

    if verbose:
        resolved_root = root.resolve()
        for path in summary.source_files_written:
            try:
                rel = path.relative_to(resolved_root)
            except ValueError:
                rel = path
            typer.echo(f"[source] {rel}", err=True)
        for path in summary.lang_files_written:
            try:
                rel = path.relative_to(resolved_root)
            except ValueError:
                rel = path
            typer.echo(f"[lang]   {rel}", err=True)

    _print_sync_summary(summary)
    typer.echo(f"[i18n sync] 完成（{summary.elapsed:.2f}s）", err=True)


@i18n_app.command("status")
def i18n_status(
    lang: Optional[str] = typer.Option(None, "--lang", help="只显示指定语言"),
    by_table: bool = typer.Option(False, "--by-table", help="按表细分"),
    json_out: bool = typer.Option(False, "--json", help="输出 JSON"),
    project_root: Optional[str] = typer.Option(None, "--root", help="项目根目录"),
) -> None:
    """报告 i18n 翻译进度。"""
    _setup_logging()
    root = Path(project_root) if project_root else Path(".")
    cfg = load_config(root)
    schemas, _ = load_and_sort_schemas(cfg.resolve("schemas_dir"))

    report = compute_status_report(cfg, schemas, lang_filter=lang)

    if json_out:
        sys.stdout.write(render_json(report))
    elif by_table:
        sys.stdout.write(render_by_table(report))
    else:
        sys.stdout.write(render_default(report))


@i18n_app.command("compact")
def i18n_compact(
    lang: Optional[str] = typer.Option(None, "--lang", help="只处理指定语言"),
    table: Optional[str] = typer.Option(None, "--table", help="只处理指定表"),
    dry_run: bool = typer.Option(False, "--dry-run", help="仅打印将被删除的条目，不修改文件"),
    project_root: Optional[str] = typer.Option(None, "--root", help="项目根目录"),
) -> None:
    """物理移除 lang 文件中所有 status: orphan 的条目。"""
    _setup_logging()
    root = Path(project_root) if project_root else Path(".")
    cfg = load_config(root)
    schemas, _ = load_and_sort_schemas(cfg.resolve("schemas_dir"))
    i18n_dir = cfg.resolve("i18n_dir")

    langs = cfg.secondary_langs
    if lang:
        if lang not in langs:
            typer.echo(f"语言 '{lang}' 不在 secondary_langs 中", err=True)
            raise typer.Exit(1)
        langs = [lang]

    target_schemas = [s for s in schemas if s.has_i18n]
    if table:
        target_schemas = [s for s in target_schemas if s.table == table]

    from ct.cli_helpers.i18n_json import dump_lang_file

    total_removed = 0
    touched = False

    for l in langs:
        for schema in target_schemas:
            path = i18n_dir / l / f"{schema.table}.json"
            if not path.exists():
                continue
            with open(path, encoding="utf-8") as f:
                data = json.load(f)

            orphan_keys = [k for k, v in data.items() if v.get("status") == "orphan"]
            if not orphan_keys:
                continue

            touched = True
            if dry_run:
                typer.echo(f"[dry-run] {l}/{schema.table}: 将移除 {len(orphan_keys)} 条 orphan")
                for k in orphan_keys:
                    typer.echo(f"  - {k}")
                continue

            for k in orphan_keys:
                del data[k]
            field_order = [f.name for f in schema.i18n_fields]
            dump_lang_file(data, path, field_order)
            total_removed += len(orphan_keys)
            typer.echo(f"[compact] {l}/{schema.table}: 移除 {len(orphan_keys)} 条 orphan")

    if not touched:
        typer.echo("[compact] 无 orphan 条目，无需操作")
    elif not dry_run:
        typer.echo(f"\n[compact] 总计移除 {total_removed} 条")


if __name__ == "__main__":
    app()
