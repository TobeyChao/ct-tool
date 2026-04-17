## ADDED Requirements

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

## MODIFIED Requirements

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
