## Purpose

提供 `ct` 命令行接口，用统一的子命令（export/validate/status/gen-template/i18n/deploy）驱动 canonical 导出、校验与 i18n 工作流，供脚本与 CI 调用。

## Requirements

### Requirement: ct export command
`ct export` SHALL 全量重跑 canonical 导出管道，步骤序列即 `CANONICAL_STEPS`：`解析校验 → JSON → Accessor → FBS → Bundle`（`ct/app/canonical_export.py`）。管道内**无 i18n sync、无 flatc 调用、无 deploy stage**；`ct export` 不调用 `canonical_i18n_sync`，因此不写 `i18n/source/`（只有 `ct i18n sync` 会写）。

管道没有任何复用路径：每次都是全量重建，不读 `cache/state.json`。`--all` 只是把 `forced=True` 记录进返回值，不是「强制全量」开关（导出本就全量）。缓存（`excel_hashes` / `bundles`）只供 `ct status` 报告变更，不跳过导出工作。

部署不在步骤序列内：CLI 在管道成功后打印 `导出完成: N 张表`，随后调用 `ct/export/deploy.py` 的 `deploy()` 把产物同步到 Unity Assets（`[deploy] 完成：N 个文件已同步` / `[deploy] 无文件变更`），最后才调用 `persist_export_state` 提交缓存指纹。

#### Scenario: Default full export
- **WHEN** 用户执行 `ct export`
- **THEN** 全部表 × 全部语言重新解析并重写 JSON / FBS / Accessor / Bundle，依次输出 `导出完成: N 张表` 与 deploy 结果；不出现 `[skip]` 式跳过提示，`cache/state.json` 中的历史 hash 不影响本次导出范围

#### Scenario: Export specific table
- **WHEN** 用户执行 `ct export --table Item`
- **THEN** 只处理表名**精确等于** `Item` 的表（`table.table == table_filter`）；`--table` 只接受单个值，不接受逗号列表，表名须为 PascalCase（`item` 会被 schema 校验拒绝）

#### Scenario: Export with specific language
- **WHEN** 用户执行 `ct export --lang en`
- **THEN** 只导出 `en` 一种语言的产物（`lang == lang_filter`，单个精确值，不接受逗号列表）

#### Scenario: Validation failure aborts the whole export
- **WHEN** 任一张表校验失败（类型、主键、CodeName 闸门或跨表 ref）
- **THEN** 整个导出中止，任何表都不生成产物，`output/` 保持上一次成功导出的内容，退出码非 0

#### Scenario: Verbose export shows debug log
- **WHEN** 执行 `ct export --verbose`
- **THEN** 日志级别降为 DEBUG（`_setup_logging`），不输出任何 i18n sync 汇总（导出不触发 sync）

### Requirement: ct i18n subcommand group
CLI SHALL 提供 `ct i18n` 子命令组，承载所有翻译骨架与状态管理操作。子命令组下 SHALL 包含 `sync`、`status`、`compact` 三个子命令。

所有子命令 SHALL 支持 `--root <dir>` 选项，用法与现有顶层命令一致。

#### Scenario: Help lists subcommands
- **WHEN** 用户执行 `ct i18n --help`
- **THEN** 输出列出 `sync`、`status`、`compact` 三个子命令及简短描述

#### Scenario: Unknown subcommand fails clearly
- **WHEN** 用户执行 `ct i18n foo`
- **THEN** 命令以非零退出码失败，输出可用子命令列表

### Requirement: ct i18n sync command
`ct i18n sync` SHALL 刷新主语言 source 文件并为每个 secondary_lang 生成或更新 lang 骨架。

命令 SHALL 支持下列选项：
- `--lang <lang>`：限定一个语言（其他 lang 文件不变，但 source 仍全量刷新）
- `--table <table>`：限定一张表（其他表的 source/lang 文件不变）
- `--verbose`：输出每个写入文件的路径及变更条目数

完成时 SHALL 输出汇总，例如 `[i18n sync] 处理 3 张表 × 2 语言：新增 5、更新 12、stale 3、orphan 2`。

#### Scenario: Sync creates lang directory and files
- **WHEN** secondary_langs 含 `en`，`i18n/en/` 不存在，执行 `ct i18n sync`
- **THEN** 工具创建 `i18n/en/` 目录及该目录下每张含 i18n 表的 lang 文件

#### Scenario: Sync filters by lang
- **WHEN** 执行 `ct i18n sync --lang en`，secondary_langs=[en, ja]
- **THEN** `i18n/en/` 下文件被更新，`i18n/ja/` 下文件保持不变

#### Scenario: Sync filters by table
- **WHEN** 执行 `ct i18n sync --table Item`
- **THEN** `i18n/source/Item.json` 与每语言的 `Item.json` 被处理，其他表的文件不动

