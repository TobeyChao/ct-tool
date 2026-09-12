from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional

import typer

from ct.app.canonical_commands import (
    CanonicalValidationError,
    canonical_gen_template,
    canonical_i18n_compact,
    canonical_i18n_status,
    canonical_i18n_sync,
    canonical_publication_state,
    canonical_status,
    canonical_validate,
)
from ct.app.canonical_workspace import CanonicalWorkspace
from ct.app.exporting.models import CompletionPolicy, ExportRequest
from ct.app.exporting.service import run_export
from ct.config import load_config
from ct.diagnostics.errors import report_errors
from ct.export.deploy import deploy
from ct.storage.publication import FilePublisher, PublicationError
from ct.storage.workspace_lock import WorkspaceBusyError

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


def _root(project_root: Optional[str]) -> Path:
    return Path(project_root) if project_root else Path(".")


class CLIProgressReporter:
    """把管道事件渲染为 CLI 现有文本（步骤事件本身不输出，保持逐字一致）。"""

    def step_started(self, step: str) -> None:
        pass

    def step_finished(self, step: str) -> None:
        pass

    def log(self, line: str, *, err: bool = False) -> None:
        typer.echo(line, err=err)


def _friendly_exit(prefix: str, exc: BaseException) -> None:
    """配置/schema 级失败：友好提示 + 退出码 1，不把 Python 堆栈丢给策划。

    `--verbose`（日志级别 DEBUG）时先把完整堆栈写进日志，供开发排查
    （`Designer-friendly error messages` 要求的 `--verbose` 逃生门）。
    已在异常处理中的调用会带堆栈；纯参数校验（如未知语言）没有堆栈可打。
    """
    if logger.isEnabledFor(logging.DEBUG) and sys.exc_info()[0] is not None:
        logger.debug("命令失败", exc_info=True)
    typer.echo(f"{prefix} {exc}", err=True)
    raise typer.Exit(1)


def _load_workspace(root: Path) -> CanonicalWorkspace:
    """加载 canonical workspace；配置/schema 错误转为友好提示（不抛 traceback）。"""
    try:
        return CanonicalWorkspace.load(root)
    except (FileNotFoundError, ValueError) as e:
        _friendly_exit("[error]", e)


def _echo_deploy_result(changed: int) -> None:
    """部署结果的 CLI 呈现（业务层不打印文本）。"""
    if changed:
        typer.echo(f"[deploy] 完成：{changed} 个文件已同步")
    else:
        typer.echo("[deploy] 无文件变更")


def _deploy_for_service(root: Path, for_build: bool):
    """服务用的部署回调：失败仍渲染成既有的 `[deploy error]` 并非零退出。"""

    def run(received_for_build: bool, reporter) -> int:
        try:
            return deploy(load_config(root), received_for_build, reporter)
        except (FileNotFoundError, OSError) as e:
            typer.echo(f"[deploy error] {e}", err=True)
            raise typer.Exit(1)

    return run


def _run_deploy(root: Path, for_build: bool) -> None:
    """执行部署并渲染结果；失败以友好提示退出。

    部署前先恢复未完成的本地发布，保证部署读到的是一份完整版本。
    """
    try:
        recovery = FilePublisher(root).recover()
        if recovery:
            typer.echo(f"[发布恢复] {recovery}", err=True)
        config = load_config(root)
        n = deploy(config, for_build, CLIProgressReporter())
    except PublicationError as e:
        typer.echo(f"[publish error] {e}", err=True)
        raise typer.Exit(1)
    except (FileNotFoundError, OSError) as e:
        typer.echo(f"[deploy error] {e}", err=True)
        raise typer.Exit(1)
    if n:
        typer.echo(f"[deploy] 完成：{n} 个文件已同步")
    else:
        typer.echo("[deploy] 无文件变更")


@app.command()
def export(
    all_tables: bool = typer.Option(
        False, "--all", help="强制重建所有选中产物，跳过增量缓存"
    ),
    table: Optional[str] = typer.Option(None, "--table", help="只导出指定表"),
    lang: Optional[str] = typer.Option(None, "--lang", help="只导出指定语言"),
    verbose: bool = typer.Option(False, "--verbose", help="显示详细日志"),
    for_build: bool = typer.Option(False, "--for-build", help="部署时追加构建目标"),
    project_root: Optional[str] = typer.Option(None, "--root", help="项目根目录"),
) -> None:
    """导出主流程（canonical）：默认增量复用，--all 强制重建。"""
    _setup_logging(verbose)
    root = _root(project_root)
    try:
        # 完整应用用例：持锁 → 恢复 → 发布 → 通知 → 部署 → 记账，全在一个服务里
        run_export(
            ExportRequest(
                root=root,
                table_filter=table,
                lang_filter=lang,
                forced=all_tables,
            ),
            policy=CompletionPolicy.export_then_deploy(for_build=for_build),
            reporter=CLIProgressReporter(),
            notify=lambda result: typer.echo(f"\n导出完成: {result.tables} 张表"),
            on_deploy=_echo_deploy_result,
            deployer=_deploy_for_service(root, for_build),
        )
    except CanonicalValidationError as e:
        report_errors(e.issues, verbose)
        raise typer.Exit(1)
    except WorkspaceBusyError as e:
        typer.echo(f"[export error] {e}", err=True)
        raise typer.Exit(1)
    except PublicationError as e:
        typer.echo(f"[publish error] {e}", err=True)
        raise typer.Exit(1)
    except (FileNotFoundError, ValueError, OSError) as e:
        typer.echo(f"[export error] {e}", err=True)
        raise typer.Exit(1)


