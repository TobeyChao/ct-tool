## Purpose

提供 `ct` 命令行接口，用统一的子命令（export/validate/status/gen-template/i18n/deploy）驱动 canonical 导出、校验与 i18n 工作流，供脚本与 CI 调用。

## Requirements

### Requirement: ct export command

`ct export` SHALL 执行 canonical 解析校验并默认增量复用生成产物，`--all` SHALL 强制生成及写出所有选中产物。对外步骤 SHALL 保持 `解析校验 → JSON → Accessor → FBS → Bundle`，不新增 Deploy 步骤。导出 SHALL 不执行 i18n sync、不写 i18n/source、不调用 flatc。

全部生成及结构检查成功后 SHALL 可恢复地发布本地产物。本地发布成功时 CLI SHALL 输出 `导出完成: N 张表`，随后执行配置的 Unity 部署并输出 `[deploy] 完成：N 个文件已同步` 或 `[deploy] 无文件变更`，最后提交成功账本。部署失败 SHALL 非零退出并保留旧账本。缓存全命中 SHALL 不省略部署。Web 导出不属于 CLI 自动部署策略。

`--table` / `--lang` SHALL 只接受单个精确值；不存在时 SHALL 友好失败（`表 'X' 不存在` / `语言 'X' 不在可导出语言中（可用: ...）`），不发布产物或提交账本。语言过滤 SHALL 保留当前兼容行为：只构建所选语言 Bundle 和次语言 JSON，但始终生成选中表的主语言 JSON，共享 FBS/Accessor/manifest 仍参与导出。表过滤的 Bundle SHALL 仅含选中表的相应内容。

#### Scenario: Default full export
- **WHEN** 用户执行 `ct export`
- **THEN** 全部表被解析校验，全部语言生成或复用 JSON/FBS/Accessor/Bundle，未变内容保留 mtime；依次输出导出完成和部署结果

#### Scenario: Export specific table
- **WHEN** 用户执行 `ct export --table Item`
- **THEN** 只选择精确匹配 Item 的表，不接受逗号列表或大小写不匹配，保持当前 ref 校验范围

#### Scenario: Export with specific language
- **WHEN** 主语言为 zh，用户执行 `ct export --lang en`
- **THEN** 生成 en Bundle 与 en JSON，同时保留主语言 zh JSON 的生成行为，不重建 zh Bundle

#### Scenario: Validation failure aborts the whole export
- **WHEN** 选中表出现类型、主键、CodeName 或跨表 ref 校验失败
- **THEN** 整个导出中止，output 与 layout manifest 保持发布前内容，退出码非零

#### Scenario: Verbose export shows debug log
- **WHEN** 执行 `ct export --verbose`
- **THEN** 启用 DEBUG 日志，不输出 i18n sync 汇总

#### Scenario: Unknown table or language fails
- **WHEN** 指定不存在的语言 zz 或表 Nope
- **THEN** 友好报错并非零退出，语言错误含可用取值，不发布产物或提交账本

#### Scenario: Forced export
- **WHEN** 执行 `ct export --all`
- **THEN** 强制生成与写出选中产物，保留原有部署流程及参数组合语义

#### Scenario: Deploy failure keeps the old ledger
- **WHEN** 本地发布成功但 Unity 同步失败
- **THEN** CLI 非零退出并输出 `[deploy error]`，完整本地产物保留，`cache/state.json` 不推进

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

`--lang` SHALL 真正限定 lang 骨架的写入范围（source 仍按选中表全量刷新）。`--lang` 不在 `secondary_langs` 中、`--table` 不存在或该表不含 i18n 字段时 SHALL 以友好错误失败退出（`语言 'X' 不在 secondary_langs 中` / `表 'X' 不存在` / `表 'X' 没有 i18n 字段`，退出码非 0），SHALL NOT 静默忽略过滤条件后照常成功。

完成时 SHALL 输出汇总，例如 `[i18n sync] 处理 3 张表 × 2 语言：新增 5、更新 12、stale 3、orphan 2`；`--verbose` 时每个写出的文件各输出一行路径与变更条目数（例如 `[i18n sync] 写入 i18n/en/Item.json（新增 2、更新 0、stale 0、orphan 0）`）。

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

#### Scenario: Unknown filter value fails
- **WHEN** 执行 `ct i18n sync --lang zz`（`zz` 不在 `secondary_langs` 中）或 `ct i18n sync --table Nope`
- **THEN** 命令以非 0 退出码失败并输出可用取值，不写任何 source / lang 文件

