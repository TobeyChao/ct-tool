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
    canonical_status,
    canonical_validate,
)
from ct.app.canonical_export import run_canonical_export
from ct.app.canonical_workspace import CanonicalWorkspace
from ct.config import load_config
from ct.diagnostics.errors import report_errors
from ct.export.deploy import deploy

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


def _load_workspace(root: Path) -> CanonicalWorkspace:
    """加载 canonical workspace；配置/schema 错误转为友好提示（不抛 traceback）。"""
    try:
        return CanonicalWorkspace.load(root)
    except (FileNotFoundError, ValueError) as e:
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("加载 workspace 失败", exc_info=True)
        typer.echo(f"[error] {e}", err=True)
        raise typer.Exit(1)


def _run_deploy(root: Path, for_build: bool) -> None:
    """执行部署并渲染结果；失败以友好提示退出。"""
    try:
        config = load_config(root)
        n = deploy(config, for_build, CLIProgressReporter())
    except (FileNotFoundError, OSError) as e:
        typer.echo(f"[deploy error] {e}", err=True)
        raise typer.Exit(1)
    if n:
        typer.echo(f"[deploy] 完成：{n} 个文件已同步")
    else:
        typer.echo("[deploy] 无文件变更")


@app.command()
def export(
    all_tables: bool = typer.Option(False, "--all", help="强制全量导出"),
    table: Optional[str] = typer.Option(None, "--table", help="只导出指定表"),
    lang: Optional[str] = typer.Option(None, "--lang", help="只导出指定语言"),
    verbose: bool = typer.Option(False, "--verbose", help="显示详细日志"),
    for_build: bool = typer.Option(False, "--for-build", help="部署时追加构建目标"),
    project_root: Optional[str] = typer.Option(None, "--root", help="项目根目录"),
) -> None:
    """增量导出主流程（canonical ）。"""
    _setup_logging(verbose)
    root = _root(project_root)
    try:
        result = run_canonical_export(
            root,
            table_filter=table,
            lang_filter=lang,
            forced=all_tables,
            reporter=CLIProgressReporter(),
        )
    except CanonicalValidationError as e:
        report_errors(e.issues, verbose)
        raise typer.Exit(1)
    except (FileNotFoundError, ValueError) as e:
        typer.echo(f"[export error] {e}", err=True)
        raise typer.Exit(1)
    typer.echo(f"\n导出完成: {result['tables']} 张表")
    _run_deploy(root, for_build)


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
    errors = canonical_validate(root, table_filter=table)
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
    report = canonical_status(root)
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
    if not report["missing"] and not report["changed"] and not report["drifted"]:
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


@i18n_app.command("sync")
def i18n_sync(
    lang: Optional[str] = typer.Option(None, "--lang", help="只处理指定语言的 lang 文件"),
    table: Optional[str] = typer.Option(None, "--table", help="只处理指定表"),
    project_root: Optional[str] = typer.Option(None, "--root", help="项目根目录"),
    verbose: bool = typer.Option(False, "--verbose", help="显示详细日志"),
) -> None:
    """刷新 i18n source 文件并为每个 secondary 语言生成/更新 lang 骨架。"""
    _setup_logging(verbose)
    root = _root(project_root)
    messages = canonical_i18n_sync(root, table_filter=table)
    for message in messages:
        typer.echo(f"[i18n sync] {message}", err=True)
    typer.echo("[i18n sync] 完成", err=True)


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
    report = canonical_i18n_status(root)
    if json_out:
        import json

        sys.stdout.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        return
    for lang_name, counts in sorted(report.items()):
        if lang is not None and lang_name != lang:
            continue
        typer.echo(
            f"{lang_name}: translated={counts['translated']}, "
            f"missing={counts['missing']}, stale={counts['stale']}, "
            f"orphan={counts['orphan']}"
        )


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
    removed = canonical_i18n_compact(root, table_filter=table)
    if not removed:
        typer.echo("[compact] 无 orphan 条目，无需操作")
    else:
        typer.echo(f"[compact] 总计移除 {removed} 条")


if __name__ == "__main__":
    app()
