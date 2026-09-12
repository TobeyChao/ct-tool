## MODIFIED Requirements

### Requirement: ct export command
`ct export` SHALL 全量重跑 canonical 导出管道，步骤序列即 `CANONICAL_STEPS`：`解析校验 → JSON → Accessor → FBS → Bundle`（`ct/app/canonical_export.py`）。管道内**无 i18n sync、无 flatc 调用、无 deploy stage**；`ct export` 不调用 `canonical_i18n_sync`，因此不写 `i18n/source/`（只有 `ct i18n sync` 会写）。

管道没有任何复用路径：每次都是全量重建，不读 `cache/state.json`。`--all` 只是把 `forced=True` 记录进返回值，不是「强制全量」开关（导出本就全量）。缓存（`excel_hashes` / `bundles`）只供 `ct status` 报告变更，不跳过导出工作。

部署不在步骤序列内：CLI 在管道成功后打印 `导出完成: N 张表`，随后调用 `ct/export/deploy.py` 的 `deploy()` 把产物同步到 Unity Assets（`[deploy] 完成：N 个文件已同步` / `[deploy] 无文件变更`），最后才调用 `persist_export_state` 提交缓存指纹。

`--table` / `--lang` 指向不存在的表或语言时 SHALL 以友好错误失败退出（`表 'X' 不存在` / `语言 'X' 不在可导出语言中（可用: ...）`，退出码非 0），SHALL NOT 静默产出空结果。

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

#### Scenario: Unknown table or language fails
- **WHEN** 用户执行 `ct export --lang zz`（`zz` 不在 `all_langs` 中），或 `ct export --table Nope`
- **THEN** 命令以非 0 退出码失败并输出可用取值（`语言 'zz' 不在可导出语言中（可用: zh, en, ja）` / `表 'Nope' 不存在`），不写任何产物、不提交缓存指纹

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