#### Scenario: Sync output summary
- **WHEN** sync 处理完所有文件
- **THEN** stderr 输出统计行（新增/更新/stale/orphan 总数）

### Requirement: ct i18n status command
`ct i18n status` SHALL 报告每语言（或每语言每表）的翻译进度。

命令 SHALL 支持下列选项：
- `--lang <lang>`：只显示一个语言
- `--by-table`：每语言每表一行
- `--json`：输出机器可读 JSON
- `--root <dir>`：指定项目根目录

`--by-table` 与 `--json` 可同时使用（输出更细粒度的 JSON）。

#### Scenario: Default progress bar per language
- **WHEN** 执行 `ct i18n status`，en 有 200 条目中 170 translated
- **THEN** 输出包含 `[en]  85% [████████░░] 170/200 translated, 12 missing, 8 stale, 10 orphan` 的进度行

#### Scenario: By-table breakdown
- **WHEN** 执行 `ct i18n status --by-table`
- **THEN** 每个 (lang, table) 组合输出独立一行，便于定位翻译瓶颈

#### Scenario: JSON shape stable for CI
- **WHEN** 执行 `ct i18n status --json`
- **THEN** stdout 仅含 JSON，结构形如 `{"langs": {"en": {"total": 200, "translated": 170, "missing": 12, "stale": 8, "orphan": 10, "tables": {...}}}}`

#### Scenario: Filter by language
- **WHEN** 执行 `ct i18n status --lang en`
- **THEN** 只输出 en 行，不显示其他语言

### Requirement: ct i18n compact command
`ct i18n compact` SHALL 物理移除 lang 文件中所有 `status: orphan` 的条目，文件中其他条目保持原样。

命令 SHALL 支持下列选项：
- `--lang <lang>`：限定一个语言
- `--table <table>`：限定一张表
- `--dry-run`：仅列出将被删除的 key，不修改文件

非 dry-run 执行成功时 SHALL 输出每个被修改文件的统计行，例如 `[compact] en/Item: 移除 3 条 orphan`。

#### Scenario: Compact removes orphan entries
- **WHEN** `i18n/en/Item.json` 含 3 条 orphan，执行 `ct i18n compact --lang en --table Item`
- **THEN** 文件中 3 条 orphan 被移除，其他条目保留，输出 `[compact] en/Item: 移除 3 条 orphan`

#### Scenario: Dry run lists deletions without writing
- **WHEN** 执行 `ct i18n compact --dry-run`
- **THEN** 输出每个 (lang, table) 下将被删除的 key 列表，文件未被修改

#### Scenario: No orphans reports nothing to do
- **WHEN** 所有 lang 文件均无 orphan 条目
- **THEN** 输出 `[compact] 无 orphan 条目，无需操作`，退出码 0

### Requirement: ct validate command
`ct validate` SHALL 只执行解析和校验流程，不生成任何输出文件。

#### Scenario: Validate all tables
- **WHEN** 用户执行 `ct validate`
- **THEN** 校验所有表，报告错误总数，不修改任何文件

#### Scenario: Validate passes
- **WHEN** 所有表校验通过
- **THEN** 输出 `校验通过`，退出码 0

### Requirement: ct gen-template command
`ct gen-template` SHALL 依据 schema 生成或**重建并迁移** Excel 模板，并写入 `excel/layout_manifests/{table}.json` 布局 manifest（模板漂移由 manifest 的 `schema_hash` 与工作簿实际列数判定；模板内不写 `ct_*` 元数据）。

命令 SHALL 支持下列选项：
- `--all`：处理所有表
- `--table <name>`：只处理指定表（精确匹配，PascalCase）
- `--root <dir>`：指定项目根目录

`--all` 与 `--table` 必须至少给一个：两者都未给时以 `请指定 --all 或 --table <表名>` 失败退出（退出码非 0）。

每张目标表按下列规则处理（`canonical_gen_template`）：
- Excel 不存在：生成空模板 + 写 manifest
- Excel 与 manifest 均存在：生成新模板到同目录的 staged 文件，按 stable column path 迁移旧数据行（`plan_excel_migration`），校验并原子替换原文件，再写 manifest
- Excel 存在但无 manifest：**拒绝**，输出 `<Table> 的 Excel 缺少布局 manifest，无法安全迁移；请先备份后删除旧文件，再重新生成空模板`，原文件不动，退出码非 0

迁移计划被阻塞时以 `Excel 数据无法安全迁移：...` 失败退出，不落盘。成功时每张表输出 `模板已生成: <Table>`，并把处理过的表的最新 Excel hash 写入 `cache/state.json` 的 `excel_hashes`（使 `ct status` 不再把该表报为 `changed`）。

