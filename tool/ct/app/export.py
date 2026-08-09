"""导出用例：把 cli.py 的导出编排提炼为步骤管道（拆分阶段 6.11）。

步骤序列与旧实现一一对应，日志文本逐字一致；CLI 只负责参数解析、
范围确定与结果渲染，管道负责执行与缓存提交。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from ct.app.events import CancelToken, CancelledError, ProgressReporter
from ct.app.options import ExportOptions
from ct.app.validate import parse_and_validate
from ct.app.workspace import Workspace
from ct.cache.state import (
    load_fbs_bytes,
    save_cache,
    save_fbs_bytes,
    update_table_cache,
)
from ct.excel.diff import file_hash
from ct.export.binary_writer import (
    build_i18n_table_bytes,
    build_table_bytes,
    write_i18n_bundle,
    write_primary_bundle,
)
from ct.export.csharp_accessor_generator import generate_csharp_accessor
from ct.export.fbs_generator import generate_container_fbs
from ct.export.i18n.merger import load_translation, merge_translations
from ct.export.i18n.sync import sync_all
from ct.export.json_writer import write_json
from ct.export.lua_accessor_generator import generate_lua_accessor
from ct.schema.models import TableSchema
from ct.validate.errors import Issue


class ExportValidationError(Exception):
    """解析/校验失败：携带现有字符串格式的错误列表，由展示层渲染。"""

    def __init__(self, issues: list[Issue]) -> None:
        super().__init__("导出前校验失败")
        self.issues = issues


@dataclass
class ExportContext:
    """步骤之间共享的中间状态（命令对象的字段，见 11.9）。"""

    ws: Workspace
    opts: ExportOptions
    reporter: ProgressReporter
    cancel: CancelToken
    cache: Any
    tables_to_export: list[str]
    parsed_data: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    id_sets: dict[str, set[Any]] = field(default_factory=dict)
    all_errors: list[Issue] = field(default_factory=list)
    all_table_bytes: dict[str, bytes] = field(default_factory=dict)
    all_i18n_bytes: dict[str, dict[str, bytes]] = field(default_factory=dict)
    bundles_written: list[Path] = field(default_factory=list)
    flatc_ok: bool = True
    exported_tables: list[str] = field(default_factory=list)

    @property
    def langs(self) -> list[str]:
        if self.opts.lang:
            return [self.opts.lang]
        return self.ws.config.all_langs

    @property
    def excel_dir(self) -> Path:
        return self.ws.resolve("excel_dir")

    @property
    def output_dir(self) -> Path:
        return self.ws.resolve("output_dir")

    @property
    def i18n_dir(self) -> Path:
        return self.ws.resolve("i18n_dir")

    @property
    def cache_dir(self) -> Path:
        return self.ws.resolve("cache_dir")


class ExportStep(Protocol):
    name: str

    def run(self, ctx: ExportContext) -> None: ...


class ParseValidateStep:
    name = "解析校验"

    def run(self, ctx: ExportContext) -> None:
        pv = parse_and_validate(
            ctx.ws,
            ctx.tables_to_export,
            ctx.cache,
            ctx.excel_dir,
            on_parse=lambda name: ctx.reporter.log(f"[parse] {name}"),
            on_missing=lambda name, path: ctx.reporter.log(
                f"[error] {path} 不存在，跳过 {name}", err=True
            ),
        )
        ctx.parsed_data = pv.parsed_data
        ctx.id_sets = pv.id_sets
        ctx.all_errors = pv.errors
        if ctx.all_errors:
            raise ExportValidationError(ctx.all_errors)


class I18nSyncStep:
    name = "i18n sync"

    def run(self, ctx: ExportContext) -> None:
        changed_i18n_schemas = [ctx.ws.schema_map[n] for n in ctx.parsed_data]
        summary = sync_all(ctx.ws.config, changed_i18n_schemas, ctx.parsed_data)
        if ctx.opts.verbose:
            totals = summary.totals_by_lang()
            if not totals:
                ctx.reporter.log("[i18n sync] 无 secondary 语言或无 i18n 表，跳过", err=True)
            else:
                parts = []
                for lang, counts in sorted(totals.items()):
                    parts.append(
                        f"{lang}: translated={counts.translated}, missing={counts.missing}, "
                        f"stale={counts.stale}, orphan={counts.orphan}"
                    )
                ctx.reporter.log("[i18n sync] " + "; ".join(parts), err=True)


class JsonStep:
    """JSON 导出 + FlatBuffers bytes 收集 + 缓存更新（含未变化表的复用）。"""

    name = "JSON"

    def run(self, ctx: ExportContext) -> None:
        for name in ctx.ws.order:
            ctx.cancel.raise_if_cancelled()
            schema = ctx.ws.schema_map[name]
            if name in ctx.parsed_data:
                self._export_changed_table(
                    ctx, name, schema, ctx.parsed_data[name], ctx.langs
                )
            else:
                self._reuse_unchanged_table(ctx, name, schema, ctx.langs)
            ctx.exported_tables.append(name)

    def _export_changed_table(
        self,
        ctx: ExportContext,
        name: str,
        schema: TableSchema,
        rows: list[dict[str, Any]],
        langs: list[str],
    ) -> None:
        """写 JSON → 构建并缓存主表/i18n bytes → 更新 cache。"""
        self._write_json(ctx, schema, rows, langs)
        self._build_and_cache_bytes(ctx, name, schema, rows, langs)
        self._update_cache(ctx, name, schema)

    def _reuse_unchanged_table(
        self,
        ctx: ExportContext,
        name: str,
        schema: TableSchema,
        langs: list[str],
    ) -> None:
        """未变化表：从 cache 复用 bytes。"""
        cached_bytes = load_fbs_bytes(ctx.cache_dir, name)
        if cached_bytes:
            ctx.all_table_bytes[name] = cached_bytes
            ctx.reporter.log(f"[skip] {name} (unchanged)")
        if schema.has_i18n:
            for l in langs:
                if l == ctx.ws.config.primary_lang:
                    continue
                cached_i18n = load_fbs_bytes(ctx.cache_dir, f"{name}_i18n_{l}")
                if cached_i18n:
                    ctx.all_i18n_bytes.setdefault(l, {})[f"{name}_i18n"] = cached_i18n

    def _write_json(
        self,
        ctx: ExportContext,
        schema: TableSchema,
        rows: list[dict[str, Any]],
        langs: list[str],
    ) -> None:
        """每种语言写一份 JSON。"""
        for l in langs:
            if l == ctx.ws.config.primary_lang:
                json_rows = rows
            else:
                translations = load_translation(ctx.i18n_dir, l, schema.table)
                json_rows = merge_translations(
                    rows, schema, l, translations, ctx.ws.config.primary_lang
                )
            path = write_json(json_rows, schema, l, ctx.output_dir)
            ctx.reporter.log(f"[json] {path.name}")

    def _build_and_cache_bytes(
        self,
        ctx: ExportContext,
        name: str,
        schema: TableSchema,
        rows: list[dict[str, Any]],
        langs: list[str],
    ) -> None:
        """构建主表 bytes（不含 server_only）与次语言 i18n bytes 并缓存。"""
        fbs_bytes = build_table_bytes(rows, schema, exclude_server_only=True)
        ctx.all_table_bytes[name] = fbs_bytes
        save_fbs_bytes(ctx.cache_dir, name, fbs_bytes)

        if schema.has_i18n:
            for l in langs:
                if l == ctx.ws.config.primary_lang:
                    continue
                translations = load_translation(ctx.i18n_dir, l, schema.table)
                merged = merge_translations(
                    rows, schema, l, translations, ctx.ws.config.primary_lang
                )
                i18n_bytes = build_i18n_table_bytes(merged, schema)
                ctx.all_i18n_bytes.setdefault(l, {})[f"{name}_i18n"] = i18n_bytes
                save_fbs_bytes(ctx.cache_dir, f"{name}_i18n_{l}", i18n_bytes)

    def _update_cache(self, ctx: ExportContext, name: str, schema: TableSchema) -> None:
        """记录本次导出的 Excel hash 与主键集合。"""
        xlsx_path = ctx.excel_dir / schema.resolved_excel_file
        h = file_hash(xlsx_path)
        update_table_cache(
            ctx.cache, name,
            hash=h,
            ids=sorted(ctx.id_sets.get(name, set())),
        )


class FbsStep:
    name = "FBS"

    def run(self, ctx: ExportContext) -> None:
        from ct.schema.repository import create_repository

        repository = create_repository(
            ctx.ws.resolve("schemas_dir"), ctx.ws.config.schema_format
        )
        sources = repository.fbs_sources(ctx.ws.schemas)
        fbs_dir = ctx.output_dir / "fbs"
        fbs_dir.mkdir(parents=True, exist_ok=True)

        for name in ctx.ws.order:
            ctx.cancel.raise_if_cancelled()
            entry = sources[name]
            main_path = fbs_dir / f"{name}.fbs"
            main_path.write_text(entry["main"], encoding="utf-8")
            ctx.reporter.log(f"[fbs] {main_path.name}")
            if entry["i18n"] is not None:
                i18n_path = fbs_dir / f"{name}_i18n.fbs"
                i18n_path.write_text(entry["i18n"], encoding="utf-8")
        generate_container_fbs(ctx.output_dir)
        ctx.reporter.log("[fbs] container.fbs")


class FlatcStep:
    name = "flatc"

    def run(self, ctx: ExportContext) -> None:
        flatc_path = ctx.ws.resolve("flatc_path")
        if flatc_path.exists():
            from ct.export.flatc_runner import compile_fbs
            fbs_dir = ctx.output_dir / "fbs"
            ctx.flatc_ok = compile_fbs(flatc_path, fbs_dir, ctx.output_dir)
        else:
            ctx.reporter.log(f"[warn] flatc 未找到 ({flatc_path})，跳过编译", err=True)
            ctx.flatc_ok = False


class AccessorStep:
    name = "Accessor"

    def run(self, ctx: ExportContext) -> None:
        for name in ctx.ws.order:
            ctx.cancel.raise_if_cancelled()
            schema = ctx.ws.schema_map[name]
            cs_path = generate_csharp_accessor(
                schema, ctx.output_dir / "generated" / "csharp"
            )
            ctx.reporter.log(f"[accessor] {cs_path.name}")
            lua_path = generate_lua_accessor(
                schema, ctx.output_dir / "generated" / "lua"
            )
            ctx.reporter.log(f"[accessor] {lua_path.name}")


class BundleStep:
    name = "Bundle"

    def run(self, ctx: ExportContext) -> None:
        ws = ctx.ws
        if ctx.all_table_bytes:
            path = write_primary_bundle(
                ctx.all_table_bytes, ws.config.primary_lang, ctx.output_dir
            )
            ctx.bundles_written.append(path)
            ctx.reporter.log(f"[bundle] {path.name}")
        for l in ctx.langs:
            if l != ws.config.primary_lang:
                path = write_i18n_bundle(ctx.all_i18n_bytes.get(l, {}), l, ctx.output_dir)
                if path:
                    ctx.bundles_written.append(path)
                    ctx.reporter.log(f"[bundle] {path.name}")


@dataclass
class ExportResult:
    tables_exported: int
    elapsed: float
    cancelled: bool = False
    flatc_ok: bool = True
    bundles_written: list[Path] = field(default_factory=list)


class ExportPipeline:
    """把导出用例串成步骤序列；取消时不写 state.json。"""

    def __init__(self, steps: list[ExportStep] | None = None) -> None:
        self.steps = steps or [
            ParseValidateStep(),
            I18nSyncStep(),
            JsonStep(),
            FbsStep(),
            FlatcStep(),
            AccessorStep(),
            BundleStep(),
        ]

    def run(
        self,
        ws: Workspace,
        opts: ExportOptions,
        cache: Any,
        tables_to_export: list[str],
        reporter: ProgressReporter,
        cancel: CancelToken,
    ) -> ExportResult:
        ctx = ExportContext(
            ws=ws,
            opts=opts,
            reporter=reporter,
            cancel=cancel,
            cache=cache,
            tables_to_export=tables_to_export,
        )
        started = time.perf_counter()
        try:
            for step in self.steps:
                cancel.raise_if_cancelled()
                reporter.step_started(step.name)
                step.run(ctx)
                reporter.step_finished(step.name)
        except ExportValidationError:
            raise
        except CancelledError:
            return ExportResult(
                tables_exported=len(ctx.exported_tables),
                elapsed=time.perf_counter() - started,
                cancelled=True,
            )

        # 全流程成功才提交缓存；被取消时保持旧 state.json
        save_cache(ctx.cache, ctx.cache_dir)
        return ExportResult(
            tables_exported=len(tables_to_export),
            elapsed=time.perf_counter() - started,
            flatc_ok=ctx.flatc_ok,
            bundles_written=ctx.bundles_written,
        )
