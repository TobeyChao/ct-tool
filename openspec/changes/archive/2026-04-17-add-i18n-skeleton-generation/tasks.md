## 1. 准备与清理

- [x] 1.1 删除 `gd/i18n/strings_en.json`（占位旧文件，开发期不迁移）
- [x] 1.2 在 `ct-tool/tests/i18n/` 下建立测试目录
- [x] 1.3 阅读 `ct/export/i18n/extractor.py`、`merger.py`、`writer.py` 确认重写边界

## 2. 紧凑 JSON 写出工具

- [x] 2.1 新建 `ct/cli_helpers/i18n_json.py`，实现 `dump_lang_file(data: dict, path: Path)` 和 `dump_source_file(data: dict, path: Path)`
- [x] 2.2 实现 key 排序：先按 id 数值升序，再按 schema 字段顺序（字段顺序参数显式传入，避免依赖全局）
- [x] 2.3 自定义序列化：外层手写 `{`/`}`/`,`，每条 entry 用 `json.dumps(value, ensure_ascii=False, separators=(", ", ": "))`
- [x] 2.4 写入后立即 `json.loads` 自检，断言往返等价
- [x] 2.5 `tests/i18n/test_compact_json.py`：覆盖空 dict、Unicode 字符（中文、emoji）、嵌套对象、数值 vs 字符串 id 排序、写后 loads 等价

## 3. Source 文件重构（按表拆分 + 扁平结构）

- [x] 3.1 在 `ct/export/i18n/extractor.py` 新增 `extract_source_for_table(rows, schema) -> dict[str, str]`，返回 `{"id.field": "text"}`
- [x] 3.2 移除旧的 `extract_i18n_strings` / `load_source_strings` / `save_source_strings`（已不兼容），或保留为 `_legacy_*` 内部函数仅供过渡测试
- [x] 3.3 新增 `load_source_file(i18n_dir, table) -> dict[str, str]` 和 `save_source_file(i18n_dir, table, data)`（后者复用 step 2 的 writer）
- [x] 3.4 `tests/i18n/test_extractor.py`：覆盖新增/修改/删除行后输出的扁平结构，验证 key 排序
- [x] 3.5 `tests/i18n/test_extractor.py`：表无 i18n 字段时不生成文件

## 4. Lang 文件结构与状态机

- [x] 4.1 在 `ct/export/i18n/` 新建 `state.py`，定义状态枚举 `LangStatus`（missing/translated/stale/orphan）
- [x] 4.2 实现 `compute_status(text: str, confirmed: bool, in_source: bool) -> LangStatus`
- [x] 4.3 实现 `merge_lang_entry(current_source: str | None, lang_entry: dict | None) -> dict`：返回更新后的 entry，应用 D2 字段更新规则
- [x] 4.4 实现 `sync_lang_table(source: dict[str, str], lang_existing: dict, schema_field_order: list[str]) -> dict`：对每个 key 调 `merge_lang_entry`，含遗留 orphan 处理
- [x] 4.5 `tests/i18n/test_state.py`：穷举状态转移表（5 行）
- [x] 4.6 `tests/i18n/test_state.py`：验证 source 改动时 confirmed 重置、text 保留
- [x] 4.7 `tests/i18n/test_state.py`：验证翻译者把 confirmed 改 true 后 status 转 translated

## 5. Sync 编排

- [x] 5.1 新建 `ct/export/i18n/sync.py`，实现 `sync_all(cfg, schemas, rows_by_table, *, lang_filter=None, table_filter=None) -> SyncSummary`
- [x] 5.2 流程：对每张含 i18n 的表 → 写 source 文件；然后对每个 secondary_lang × 每张 i18n 表 → 读取/创建 lang 文件 → 调 sync_lang_table → 写回
- [x] 5.3 定义 `SyncSummary` dataclass：含每语言每表的 (created, updated, stale, orphan, missing) 计数和耗时
- [x] 5.4 `lang_filter` 仅限定 lang 文件处理范围；source 文件始终全量刷新（避免 source 半新半旧）
- [x] 5.5 `tests/i18n/test_sync.py`：首次 sync 创建所有目录与文件
- [x] 5.6 `tests/i18n/test_sync.py`：幂等性 — 同样输入运行两次结果完全一致
- [x] 5.7 `tests/i18n/test_sync.py`：lang_filter 与 table_filter 的范围限定