#### Scenario: Verbose lists written files
- **WHEN** 执行 `ct i18n sync --verbose`
- **THEN** 每个写出的 source / lang 文件各输出一行路径与变更条目数，非 verbose 时只输出逐表 `synced <Table>` 与汇总行

### Requirement: ct i18n status command
`ct i18n status` SHALL 报告每语言（或每语言每表）的翻译进度。

命令 SHALL 支持下列选项：
- `--lang <lang>`：只显示一个语言
- `--by-table`：每语言每表一行
- `--json`：输出机器可读 JSON
- `--root <dir>`：指定项目根目录

`--by-table` 与 `--json` 可同时使用（输出更细粒度的 JSON）。

进度百分比 SHALL 为 `translated / (total - orphan)`：orphan 是 source 中已不存在的残留条目（由 `compact` 清理），不计入分母；无活跃条目视为 100%。文本模式每行 SHALL 为 `[<lang>]  <百分比>% [<10 格进度条>] <translated>/<total - orphan> translated, <missing> missing, <stale> stale, <orphan> orphan`；`--by-table` 时在每个语言行之后追加该语言的逐表行（同一行格式，标签为表名）。

`--json` SHALL 只在 stdout 输出 JSON（stdout 不含其他文本），结构形如 `{"langs": {"en": {"total": 200, "translated": 170, "missing": 12, "stale": 8, "orphan": 10, "progress": 0.8947, "tables": {...}}}}`；`total` 仍是四态之和（含 orphan），`progress` 是不含 orphan 的分母比值。`--lang` 不在 `secondary_langs` 中时 SHALL 以友好错误失败退出（退出码非 0）。

#### Scenario: Default progress bar per language
- **WHEN** 执行 `ct i18n status`，en 有 200 条目（170 translated、12 missing、8 stale、10 orphan）
- **THEN** 输出包含 `[en]  89% [█████████░] 170/190 translated, 12 missing, 8 stale, 10 orphan` 的进度行（10 个 orphan 不计入分母）

#### Scenario: By-table breakdown
- **WHEN** 执行 `ct i18n status --by-table`
- **THEN** 每个 (lang, table) 组合输出独立一行，便于定位翻译瓶颈

#### Scenario: JSON shape stable for CI
- **WHEN** 执行 `ct i18n status --json`
- **THEN** stdout 仅含 JSON，结构形如 `{"langs": {"en": {"total": 200, "translated": 170, "missing": 12, "stale": 8, "orphan": 10, "tables": {...}}}}`

#### Scenario: Filter by language
- **WHEN** 执行 `ct i18n status --lang en`
- **THEN** 只输出 en 行，不显示其他语言

#### Scenario: Unknown language fails
- **WHEN** 执行 `ct i18n status --lang zz`（`zz` 不在 `secondary_langs` 中）
- **THEN** 命令以非 0 退出码失败并输出可用语言列表，不输出任何进度行

### Requirement: ct i18n compact command
`ct i18n compact` SHALL 物理移除 lang 文件中所有 `status: orphan` 的条目，文件中其他条目保持原样。

命令 SHALL 支持下列选项：
- `--lang <lang>`：限定一个语言
- `--table <table>`：限定一张表
- `--dry-run`：仅列出将被删除的 key，不修改文件

`--lang` / `--dry-run` SHALL 真正生效：`--dry-run` 绝不修改任何文件。`--lang` 不在 `secondary_langs` 中、`--table` 不存在或该表不含 i18n 字段时 SHALL 以友好错误失败退出（退出码非 0）。

非 dry-run 执行成功时 SHALL 输出每个被修改文件的统计行，例如 `[compact] en/Item: 移除 3 条 orphan`；dry-run 时同一位置输出 `[compact] en/Item: 将移除 3 条 orphan` 并逐行列出待删 key。无 orphan 条目时 SHALL 输出 `[compact] 无 orphan 条目，无需操作`。

#### Scenario: Compact removes orphan entries
- **WHEN** `i18n/en/Item.json` 含 3 条 orphan，执行 `ct i18n compact --lang en --table Item`
- **THEN** 文件中 3 条 orphan 被移除，其他条目保留，输出 `[compact] en/Item: 移除 3 条 orphan`

#### Scenario: Dry run lists deletions without writing
- **WHEN** 执行 `ct i18n compact --dry-run`
- **THEN** 输出每个 (lang, table) 下将被删除的 key 列表，文件未被修改

#### Scenario: No orphans reports nothing to do
- **WHEN** 所有 lang 文件均无 orphan 条目
- **THEN** 输出 `[compact] 无 orphan 条目，无需操作`，退出码 0

