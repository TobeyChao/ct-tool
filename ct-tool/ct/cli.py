from __future__ import annotations

import hashlib
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
    update_table_cache,
)
from ct.config import load_config
from ct.excel.diff import file_hash, get_changed_tables
from ct.excel.reader import read_excel
from ct.excel.template import generate_template
from ct.export.binary_writer import (
    build_i18n_table_bytes,
    build_table_bytes,
    write_i18n_bundle,
    write_primary_bundle,
)
from ct.export.fbs_generator import generate_container_fbs, generate_fbs
from ct.export.i18n.extractor import (
    extract_i18n_strings,
    load_source_strings,
    save_source_strings,
)
from ct.export.i18n.merger import load_translation, merge_translations
from ct.export.i18n.writer import report_stale_summary
from ct.export.json_writer import write_json
from ct.schema.loader import load_and_sort_schemas
from ct.validate.errors import report_errors
from ct.validate.refs import validate_refs
from ct.validate.types import validate_table

app = typer.Typer(help="配表导出工具")
logger = logging.getLogger("ct")


def _setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(message)s",
        stream=sys.stderr,
    )


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

    # i18n 处理
    source_strings = load_source_strings(i18n_dir)
    for name, rows in parsed_data.items():
        schema = schema_map[name]
        source_strings = extract_i18n_strings(rows, schema, source_strings)
    save_source_strings(source_strings, i18n_dir)

    # 导出
    # 收集所有表的 FlatBuffers bytes（用于 Bundle 全量重写）
    all_table_bytes: dict[str, bytes] = {}
    all_i18n_bytes: dict[str, bytes] = {}

    for name in order:
        schema = schema_map[name]
        if name in parsed_data:
            rows = parsed_data[name]

            # JSON 导出（每种语言）
            for l in langs:
                if l == cfg.primary_lang:
                    json_rows = rows
                else:
                    translations = load_translation(i18n_dir, l)
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

            # i18n bytes
            if schema.has_i18n:
                for l in langs:
                    if l == cfg.primary_lang:
                        i18n_bytes = build_i18n_table_bytes(rows, schema)
                    else:
                        translations = load_translation(i18n_dir, l)
                        merged = merge_translations(
                            rows, schema, l, translations, cfg.primary_lang
                        )
                        i18n_bytes = build_i18n_table_bytes(merged, schema)
                    all_i18n_bytes[f"{name}_i18n"] = i18n_bytes

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
            path = write_i18n_bundle(all_i18n_bytes, l, output_dir)
            if path:
                typer.echo(f"[bundle] {path.name}")

    # stale 报告
    report_stale_summary(source_strings)

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

    targets = [table] if table else [s.table for s in schemas] if all_tables else []
    if not targets:
        typer.echo("请指定 --all 或 --table <表名>", err=True)
        raise typer.Exit(1)

    for name in targets:
        if name not in schema_map:
            typer.echo(f"表 '{name}' 不存在", err=True)
            continue
        schema = schema_map[name]
        out_path = excel_dir / schema.resolved_excel_file
        generate_template(schema, out_path)
        typer.echo(f"[template] {out_path}")


@app.command()
def status(
    project_root: Optional[str] = typer.Option(None, "--root", help="项目根目录"),
) -> None:
    """对比当前 hash 与缓存，列出变更和未变更的表。"""
    _setup_logging()
    root = Path(project_root) if project_root else Path(".")
    cfg = load_config(root)

    schemas, _ = load_and_sort_schemas(cfg.resolve("schemas_dir"))
    cache = load_cache(cfg.resolve("cache_dir"))
    excel_dir = cfg.resolve("excel_dir")

    changed = get_changed_tables(schemas, cache, excel_dir)
    changed_set = set(changed)

    for s in schemas:
        xlsx_path = excel_dir / s.resolved_excel_file
        if not xlsx_path.exists():
            typer.echo(f"  [missing] {s.table}")
        elif s.table in changed_set:
            typer.echo(f"  [changed] {s.table}")
        else:
            typer.echo(f"  [  ok   ] {s.table}")


if __name__ == "__main__":
    app()
