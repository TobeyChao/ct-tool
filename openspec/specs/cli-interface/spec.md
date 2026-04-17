## ADDED Requirements

### Requirement: ct export command
`ct export` SHALL 执行增量导出流程：变更检测 → 解析 → 校验 → **i18n sync（自动）** → JSON/Binary 输出 → 缓存更新。

`ct export` 在解析完成后、生成各语言产物之前 SHALL 自动调用 i18n sync 内部入口，确保 source/lang 文件与最新 schema/Excel 保持一致；该内部调用默认安静运行，仅在 `--verbose` 模式下输出 sync 汇总。

#### Scenario: Default incremental export
- **WHEN** 用户执行 `ct export`
- **THEN** 只导出 hash 变化的表，输出进度信息，成功后显示导出摘要

#### Scenario: Export specific tables
- **WHEN** 用户执行 `ct export --table item,item_type`
- **THEN** 只处理指定的表（仍走增量检测）

#### Scenario: Export with specific languages
- **WHEN** 用户执行 `ct export --lang zh,en`
- **THEN** 只导出 zh 和 en 语言的产物，忽略其他配置的语言

#### Scenario: Validation failure stops export
- **WHEN** 某张表校验失败
- **THEN** 该表不生成任何产物，其他无错误的表正常导出，退出码非 0

#### Scenario: Export auto-syncs i18n skeletons
- **WHEN** 执行 `ct export`，某张含 i18n 字段的表新增了一行
- **THEN** export 流程内部触发 i18n sync，对应 lang 文件中自动出现新的 `missing` 条目；后续合并步骤使用最新 lang 文件

#### Scenario: Verbose export shows sync summary
- **WHEN** 执行 `ct export --verbose`
- **THEN** 输出包含 i18n sync 的汇总（新增/更新/stale/orphan 计数）

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
- **WHEN** 执行 `ct i18n sync --table item`
- **THEN** `i18n/source/item.json` 与每语言的 `item.json` 被处理，其他表的文件不动

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

非 dry-run 执行成功时 SHALL 输出每个被修改文件的统计行，例如 `[compact] en/item: 移除 3 条 orphan`。

#### Scenario: Compact removes orphan entries
- **WHEN** `i18n/en/item.json` 含 3 条 orphan，执行 `ct i18n compact --lang en --table item`
- **THEN** 文件中 3 条 orphan 被移除，其他条目保留，输出 `[compact] en/item: 移除 3 条 orphan`

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
- **THEN** 输出 `✓ 所有表校验通过（共 N 张表）`，退出码 0

### Requirement: ct gen-template command
`ct gen-template` SHALL 根据 schema 生成或更新 Excel 文件的模板头部，并写入 schema 元数据。命令 SHALL 根据目标文件的元数据状态决定行为，绝不静默丢失已填数据。

命令 SHALL 支持下列选项：
- `--all`：处理所有 schema
- `--table <name>`：只处理指定表
- `--force`：在文件已存在时强制全量覆盖（不保留数据）
- `--update-header`：在文件已存在时保留数据行原样追加到新表头之下

行为决策矩阵：

| 文件状态 | 默认行为 | `--force` | `--update-header` |
|---------|---------|-----------|------------------|
| 不存在 | 生成新模板 + 元数据 | 同左 | 同左 |
| 无元数据（legacy） | 拒绝 + 提示二选一 | 全量覆盖（数据丢失） | 用新 schema header_rows 推断保留数据 |
| `ct_table_name` 不匹配 | 拒绝（任何 flag 都拒绝） | 拒绝 | 拒绝 |
| hash 一致（无变化） | 跳过 + 提示无需重建 | 重建 | 重建 |
| hash 不同 + 无数据 | 直接重建 | 重建 | 重建 |
| hash 不同 + 有数据 | 拒绝 + 提示二选一 | 全量覆盖（数据丢失） | 保留数据重建 |

#### Scenario: Generate template for all tables
- **WHEN** 用户执行 `ct gen-template --all`
- **THEN** 为所有 schema 对应的 Excel 按上述决策矩阵处理

#### Scenario: New file generates with metadata
- **WHEN** 目标 Excel 不存在
- **THEN** 生成新模板并写入 ct_* 元数据，输出 `[new] <path>`