@app.command("deploy")
def deploy_command(
    for_build: bool = typer.Option(False, "--for-build", help="追加构建目标（StreamingAssets）"),
    project_root: Optional[str] = typer.Option(None, "--root", help="项目根目录"),
) -> None:
    """只部署当前产物到 Unity Assets，不触发导出。"""
    _setup_logging()
    _run_deploy(_root(project_root), for_build)


@app.command()
def validate(
    table: Optional[str] = typer.Option(None, "--table", help="只校验指定表"),
    verbose: bool = typer.Option(False, "--verbose", help="显示详细日志"),
    project_root: Optional[str] = typer.Option(None, "--root", help="项目根目录"),
) -> None:
    """只走解析和校验，不输出产物。"""
    _setup_logging(verbose)
    root = _root(project_root)
    try:
        errors = canonical_validate(root, table_filter=table)
    except (FileNotFoundError, ValueError) as e:
        # schema/配置级错误（例如非 int32 主键）：友好报错，不丢 traceback
        _friendly_exit("[error]", e)
    if errors:
        report_errors(errors, verbose)
        raise typer.Exit(1)
    typer.echo("校验通过")


@app.command("gen-template")
def gen_template(
    all_tables: bool = typer.Option(False, "--all", help="生成所有表模板"),
    table: Optional[str] = typer.Option(None, "--table", help="只生成指定表模板"),
    project_root: Optional[str] = typer.Option(None, "--root", help="项目根目录"),
) -> None:
    """根据 schema 生成 Excel 模板头部。"""
    _setup_logging()
    root = _root(project_root)
    try:
        messages = canonical_gen_template(
            root, table_filter=table, all_tables=all_tables
        )
    except ValueError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(1)
    for message in messages:
        typer.echo(message)


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
    root = _root(project_root)
    try:
        report = canonical_status(root)
    except (FileNotFoundError, ValueError) as e:
        # schema/配置级错误：友好报错，不丢 traceback
        _friendly_exit("[error]", e)
    if report["missing"]:
        typer.echo("缺失文件:")
        for name in report["missing"]:
            typer.echo(f"  [missing] {name}")
    if report["changed"]:
        typer.echo("数据变更（待导出）:")
        for name in report["changed"]:
            typer.echo(f"  [changed] {name}")
    if report["drifted"]:
        typer.echo("模板已过时（schema 修改后未重建）:")
        for name in report["drifted"]:
            typer.echo(
                f"  [template-stale] {name}  "
                f"(建议: ct gen-template --table {name})"
            )
    publication = canonical_publication_state(root)
    if publication:
        typer.echo("未完成的发布:")
        typer.echo(f"  [publication] {publication}")
    if (
        not report["missing"]
        and not report["changed"]
        and not report["drifted"]
        and not publication
    ):
        typer.echo("[OK] 所有表已是最新（数据 + 模板）")


@app.command()
def panel(
    project_root: Optional[str] = typer.Option(None, "--root", help="项目根目录"),
    host: str = typer.Option("127.0.0.1", "--host", help="监听地址"),
    port: int = typer.Option(8000, "--port", help="监听端口"),
    no_browser: bool = typer.Option(False, "--no-browser", help="启动时不自动打开浏览器"),
) -> None:
    """启动本地面板（浏览器打开即用）。"""
    _setup_logging()
    root = _root(project_root)
    _load_workspace(root)  # 配置/schema 错误立即以友好提示退出

    from ct.web.app import create_app

    app = create_app(root)
    if not no_browser:
        import threading
        import webbrowser

        threading.Timer(0.8, lambda: webbrowser.open(f"http://{host}:{port}")).start()

    typer.echo(f"面板已启动: http://{host}:{port}（Ctrl+C 停止）")
    app.run(host=host, port=port, debug=False, use_reloader=False, threaded=True)


# ---------------------------------------------------------------- ct i18n group

#: 进度条格数（`ct i18n status`）。
_I18N_BAR_WIDTH = 10