#### Scenario: Language filter applies
- **WHEN** `i18n/en/Item.json` 与 `i18n/ja/Item.json` 各含 orphan，执行 `ct i18n compact --lang en`
- **THEN** 只有 `i18n/en/Item.json` 被修改，`i18n/ja/Item.json` 保持原样

#### Scenario: Unknown filter value fails
- **WHEN** 执行 `ct i18n compact --lang zz`（`zz` 不在 `secondary_langs` 中）或 `ct i18n compact --table Nope`
- **THEN** 命令以非 0 退出码失败并输出可用取值，不修改任何文件

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

`--all` 与 `--table` 必须至少给一个：两者都未给时以 `请指定 --all 或 --table <表名>` 失败退出（退出码非 0）。`--table` 指向不存在的表时 SHALL 以 `表 'X' 不存在` 失败退出（退出码非 0），SHALL NOT 静默不处理任何表而成功退出；仅大小写不符时 SHALL 在错误中提示正确写法（表名精确匹配 PascalCase）。

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

#### Scenario: Unknown table fails
- **WHEN** 用户执行 `ct gen-template --table Nope`（`Nope` 不是任何 schema 的表名）
- **THEN** 命令以 `表 'Nope' 不存在` 失败退出（退出码非 0），不生成、不修改任何文件

#### Scenario: Case-mismatched table hints the correct name
- **WHEN** 用户执行 `ct gen-template --table item`（存在表 `Item`）
- **THEN** 命令以非 0 退出码失败，并在错误中提示 `是否想用 'Item'？`

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

schema / 配置**加载阶段**的错误（非 `int32` 主键、schema 文件缺失、旧字段形状等）SHALL 同样以 `[error] <说明>` 友好失败、退出码非 0，SHALL NOT 让 `ValueError` 冒泡成 traceback——`ct validate` / `ct status` / `ct i18n *` 与 `ct export`（`[export error]`）、`ct panel` 行为一致；`--verbose` 时 SHALL 把完整堆栈写入日志而不是 stdout。

#### Scenario: User-friendly validation error with exact location
- **WHEN** Item 表头（3 行）之下第 3 条数据位于 Excel 第 6 行，Price 列（列 C）填写了非数值 `"贵"`
- **THEN** 输出 `[Item.xlsx] Excel 第6行 · 列C (Price) · 当前值 '贵' → 期望 float`，而非 Python 异常

#### Scenario: Absolute row survives blank lines
- **WHEN** Excel 数据区存在空行，出错行是数据区第 3 行但 Excel 绝对行号为 7
- **THEN** 错误输出使用绝对行号 `第7行`，而非跳过空行后的相对序号

#### Scenario: Verbose mode for developers
- **WHEN** 发生未预期异常且用户使用 `--verbose` 标志
- **THEN** 输出完整 Python traceback

#### Scenario: Schema load error is friendly
- **WHEN** 某表主键声明为 `int64`（模型固定为 `int32`），执行 `ct validate` 或 `ct status`
- **THEN** 输出 `[error] 加载 Table 失败 [<Table>.yaml]: 表 <Table>: 主键字段 'Id' 类型必须为 int32（当前: int64）…`，退出码 1，输出中不含 `Traceback`；加 `--verbose` 时堆栈写入日志供开发排查

### Requirement: 导出输出报告填充率与定宽体积代价

`ct export` SHALL 为每张表输出一行报告：**布局形态**（定宽 / 变长，取自 schema 的 `uniform` 声明）在前，填充率百分比与体积对比（常规布局字节数 → 定宽布局字节数，附倍率）在后。该行 SHALL NOT 把填充率排在布局形态之前或用箭头相连，以免读作「填充率决定了布局」。填充率是**诊断数字**，SHALL NOT 参与布局决策。

当一张声明定宽（含缺省）的表，其定宽体积比常规布局明显更大时，该行 SHALL 追加提示，说明膨胀倍数并指引可通过对该表声明 `uniform: false` 退回变长布局。提示 SHALL NOT 阻断导出。

#### Scenario: 定宽表报告体积收益

- **WHEN** 导出缺省定宽且填充率高的表
- **THEN** 输出形如 `定宽（schema 声明）｜填充率 92.9%（436 B → 424 B，0.972x）` 的一行

#### Scenario: 稀疏表定宽给出体积提示

- **WHEN** 某表声明定宽但填充率低，使定宽字节数明显大于常规布局
- **THEN** 该行追加提示，指出膨胀倍数并提示可声明 `uniform: false`
- **AND** 导出仍成功完成

#### Scenario: 变长表不报告定宽体积

- **WHEN** 某表声明 `uniform: false`
- **THEN** 该行报告为变长，且不给出定宽体积对比
