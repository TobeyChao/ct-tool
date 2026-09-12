"""导出五阶段构建内核：校验 → JSON/bytes → Accessor/manifest → FBS → Bundle → 本地发布。

这里是**唯一**的 pipeline 实现。``ct.app.canonical_export`` 保留为兼容层，
``ct.app.exporting.service`` 在其上叠加锁、发布恢复、完成策略与成功账本。

构建与正式写入分开：所有生成与结构检查产生 payload（``_Publication``），
只有全部通过后才在一个可恢复事务里改写正式输出与 layout manifest。
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Iterable

from ct.app.canonical_commands import CanonicalValidationError
from ct.app.canonical_workspace import CanonicalWorkspace
from ct.app.data_preparation import (
    enums_map,
    prepare_tables,
    records_map,
    select_tables,
)
from ct.app.exporting.models import ExportRequest, ExportResult, TableBuild
from ct.app.exporting.prepare import (
    capture_export_inputs,
    capture_manifest_contents,
    capture_sources,
    capture_translation_contents,
    read_excel_bytes,
    verify_inputs_unchanged,
)
from ct.cache.artifacts import ArtifactCache
from ct.cache.canonical_state import CanonicalCacheState, load_state, record_excel_hashes, save_state
from ct.cache.fingerprints import bundle_fingerprint
from ct.contracts import CancelToken, CancelledError, NullReporter, ProgressReporter
from ct.diagnostics.errors import Issue, IssueCode
from ct.excel.canonical_template import build_canonical_template
from ct.excel.layout import Layout
from ct.excel.layout_manifest import LayoutManifest, manifest_payload
from ct.export.canonical_accessor import (
    generate_csharp_accessor,
    generate_csharp_enums,
    generate_lua_accessor,
    generate_lua_enums,
)
from ct.export.canonical_accessor_model import build_accessor_model
from ct.export.canonical_binary import (
    build_canonical_bundle,
    build_canonical_table_bytes as _build_canonical_table_bytes,
    UniformLayoutError,
    count_vtables,
    probe_row_layout,
    written_slot_ratio,
)
from ct.export.canonical_fbs import (
    table_fbs_text,
    types_fbs_text,
    validate_canonical_fbs,
)
from ct.export.canonical_json import serialize_table_json
from ct.export.i18n.merger import load_translation
from ct.schema.resources import (
    EnumResource,
    RecordResource,
    SchemaResource,
    TableResource,
)
from ct.storage.publication import FilePublisher

CODEGEN_VERSION = "incremental/2-schema-layout"

CANONICAL_STEPS = ("解析校验", "JSON", "Accessor", "FBS", "Bundle")

# 定宽体积提示阈值：定宽字节 >= 常规的此倍数时，在填充率行追加提示。
# 取 1.25 的由来：旧的自动阈值（填充率 75%）当初就是按「该点体积膨胀 <=1.18x」选的，
# 所以超过 1.25x 即「比原先自动判定允许的更贵」，值得让作者知道并考虑 uniform: false。
UNIFORM_BLOAT_NOTICE = 1.25

#: 本次导出在 output/ 下使用的私有暂存目录名（相对 output_dir）。
#: 枚举陈旧产物时必须排除它，否则会把自身 staging 当旧产物删掉。
STAGING_SUBDIR = ".ct-staging"


class _Publication:
    """本次导出的待发布集合：先收集 payload，全部生成成功后才落盘。

    把「构建」与「正式写入」分开，是为了满足：任一生成阶段失败时正式 output
    与 layout manifest 的内容和 mtime 都不变。复用判定仍在 stage 时对着**尚未
    改写**的正式文件做，语义与原来的即时写入一致。
    """

    def __init__(self, *, forced: bool = False) -> None:
        self.forced = forced
        self.expected: set[Path] = set()
        self.payloads: dict[Path, bytes] = {}
        self.uncounted: set[Path] = set()
        #: 本次发布要删除的陈旧文件（仅全量导出计算）
        self.deletions: set[Path] = set()
        self.written: list[str] = []
        self.reused: list[str] = []

    def stale_in(
        self, roots: Iterable[Path], *, exclude: Iterable[Path] = ()
    ) -> set[Path]:
        """给定目录下、不在 ``expected`` 中的文件 = 陈旧产物。

        ``exclude`` 用于排除**本次自己的私有暂存目录**：枚举发生在暂存之后，
        不排除就会把自身 staging 当成旧产物删掉。
        """
        skipped = [Path(item) for item in exclude]
        stale: set[Path] = set()
        for root in roots:
            if not root.exists():
                continue
            for path in root.rglob("*"):
                if not path.is_file() or path in self.expected:
                    continue
                # 私有暂存文件（同目录 tempfile）也不能被当成旧产物
                if path.name.startswith(".ct-stage-"):
                    continue
                if any(path == item or item in path.parents for item in skipped):
                    continue
                stale.add(path)
        return stale

    def stage(self, path: Path, payload: str | bytes, *, count: bool = True) -> None:
        """登记一个待发布目标。

        ``count=False``：进入发布集合（``expected``/``payloads``）但不计入
        ``written``/``reused`` —— layout manifest 一直是这样的：它属于发布范围，
        但 ``written`` 只报 ``output/`` 下的产物（保持既有返回语义）。
        """
        data = payload.encode("utf-8") if isinstance(payload, str) else payload
        self.expected.add(path)
        if not self.forced and path.is_file() and path.read_bytes() == data:
            if count:
                self.reused.append(str(path))
            return
        self.payloads[path] = data
        if not count:
            self.uncounted.add(path)

    def commit(
        self, publisher: FilePublisher, deletions: Iterable[Path] = ()
    ) -> None:
        """一个事务里写出全部 payload 并删除陈旧产物。

        任一步失败由 ``FilePublisher`` 回滚到发布前状态，``written`` 不会被记账。
        """
        removals = set(deletions)
        publisher.publish(self.payloads, removals)
        self.deletions = removals
        for path in self.payloads:
            if path not in self.uncounted:
                self.written.append(str(path))


def _table_types(
    table: TableResource,
    records: dict[str, RecordResource],
    enums: dict[str, EnumResource],
) -> tuple[dict[str, RecordResource], dict[str, EnumResource]]:
    """Limit generator inputs to the table's transitive named dependencies."""
    used_records: dict[str, RecordResource] = {}
    used_enums: dict[str, EnumResource] = {}

    def visit(resource: TableResource | RecordResource) -> None:
        for field in resource.fields:
            name = _named_ref(field)
            if name in records and name not in used_records:
                used_records[name] = records[name]
                visit(records[name])
            elif name in enums:
                used_enums[name] = enums[name]

    visit(table)
    return used_records, used_enums