（本能力未实现）原始意图：用 `--force` / `--update-header` 与模板内 `ct_schema_hash` 元数据构成一张行为决策矩阵（hash 一致则跳过并提示无需重建、legacy 无元数据拒绝、`--force` 全量覆盖、`--update-header` 保留数据重建）。这些选项、元数据字段与 `[skip]` / `[new]` / `[refuse]` / `[update]` 输出在实现中均不存在。

#### Scenario: Generate template for all tables
- **WHEN** 用户执行 `ct gen-template --all`
- **THEN** 为所有 schema 对应的 Excel 生成/重建模板并写 manifest，逐表输出 `模板已生成: <Table>`

#### Scenario: Missing filter fails
- **WHEN** 用户执行 `ct gen-template`（既无 `--all` 也无 `--table`）
- **THEN** 输出 `请指定 --all 或 --table <表名>`，退出码非 0

#### Scenario: New file generates fresh template
- **WHEN** 目标 Excel 不存在
- **THEN** 生成新模板并写 manifest，输出 `模板已生成: <Table>`

#### Scenario: Existing template is rebuilt with data preserved
- **WHEN** Excel 与 manifest 均存在且旧数据行可按 stable column path 安全迁移
- **THEN** 工具把非空旧数据行写入新模板，原子替换原文件并写新 manifest，已填数据不丢失

#### Scenario: Blocked migration refuses
- **WHEN** 旧数据行无法按 stable column path 安全迁移
- **THEN** 命令以 `Excel 数据无法安全迁移：...` 失败退出，原文件保持不动

#### Scenario: Excel without layout manifest refuses
- **WHEN** Excel 存在但没有 `excel/layout_manifests/{table}.json`
- **THEN** 命令拒绝执行并提示先备份后删除旧文件再重新生成空模板，退出码非 0

### Requirement: ct status command
`ct status` SHALL 输出且仅输出三类状态（由 `canonical_status` 计算）：
1. **`missing`**：Excel 文件不存在 → 标题 `缺失文件:`，逐行 `  [missing] <Table>`
2. **`changed`**：Excel 当前 sha256 与 `cache/state.json` 的 `excel_hashes` 记录不一致，或无记录 → 标题 `数据变更（待导出）:`，逐行 `  [changed] <Table>`
3. **`drifted`**：`excel/layout_manifests/{table}.json` 缺失、其 `schema_hash` 与当前 schema 不一致，或工作簿实际列数与 layout 列数不一致 → 标题 `模板已过时（schema 修改后未重建）:`，逐行 `  [template-stale] <Table>  (建议: ct gen-template --table <Table>)`

命令 SHALL NOT 输出 deploy 行；不存在「无元数据 / untracked」这一独立类别（无 manifest 的表归入 `drifted`）。三类全空时输出 `[OK] 所有表已是最新（数据 + 模板）`。提示中 SHALL NOT 出现 `--update-header`。

（本能力未实现）原始意图：无 `ct_*` 元数据的模板单独报为 `[template-untracked]`，并提示 `--update-header` 重建；该类别与 `--update-header` 提示都不存在。

#### Scenario: Show pending data changes
- **WHEN** `Item.xlsx` 已修改但未导出（hash 与 `excel_hashes` 不一致）
- **THEN** 输出 `  [changed] Item`

#### Scenario: Show drifted templates
- **WHEN** `Quest` 的 schema 已修改但 `excel/layout_manifests/Quest.json` 未重建
- **THEN** 输出 `  [template-stale] Quest  (建议: ct gen-template --table Quest)`，提示中不含 `--update-header`

#### Scenario: Missing Excel is its own category
- **WHEN** 某表的 Excel 文件不存在
- **THEN** 该表报为 `  [missing] <Table>`，且不同时报为 changed 或 drifted

#### Scenario: All clean reports nothing pending
- **WHEN** 三类状态均为空
- **THEN** 输出 `[OK] 所有表已是最新（数据 + 模板）`

### Requirement: Designer-friendly error messages
所有校验错误 SHALL 以中文输出，包含表名、**Excel 绝对行号**、列字母、
字段名、当前单元格值与错误说明，不暴露 Python 堆栈跟踪给非技术用户。
程序员可通过 `--verbose` 查看详细堆栈。

#### Scenario: User-friendly validation error with exact location
- **WHEN** Item 表头（3 行）之下第 3 条数据位于 Excel 第 6 行，Price 列（列 C）填写了非数值 `"贵"`
- **THEN** 输出 `[Item.xlsx] Excel 第6行 · 列C (Price) · 当前值 '贵' → 期望 float`，而非 Python 异常

#### Scenario: Absolute row survives blank lines
- **WHEN** Excel 数据区存在空行，出错行是数据区第 3 行但 Excel 绝对行号为 7
- **THEN** 错误输出使用绝对行号 `第7行`，而非跳过空行后的相对序号

#### Scenario: Verbose mode for developers
- **WHEN** 发生未预期异常且用户使用 `--verbose` 标志
- **THEN** 输出完整 Python traceback
