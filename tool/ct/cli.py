from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional

import typer

from ct.app.i18n import read_i18n_rows
from ct.app.options import ExportOptions
from ct.app.events import CancelToken
from ct.app.export import ExportPipeline, ExportValidationError
from ct.app.status import compute_status
from ct.app.template import Action, decide_template_action
from ct.app.validate import parse_and_validate
from ct.app.workspace import Workspace
from ct.cache.state import load_cache
from ct.excel.diff import get_changed_tables
from ct.excel.template import generate_template, update_template
from ct.export.i18n.compact import CompactError, compact_i18n
from ct.export.i18n.status import (
    compute_status_report,
    render_by_table,
    render_default,
    render_json,
)
from ct.export.i18n.sync import sync_all
from ct.export.i18n.writer import report_stale_summary
from ct.validate.errors import report_errors

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


class CLIProgressReporter:
    """把管道事件渲染为 CLI 现有文本（步骤事件本身不输出，保持逐字一致）。"""

    def step_started(self, step: str) -> None:
        pass

    def step_finished(self, step: str) -> None:
        pass

    def log(self, line: str, *, err: bool = False) -> None:
        typer.echo(line, err=err)


@app.command()
def export(
    all_tables: bool = typer.Option(False, "--all", help="强制全量导出"),
    table: Optional[str] = typer.Option(None, "--table", help="只导出指定表"),
    lang: Optional[str] = typer.Option(None, "--lang", help="只导出指定语言"),
    verbose: bool = typer.Option(False, "--verbose", help="显示详细日志"),
    project_root: Optional[str] = typer.Option(None, "--root", help="项目根目录"),
) -> None:
    """增量导出主流程。"""
    opts = ExportOptions(all_tables=all_tables, table=table, lang=lang, verbose=verbose)
    _setup_logging(opts.verbose)
    root = Path(project_root) if project_root else Path(".")
    ws = Workspace.load(root)

    if not ws.schemas:
        typer.echo("未找到任何 schema", err=True)
        raise typer.Exit(1)

    cache = load_cache(ws.resolve("cache_dir"))
    excel_dir = ws.resolve("excel_dir")

    # 确定导出范围
    if opts.table:
        if opts.table not in ws.schema_map:
            typer.echo(f"表 '{opts.table}' 不存在", err=True)
            raise typer.Exit(1)
        tables_to_export = [opts.table]
    elif opts.all_tables:
        tables_to_export = ws.order
    else:
        tables_to_export = get_changed_tables(ws.schemas, cache, excel_dir)
        if not tables_to_export:
            typer.echo("所有表均无变化，跳过导出")
            return

    try:
        result = ExportPipeline().run(
            ws, opts, cache, tables_to_export, CLIProgressReporter(), CancelToken()
        )
    except ExportValidationError as e:
        report_errors(e.issues, opts.verbose)
        raise typer.Exit(1)

    # stale 报告（基于 lang 文件聚合）
    report_stale_summary(ws.config, ws.schemas)
    typer.echo(f"\n导出完成: {result.tables_exported} 张表")


@app.command()
def validate(
    table: Optional[str] = typer.Option(None, "--table", help="只校验指定表"),
    verbose: bool = typer.Option(False, "--verbose", help="显示详细日志"),
    project_root: Optional[str] = typer.Option(None, "--root", help="项目根目录"),
) -> None:
    """只走解析和校验，不输出产物。"""
    _setup_logging(verbose)
    root = Path(project_root) if project_root else Path(".")
    ws = Workspace.load(root)

    schemas, order = ws.schemas, ws.order
    cache = load_cache(ws.resolve("cache_dir"))
    excel_dir = ws.resolve("excel_dir")

    targets = [table] if table else order
    pv = parse_and_validate(
        ws,
        targets,
        cache,
        excel_dir,
        on_missing=lambda name, path: typer.echo(
            f"[error] {path} 不存在", err=True
        ),
    )
    all_errors = pv.errors

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
    ws = Workspace.load(root)

    schemas, _ = ws.schemas, ws.order
    schema_map = ws.schema_map
    excel_dir = ws.resolve("excel_dir")
    excel_dir.mkdir(parents=True, exist_ok=True)

    targets = [table] if table else [s.table for s in schemas] if all_tables else []
    if not targets:
        typer.echo("请指定 --all 或 --table <表名>", err=True)
        raise typer.Exit(1)

    refused = 0
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
            continue

        # CREATE_NEW or REBUILD: same code path, different message.
        generate_template(schema, out_path)
        typer.echo(decision.message)

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
    ws = Workspace.load(root)

    cache = load_cache(ws.resolve("cache_dir"))
    report = compute_status(ws, cache)

    # Render output: each section only appears if it has entries.
    if report.missing:
        typer.echo("缺失文件:")
        for name in report.missing:
            typer.echo(f"  [missing] {name}")

    if report.changed:
        typer.echo("数据变更（待导出）:")
        for name in report.changed:
            typer.echo(f"  [changed] {name}")

    if report.drifted:
        typer.echo("模板已过时（schema 修改后未重建）:")
        for name in report.drifted:
            typer.echo(
                f"  [template-stale] {name}  "
                f"(建议: ct gen-template --table {name} --update-header)"
            )

    if report.untracked:
        typer.echo("未跟踪元数据（legacy 文件）:")
        for name in report.untracked:
            typer.echo(f"  [template-untracked] {name}")

    if not report.has_anything:
        typer.echo("[OK] 所有表已是最新（数据 + 模板）")


# ---------------------------------------------------------------- ct i18n group


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
    ws = Workspace.load(root)
    schemas, _ = ws.schemas, ws.order

    if table and table not in {s.table for s in schemas}:
        typer.echo(f"表 '{table}' 不存在", err=True)
        raise typer.Exit(1)

    rows_result = read_i18n_rows(ws.config, schemas, table=table)
    for table_name, path in rows_result.missing:
        typer.echo(f"[warn] {path} 不存在，跳过 {table_name}", err=True)
    summary = sync_all(
        ws.config,
        schemas,
        rows_result.rows_by_table,
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
    ws = Workspace.load(root)
    schemas, _ = ws.schemas, ws.order

    report = compute_status_report(ws.config, schemas, lang_filter=lang)

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
    ws = Workspace.load(root)
    schemas, _ = ws.schemas, ws.order

    try:
        summary = compact_i18n(
            ws.config, schemas, lang=lang, table=table, dry_run=dry_run
        )
    except CompactError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(1)

    if not summary.touched:
        typer.echo("[compact] 无 orphan 条目，无需操作")
    else:
        for f in summary.files:
            if dry_run:
                typer.echo(
                    f"[dry-run] {f.lang}/{f.table}: 将移除 {len(f.removed_keys)} 条 orphan"
                )
                for k in f.removed_keys:
                    typer.echo(f"  - {k}")
            else:
                typer.echo(
                    f"[compact] {f.lang}/{f.table}: 移除 {len(f.removed_keys)} 条 orphan"
                )
        if not dry_run:
            typer.echo(f"\n[compact] 总计移除 {summary.total_removed} 条")


if __name__ == "__main__":
    app()