def build_canonical_table_bytes(rows, table, **kwargs) -> bytes:
    """Translate wire-layout failures into the CLI/Web validation contract."""
    try:
        return _build_canonical_table_bytes(rows, table, **kwargs)
    except UniformLayoutError as exc:
        raise CanonicalValidationError([
            Issue(table.table, IssueCode.TYPE, str(exc))
        ]) from exc


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
                Issue(
                    name,
                    IssueCode.TYPE,
                    f"{name}[{lang}]：uniform 布局下出现 {n_vt} 种 vtable（要求恰好 1 种）"
                    "——二进制布局未遵守 Schema 布局计划，请检查生成器或缓存产物",
                )
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


def run_pipeline(
    request: ExportRequest,
    *,
    reporter: ProgressReporter | None = None,
    cancel_token: CancelToken | None = None,
) -> ExportResult:
    """五阶段导出内核：校验 → JSON/bytes → Accessor/manifest → FBS → Bundle → 发布。

    **不抢锁、不做发布恢复、不部署、不写成功账本** —— 那些是应用用例
    （``ct.app.exporting.service``）的职责。这里只把「输入快照 → 本地发布」做完，
    因此可以被兼容入口与完整用例复用而不会形成第二套 pipeline。
    ``cancel_token`` 只在准备/构建阶段检查，进入发布事务后被延后。
    """
    started = time.perf_counter()
    reporter = reporter or NullReporter()
    # 配置与 schema/types 从**捕获内容**解析（不 glob、不读盘）
    config, source_contents = capture_sources(request.root)
    workspace = CanonicalWorkspace.load(
        request.root, contents=source_contents, config=config
    )
    config = workspace.config
    records = records_map(workspace)
    enums = enums_map(workspace)

    output_dir = config.resolve("output_dir")
    excel_dir = config.resolve("excel_dir")
    i18n_dir = config.resolve("i18n_dir")
    cache_dir = config.resolve("cache_dir")
    generated = output_dir / "generated"
    languages = [
        lang
        for lang in config.all_langs
        if request.lang_filter is None or lang == request.lang_filter
    ]
    if request.lang_filter is not None and not languages:
        raise ValueError(
            f"语言 '{request.lang_filter}' 不在可导出语言中"
            f"（可用: {', '.join(config.all_langs)}）"
        )

    # ---- 输入捕获：源 Excel 只读一次，之后 reader 与账本共用同一批字节 ----
    selected = select_tables(workspace, request.table_filter)
    if request.table_filter is not None and not selected:
        raise ValueError(f"表 '{request.table_filter}' 不存在")
    excel_bytes = read_excel_bytes(workspace, selected)
    # 译文与旧 manifest 同样先捕获，生成阶段只消费捕获到的字节
    i18n_contents = capture_translation_contents(
        workspace,
        tables=selected,
        languages=languages,
        primary_lang=config.primary_lang,
    )
    manifest_contents = capture_manifest_contents(workspace, tables=selected)
    before_inputs = capture_export_inputs(
        workspace,
        tables=selected,
        languages=languages,
        primary_lang=config.primary_lang,
    )
    verify_inputs_unchanged(
        before_inputs,
        capture_export_inputs(
            workspace,
            tables=selected,
            languages=languages,
            primary_lang=config.primary_lang,
        ),
        when="捕获期间",
    )

    # 每张表的构建结果：定宽决策、偏移常量与各语言字节
    # （阶段 2 产生，阶段 3 生成 accessor/manifest，阶段 5 组装 Bundle）
    builds: dict[str, TableBuild] = {}
    bundle_hashes: dict[str, str] = {}

    # ---- 阶段 1：解析校验（所有表；走 validate 共用的 preparation 内核） ----
    reporter.step_started(CANONICAL_STEPS[0])
    try:
        result = prepare_tables(
            workspace,
            table_filter=request.table_filter,
            # 逐表取消检查与进度日志由内核回调驱动，保持与原循环一致的交错顺序
            before_table=lambda _table: _check_cancel(cancel_token),
            after_table=lambda table, parsed: reporter.log(
                f"解析 {table.table}（{len(parsed.rows)} 行）"
            ),
            excel_bytes=excel_bytes,
        )
        if result.unknown_table is not None:
            raise ValueError(f"表 '{result.unknown_table}' 不存在")
        # 缺 Excel：导出入口保持原行为 —— 读取阶段直接失败，不产出模板
        if result.missing_excel:
            raise FileNotFoundError(f"Excel 文件不存在: {result.missing_excel[0]}")
        if result.issues:
            raise CanonicalValidationError(result.issues)
        tables = list(result.selected)
        prepared: list[tuple[TableResource, Layout, Path, Any]] = [
            (item.table, item.layout, item.excel_path, item.parsed)
            for item in result.prepared
        ]
    finally:
        reporter.step_finished(CANONICAL_STEPS[0])

    cache = ArtifactCache(cache_dir, version=CODEGEN_VERSION, forced=request.forced)
    publication = _Publication(forced=request.forced)

    def emit(path: Path, payload: str | bytes, *, count: bool = True) -> None:
        publication.stage(path, payload, count=count)

    # ---- 阶段 2：JSON + 各语言 bytes ----
    types_path = output_dir / "fbs" / "types.fbs"
    reporter.step_started(CANONICAL_STEPS[1])
    try:
        for table, _layout, _excel_path, parsed in prepared:
            _check_cancel(cancel_token)
            table_records, table_enums = _table_types(table, records, enums)
            base_rows = parsed.rows
            build = TableBuild(
                table=table.table, uniform=table.uniform, fill_rate=0.0, bytes_normal=0
            )
            builds[table.table] = build

            # 定宽由 schema 声明（缺省 true），**不按填充率判定**。填充率仍用
            # **非 uniform** 字节统计出来（不复刻写入规则），但只作为诊断数字，
            # 以及定宽体积提示的依据。
            client_count = len([f for f in table.fields if not f.server_only])
            probe = cache.call(
                "build_canonical_table_bytes", build_canonical_table_bytes,
                base_rows, table, records=table_records, enums=table_enums
            )
            build.bytes_normal = len(probe)
            build.fill_rate = written_slot_ratio(probe, client_count)
            use_uniform = table.uniform
            if use_uniform:
                build.slot_offsets = probe_row_layout(
                    table, records=table_records, enums=table_enums
                )

            # ---- 主语言：主表全量（含原文），随 data_{primary}.bin 一起加载 ----
            primary_rows = _merge_i18n(
                base_rows,
                table,
                load_translation(
                    i18n_dir,
                    config.primary_lang,
                    table.table,
                    data=i18n_contents.get(
                        i18n_dir / config.primary_lang / f"{table.table}.json"
                    ),
                )
            )
            primary_json = output_dir / "json" / f"{table.table}_{config.primary_lang}.json"
            emit(primary_json, cache.call("json", serialize_table_json, primary_rows, table))
            if config.primary_lang in languages:
                data = probe if not use_uniform and primary_rows == base_rows else cache.call(
                    "build_canonical_table_bytes", build_canonical_table_bytes,
                    primary_rows, table, records=table_records, enums=table_enums, uniform=use_uniform
                )
                if use_uniform:
                    _assert_single_vtable(table.table, config.primary_lang, data, len(primary_rows))
                    build.bytes_uniform = len(data)
                build.primary_bytes[config.primary_lang] = data

            # ---- 次级语言：JSON 仍是「全量行」（可 diff 评审），
            #      bin 走**稀疏 i18n 表**（只含主键 + i18n 字段，行序与主表一致）----
            i18n_table = _i18n_table(table)
            # i18n 表沿用主表的定宽决策；但它的 slot→offset 是**自己**的表级常量
            if i18n_table is not None and use_uniform:
                build.i18n_slot_offsets = probe_row_layout(
                    i18n_table, records=table_records, enums=table_enums
                )
            for lang in languages:
                if lang == config.primary_lang:
                    continue
                merged = _merge_i18n(
                    base_rows,
                    table,
                    load_translation(
                        i18n_dir,
                        lang,
                        table.table,
                        data=i18n_contents.get(i18n_dir / lang / f"{table.table}.json"),
                    )
                )
                lang_json = output_dir / "json" / f"{table.table}_{lang}.json"
                emit(lang_json, cache.call("json", serialize_table_json, merged, table))
                if i18n_table is None:
                    continue
                i18n_rows = _i18n_rows(table, i18n_table, merged)
                if len(i18n_rows) != len(primary_rows):
                    raise CanonicalValidationError(
                        [
                            Issue(
                                f"{table.table}_i18n",
                                IssueCode.TYPE,
                                f"{table.table}_i18n[{lang}]：{len(i18n_rows)} 行 ≠ 主表 "
                                f"{len(primary_rows)} 行 —— i18n 表与主表必须同序等长",
                            )
                        ]
                    )
                i18n_data = cache.call(
                    "build_canonical_table_bytes", build_canonical_table_bytes,
                    i18n_rows, i18n_table, records=table_records, enums=table_enums, uniform=use_uniform
                )
                if use_uniform:
                    _assert_single_vtable(f"{table.table}_i18n", lang, i18n_data, len(i18n_rows))
                build.i18n_bytes[lang] = i18n_data

            # 布局形态在前、填充率在后：填充率只是诊断数字（决策取自 schema 的
            # uniform 声明），写成「填充率 X% → 定宽」会被读成旧的数据派生规则。
            detail = (
                f"{'定宽' if use_uniform else '变长'}（schema 声明）"
                f"｜填充率 {build.fill_rate:.1%}"
            )
            if use_uniform:
                # bytes_uniform 只在主语言被纳入本次导出时才有（--lang 次级语言时
                # 主语言分支不产出字节），日志只报已计算的部分。
                detail += f"（{build.bytes_normal:,} B"
                if build.bytes_uniform is not None:
                    ratio = build.bytes_uniform / build.bytes_normal
                    detail += f" → {build.bytes_uniform:,} B，{ratio:.3f}x"
                    if ratio > UNIFORM_BLOAT_NOTICE:
                        # 定宽是 schema 声明（缺省开），稀疏表会因「所有槽位无条件写出」
                        # 而变大；把账显式交给作者，不阻断导出。
                        detail += (
                            f" ⚠ 定宽比变长大 {ratio:.2f}x，"
                            f"该表可在 schema 声明 uniform: false 退回变长布局"
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
            build = builds[table.table]
            sparse_i18n = _i18n_table(table)
            # 稀疏 i18n 表**不再**单独产出 accessor：它的唯一消费者是主表的字段 getter，
            # 读路径已经内联进主 accessor（`_emit_csharp_i18n_support`）。
            # 但它**自己的**定宽偏移仍要交给生成器 —— 那是另一份表级常量。
            table_records, _ = _table_types(table, records, enums)
            model = build_accessor_model(
                table,
                # 表级查询索引（CodeName）：来自 schema（原先硬编码成 () ⇒ 永不生成 ByCodeName）
                tuple(table.indexes),
                records=table_records,
                # 定宽表：偏移是表级常量，生成器发射字面量（无偏移表）
                uniform_offsets=(build.slot_offsets or None) if build.uniform else None,
                # 多语言字段按行下标去稀疏 i18n 表读当前语言
                i18n_table=sparse_i18n.table if sparse_i18n is not None else None,
                i18n_uniform_offsets=(build.i18n_slot_offsets or None)
                if build.uniform
                else None,
            )
            csharp_path = generated / "csharp" / f"{table.table}Accessor.cs"
            lua_path = generated / "lua" / f"{table.table}Accessor.lua"
            emit(csharp_path, cache.call("generate_csharp_accessor", generate_csharp_accessor, model))
            emit(lua_path, cache.call("generate_lua_accessor", generate_lua_accessor, model))

            if not excel_path.exists():
                # 缺失模板分支：产物同样纳入发布集合，不在 build 阶段直接写源目录
                emit(
                    excel_path,
                    build_canonical_template(
                        layout, enums=enums, primary=table.primary
                    ),
                )
            manifest_dir = excel_dir / "layout_manifests"
            manifest_path = manifest_dir / f"{table.table}.json"
            candidate_manifest = LayoutManifest.from_layout(
                layout,
                # 定宽表的表级 slot→offset 常量，供生成器与评审读取
                layout_info=build.to_layout_info(),
            )
            # 用**规范序列化逐字节比较**，而不是解析后比语义：
            # manifest 是生成物，其规范形式是已知的。按语义比会漏掉「磁盘上多了
            # 已废弃的键」——那些键在 parse 时被忽略，于是旧文件永远不会被清理。
            payload = manifest_payload(candidate_manifest)
            captured = manifest_contents.get(manifest_path)
            current = captured.decode("utf-8", errors="replace") if captured is not None else None
            if request.forced or current != payload:
                emit(manifest_path, payload, count=False)

        # 枚举类型声明：生成物里的 (Enum)WireReader.I8At(...) cast 需要它才能编译
        if enums:
            enum_cs = generated / "csharp" / "Enums.cs"
            enum_lua = generated / "lua" / "Enums.lua"
            emit(enum_cs, cache.call("generate_csharp_enums", generate_csharp_enums, enums))
            emit(enum_lua, cache.call("generate_lua_enums", generate_lua_enums, enums))
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
        types_text = cache.call("types_fbs_text", types_fbs_text, order, resources_map)
        emit(types_path, types_text)
        table_fbs = {table.table: cache.call("table_fbs_text", table_fbs_text, table) for table, *_ in prepared}
        validate_canonical_fbs(types_text, table_fbs, list(workspace.resources.resources))

        for table_name, text in table_fbs.items():
            path = output_dir / "fbs" / f"{table_name}.fbs"
            emit(path, text)

        container = output_dir / "fbs" / "container.fbs"
        emit(container,
            "table BundledTable {\n  name: string;\n  data: [ubyte];\n}\n"
            "table DataBundle {\n  tables: [BundledTable];\n}\n\nroot_type DataBundle;\n",
        )
    finally:
        reporter.step_finished(CANONICAL_STEPS[3])

    # ---- 阶段 5：Binary Bundle ----
    reporter.step_started(CANONICAL_STEPS[4])
    try:
        bundle_dir = output_dir / "binary"
        for lang in languages:
            _check_cancel(cancel_token)
            if lang == config.primary_lang:
                # 主语言包 = 主表（全量字段）
                name_to_bytes = {
                    name: table_build.primary_bytes[lang]
                    for name, table_build in builds.items()
                    if lang in table_build.primary_bytes
                }
            else:
                # 次级语言包 = **稀疏 i18n 表**（ItemType_i18n / Item_i18n / ...）
                name_to_bytes = {
                    f"{name}_i18n": table_build.i18n_bytes[lang]
                    for name, table_build in builds.items()
                    if lang in table_build.i18n_bytes
                }
            bundle = cache.call("build_canonical_bundle", build_canonical_bundle, name_to_bytes)
            bundle_path = bundle_dir / f"data_{lang}.bin"
            emit(bundle_path, bundle)
            bundle_hashes[lang] = bundle_fingerprint(
                lang,
                [(name, _sha(data)) for name, data in name_to_bytes.items()],
            )
    finally:
        reporter.step_finished(CANONICAL_STEPS[4])

    # 发布前复核：全部生成完成、清理与记账之前，再确认这期间输入未变
    verify_inputs_unchanged(
        before_inputs,
        capture_export_inputs(
            workspace,
            tables=selected,
            languages=languages,
            primary_lang=config.primary_lang,
        ),
        when="生成期间",
    )

    # ---- 发布：一个事务里完成替换与删除，全部生成与结构检查成功后才开始 ----
    if request.table_filter is None and request.lang_filter is None:
        # 显式计算删除集合；枚举时排除本次私有暂存，避免把自身 staging 当旧产物
        publication.deletions = publication.stale_in(
            (output_dir / section for section in ("fbs", "generated", "json", "binary")),
            exclude=(output_dir / STAGING_SUBDIR,),
        )

    publication.commit(FilePublisher(request.root), publication.deletions)

    if request.table_filter is None and request.lang_filter is None:
        for path in sorted(publication.deletions):
            reporter.log(f"清理陈旧产物 {path.relative_to(output_dir)}")
        cache.prune()
    mode = "强制重建" if request.forced else "增量导出"
    reporter.log(
        f"{mode}：写入 {len(publication.written)}，复用 {len(publication.reused)}；"
        f"生成缓存命中 {cache.hits}"
    )

    # 账本 hash 来自**捕获并实际解析**的字节，不再重读磁盘：否则生成期间被改动的
    # 源文件会被错误地记为「已导出」，status 也就看不到这次变化。
    excel_hashes = {
        table.table: _sha(excel_bytes[excel_path])
        for table, _layout, excel_path, _parsed in prepared
    }

    return ExportResult(
        tables=len(tables),
        languages=languages,
        written=publication.written,
        reused=publication.reused,
        cache_hits=cache.hits,
        cache_misses=cache.misses,
        bundle_hashes=bundle_hashes,
        excel_hashes=excel_hashes,
        forced=request.forced,
        elapsed=round(time.perf_counter() - started, 2),
    )


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