def _render_i18n_progress_line(label: str, counts: dict) -> str:
    """渲染一行进度：`[en]  89% [█████████░] 170/190 translated, 12 missing, ...`。

    分母取 `total - orphan`（orphan 是 source 已不存在的残留条目，不计入工作量）。
    """
    progress = float(counts.get("progress", 1.0))
    active = counts["total"] - counts["orphan"]
    filled = int(round(max(0.0, min(1.0, progress)) * _I18N_BAR_WIDTH))
    bar = "█" * filled + "░" * (_I18N_BAR_WIDTH - filled)
    return (
        f"{label}  {round(progress * 100)}% [{bar}] "
        f"{counts['translated']}/{active} translated, "
        f"{counts['missing']} missing, {counts['stale']} stale, "
        f"{counts['orphan']} orphan"
    )


def _fail(prefix: str, exc: BaseException) -> None:
    """友好失败：不打印 traceback，退出码 1（`--verbose` 时堆栈进日志）。

    与 `_friendly_exit` 同一条路径，只是前缀不同（i18n / compact 各自的命令名）。
    """
    _friendly_exit(prefix, exc)


@i18n_app.command("sync")
def i18n_sync(
    lang: Optional[str] = typer.Option(
        None, "--lang", help="只更新该语言的 lang 文件（source 仍全量刷新）"
    ),
    table: Optional[str] = typer.Option(None, "--table", help="只处理指定表"),
    project_root: Optional[str] = typer.Option(None, "--root", help="项目根目录"),
    verbose: bool = typer.Option(False, "--verbose", help="输出每个写入文件的路径与变更条目数"),
) -> None:
    """刷新 i18n source 文件并为每个 secondary 语言生成/更新 lang 骨架。"""
    _setup_logging(verbose)
    root = _root(project_root)
    try:
        messages = canonical_i18n_sync(
            root, table_filter=table, lang_filter=lang, verbose=verbose
        )
    except (FileNotFoundError, ValueError) as e:
        _fail("[i18n sync]", e)
    for message in messages:
        typer.echo(f"[i18n sync] {message}", err=True)


@i18n_app.command("status")
def i18n_status(
    lang: Optional[str] = typer.Option(None, "--lang", help="只显示指定语言"),
    by_table: bool = typer.Option(False, "--by-table", help="按表细分"),
    json_out: bool = typer.Option(False, "--json", help="输出 JSON"),
    project_root: Optional[str] = typer.Option(None, "--root", help="项目根目录"),
) -> None:
    """报告 i18n 翻译进度。"""
    _setup_logging()
    root = _root(project_root)
    try:
        report = canonical_i18n_status(root)
    except (FileNotFoundError, ValueError) as e:
        _fail("[i18n status]", e)
    if lang is not None and lang not in report:
        langs = ", ".join(sorted(report)) or "无"
        _fail("[i18n status]", f"语言 '{lang}' 不在 secondary_langs 中（可用: {langs}）")
    selected = {
        name: counts
        for name, counts in sorted(report.items())
        if lang is None or name == lang
    }
    if json_out:
        import json

        typer.echo(json.dumps({"langs": selected}, ensure_ascii=False, indent=2))
        return
    for lang_name, counts in selected.items():
        typer.echo(_render_i18n_progress_line(f"[{lang_name}]", counts))
        if by_table:
            for table_name, table_counts in sorted(counts["tables"].items()):
                typer.echo(_render_i18n_progress_line(f"  {table_name}", table_counts))


@i18n_app.command("compact")
def i18n_compact(
    lang: Optional[str] = typer.Option(None, "--lang", help="只处理指定语言"),
    table: Optional[str] = typer.Option(None, "--table", help="只处理指定表"),
    dry_run: bool = typer.Option(False, "--dry-run", help="仅打印将被删除的条目，不修改文件"),
    project_root: Optional[str] = typer.Option(None, "--root", help="项目根目录"),
) -> None:
    """物理移除 lang 文件中所有 status: orphan 的条目。"""
    _setup_logging()
    root = _root(project_root)
    try:
        result = canonical_i18n_compact(
            root, table_filter=table, lang_filter=lang, dry_run=dry_run
        )
    except (FileNotFoundError, ValueError) as e:
        _fail("[compact]", e)
    verb = "将移除" if dry_run else "移除"
    for item in result["files"]:
        keys = item["removed_keys"]
        typer.echo(
            f"[compact] {item['lang']}/{item['table']}: {verb} {len(keys)} 条 orphan"
        )
        if dry_run:
            typer.echo(f"  {'、'.join(keys)}")
    total = result["total_removed"]
    if not total:
        typer.echo("[compact] 无 orphan 条目，无需操作")
    elif dry_run:
        typer.echo(f"[compact] 共 {total} 条 orphan 待移除（dry-run，未修改任何文件）")
    else:
        typer.echo(f"[compact] 共 {total} 条 orphan 已移除")


if __name__ == "__main__":
    app()