## 6. Merger 适配新 lang 格式

- [x] 6.1 改写 `ct/export/i18n/merger.py` 的 `load_translation`：按表读取 `i18n/{lang}/{table}.json`
- [x] 6.2 改写 `merge_translations`：仅当 `text` 非空且 `confirmed=true` 时使用译文，否则回退主语言并 warning（warning 内容包含 status 类型）
- [x] 6.3 `tests/i18n/test_merger.py`：translated/stale/missing/lang 文件不存在四种回退路径
- [x] 6.4 `tests/i18n/test_merger.py`：confirmed=false 不被采用，输出 stale warning

## 7. 状态报告与汇总

- [x] 7.1 新建 `ct/export/i18n/status.py`，实现 `compute_status_report(cfg, schemas) -> StatusReport`
- [x] 7.2 `StatusReport` 含 per-language 与 per-(language, table) 的计数与百分比
- [x] 7.3 实现三种渲染：`render_default`（每语言一行 + ASCII 进度条）、`render_by_table`、`render_json`
- [x] 7.4 重写 `ct/export/i18n/writer.py` 的 `report_stale_summary`：基于 lang 文件聚合（不再依赖 source.status），输出 stale/missing/orphan 计数
- [x] 7.5 `tests/i18n/test_status.py`：覆盖三种渲染模式与 lang 过滤

## 8. CLI 集成

- [x] 8.1 在 `ct/cli.py` 新增 `i18n_app = typer.Typer(help="i18n 翻译骨架与状态管理")` 并 `app.add_typer(i18n_app, name="i18n")`
- [x] 8.2 实现 `ct i18n sync`：参数 `--lang/--table/--root/--verbose`，调 `sync_all` 并打印 summary
- [x] 8.3 实现 `ct i18n status`：参数 `--lang/--by-table/--json/--root`，调 `compute_status_report` 与对应 renderer
- [x] 8.4 实现 `ct i18n compact`：参数 `--lang/--table/--root/--dry-run`；遍历 lang 文件移除 orphan 条目，dry-run 仅打印
- [x] 8.5 修改 `ct export` 主流程：在校验通过后、每语言导出前调用 `sync_all`，verbose 时打印 summary
- [x] 8.6 移除/调整旧的 source 文件加载调用（`load_source_strings` 等）
- [x] 8.7 `tests/cli/test_i18n_subcommands.py`：sync/status/compact 三命令的端到端测试（用 CliRunner + tmp_path 构建 minimal 项目）
- [x] 8.8 `tests/cli/test_export_with_sync.py`：export 自动触发 sync，新增行后 lang 文件出现 missing 条目

## 9. 文档与回归

- [x] 9.1 更新 `CLAUDE.md`：新增 `ct i18n sync/status/compact` 子命令说明，更新 i18n 章节描述新文件结构与状态机
- [x] 9.2 在 `gd/` 工作空间运行 `ct i18n sync` 重新生成新结构（含 en），验证文件落地正确
- [x] 9.3 运行 `ct export --verbose` 完整链路：sync → 校验 → 导出，确认 JSON/Binary 产物中合并行为正确
- [x] 9.4 运行 `ct i18n status` 与 `ct i18n status --by-table --json`，验证渲染与 JSON 结构
- [x] 9.5 在 lang 文件手动制造 orphan，运行 `ct i18n compact --dry-run` 与正式执行，验证移除生效
- [x] 9.6 全量 `python -m pytest` 通过

## 10. 提交准备

- [x] 10.1 在变更目录运行 `openspec validate add-i18n-skeleton-generation --strict` 通过
- [x] 10.2 检查 `ct status` 输出无意外漂移
- [x] 10.3 自审：proposal/design/specs/tasks 一致，code 与 spec 描述一致