#### Scenario: Hash matches default skips with hint
- **WHEN** 文件存在且 ct_schema_hash 与当前 schema hash 一致，未指定任何 flag
- **THEN** 命令跳过该表，输出 `[skip] <table>: schema 未变化，模板无需重建（如需强制重建请加 --force）`，退出码 0

#### Scenario: Hash matches with --force rebuilds
- **WHEN** 文件存在且 hash 一致，用户指定 `--force`
- **THEN** 命令全量重建模板（数据会丢，用户已显式确认）

#### Scenario: Hash differs with data refuses by default
- **WHEN** schema 已修改且模板有数据行，未指定 flag
- **THEN** 命令拒绝执行，输出 `[refuse] <table>: schema 已修改且文件含数据。使用 --update-header 保留数据重建表头，或 --force 强制覆盖`，退出码非 0

#### Scenario: Hash differs with --update-header preserves data
- **WHEN** schema 已修改且模板有数据行，用户指定 `--update-header`
- **THEN** 命令读取元数据中的 ct_header_rows 跳过旧表头，按新 schema 重建表头，把所有非空旧数据行原样追加到新表头之下，写入新元数据，输出 `[update] <table>: 已重建表头并保留 N 行数据`

#### Scenario: Legacy file without metadata refuses by default
- **WHEN** 文件存在但无 ct_* 元数据，未指定 flag
- **THEN** 命令拒绝执行，输出 `[refuse] <table>: 文件无元数据（可能由旧版工具或手工创建）。使用 --update-header 用当前 schema 推断保留数据，或 --force 强制覆盖`

#### Scenario: Legacy file with --update-header uses current schema header_rows
- **WHEN** 文件无元数据，用户指定 `--update-header`
- **THEN** 命令用当前 schema 的 `header_rows` 推断旧表头行数，跳过该行数后保留剩余行作为数据，输出警告提示用户检查首尾行

#### Scenario: Table name mismatch refuses even with --force
- **WHEN** 文件元数据中 `ct_table_name` 为 `quest`，但当前正在处理 schema `item`
- **THEN** 命令拒绝执行（即使指定 `--force` 或 `--update-header`），输出 `[refuse] item.xlsx 元数据归属为 'quest'，与当前 schema 'item' 不一致。请手动确认归属后重试（改名或删除文件）`，退出码非 0

### Requirement: ct status command
`ct status` SHALL 同时输出两类状态：
1. **数据变更**：Excel 文件 hash 与缓存不一致的表（待导出）
2. **模板漂移**：当前 schema_hash 与模板元数据中 `ct_schema_hash` 不一致的表（提示重建模板）

无任何状态时输出 `[OK] 所有表已是最新（数据 + 模板）`。

#### Scenario: Show pending data changes
- **WHEN** item.xlsx 已修改但未导出
- **THEN** 输出 `[changed] item` 列表

#### Scenario: Show drifted templates
- **WHEN** quest 的 schema 已修改但 quest.xlsx 模板未重建（元数据中的 ct_schema_hash 与当前 schema 计算结果不同）
- **THEN** 输出 `[template-stale] quest`，并附建议命令 `ct gen-template --table quest --update-header`

#### Scenario: Show untracked templates
- **WHEN** shop.xlsx 文件存在但无 ct_* 元数据
- **THEN** 输出 `[template-untracked] shop`，作为单独类别

#### Scenario: All clean reports nothing pending
- **WHEN** 所有表既无数据变更也无模板漂移
- **THEN** 输出 `[OK] 所有表已是最新（数据 + 模板）`

### Requirement: Designer-friendly error messages
所有校验错误和运行时错误 SHALL 以中文输出，包含表名、行号、字段名，不暴露 Python 堆栈跟踪给非技术用户。程序员可通过 `--verbose` 查看详细堆栈。

#### Scenario: User-friendly validation error
- **WHEN** item.xlsx 第 5 行 price 字段类型错误
- **THEN** 输出：`❌ [item.xlsx] 第 5 行 price：期望 float，实际值 "贵"`，而非 Python 异常

#### Scenario: Verbose mode for developers
- **WHEN** 发生未预期异常且用户使用 `--verbose` 标志
- **THEN** 输出完整 Python traceback
