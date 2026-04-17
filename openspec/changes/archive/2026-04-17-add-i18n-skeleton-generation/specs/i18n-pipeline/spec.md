## MODIFIED Requirements

### Requirement: Extract i18n strings to source file
导出和 sync 时工具 SHALL 收集所有标记为 `i18n: true` 字段的主语言原文，按表写入 `i18n/source/{table}.json`。文件格式为扁平对象 `{ "{id}.{field}": "原文" }`，**不含**状态字段（状态完全由 lang 文件承载）。

key 排序规则：先按 id 升序，再按 schema 中 i18n 字段的出现顺序。文件 SHALL 使用紧凑 JSON 写出格式（每个 key 占一行）。

#### Scenario: New string extracted to per-table source
- **WHEN** item 表新增一行 id=1003，name="法杖"，运行 `ct i18n sync` 或 `ct export`
- **THEN** `i18n/source/item.json` 包含一行 `"1003.name": "法杖"`，文件中无 status 字段

#### Scenario: Source file rewritten on table change
- **WHEN** item id=1001 的 name 从 "宝剑" 改为 "神剑"
- **THEN** `i18n/source/item.json` 中 `"1001.name"` 的值更新为 "神剑"，其他条目不变

#### Scenario: Deleted row removed from source
- **WHEN** item id=1002 的行从 Excel 中删除，再运行 sync
- **THEN** `i18n/source/item.json` 不再包含以 `1002.` 开头的任何 key

#### Scenario: Empty source file when no i18n
- **WHEN** 一张表没有任何 i18n 字段
- **THEN** 工具不为该表生成 source 文件（已存在则保留不动，由 compact 处理）

### Requirement: Merge translations for export
导出次语言时工具 SHALL 读取 `i18n/{lang}/{table}.json`，将 `text` 字段非空且 `confirmed=true` 的译文合并到对应行。其他状态（missing/stale/orphan）SHALL 回退主语言原文并输出 warning。

#### Scenario: Confirmed translation merged
- **WHEN** `i18n/en/item.json` 中 `"1001.name": {"text": "Holy Sword", "confirmed": true, ...}` 存在
- **THEN** `output/json/item_en.json` 和 `output/binary/data_en.bin` 中该条目 name 字段值为 "Holy Sword"

#### Scenario: Stale translation falls back to source
- **WHEN** `i18n/en/item.json` 中 `"1001.name"` 的 `confirmed=false`（status 为 stale）
- **THEN** 该条目 name 回退为主语言原文，输出 warning `[item] 第1001行 name: en 译文未确认（stale），使用 zh 原文`

#### Scenario: Missing translation falls back to source
- **WHEN** `i18n/en/item.json` 中 `"1003.name"` 的 `text` 为空
- **THEN** 该条目 name 回退为主语言原文，输出 warning `[item] 第1003行 name: 缺少 en 翻译，使用 zh 原文`

#### Scenario: Lang file not found falls back to source
- **WHEN** `i18n/en/item.json` 文件不存在但 en 在 secondary_langs 中
- **THEN** 该表所有 i18n 字段使用主语言原文，输出 warning，不报错终止

### Requirement: Report stale translations
导出结束后工具 SHALL 汇总所有非 translated 状态条目（missing/stale/orphan），按 `语言 → 表 → 状态` 输出统计。

#### Scenario: Stale and missing summary shown
- **WHEN** 有 3 条 stale 的 en 翻译（item 2 条 + quest 1 条）和 5 条 missing 的 en 翻译
- **THEN** 导出完成后输出按语言 + 表分组的统计，包含 stale/missing/orphan 计数

#### Scenario: All translated reports clean
- **WHEN** 所有次语言所有 i18n 字段都是 translated 状态
- **THEN** 不输出 stale 摘要

## ADDED Requirements

### Requirement: Generate language skeleton files
sync 流程 SHALL 为每个 `secondary_langs` 中的语言、每张含 i18n 字段的表生成或更新 `i18n/{lang}/{table}.json` 骨架。

新条目（lang 文件中不存在但 source 中存在的 key）SHALL 使用以下默认值：
- `source`：当前主语言原文
- `text`：空字符串
- `confirmed`：`false`
- `status`：`missing`

文件不存在时 SHALL 自动创建（含父目录）。

#### Scenario: New lang file generated for new language
- **WHEN** secondary_langs 新增 `ja`，运行 `ct i18n sync`
- **THEN** 工具为每张含 i18n 字段的表生成 `i18n/ja/{table}.json`，所有条目 `text=""`、`confirmed=false`、`status="missing"`

#### Scenario: Existing entries preserved across sync
- **WHEN** `i18n/en/item.json` 已有 `"1001.name"` 的译文（confirmed=true），运行 sync 且 source 未变
- **THEN** 该条目 source/text/confirmed 完全不变，status 仍为 translated

#### Scenario: New row creates missing entry in lang file
- **WHEN** item 表新增 id=1004 后运行 sync
- **THEN** `i18n/en/item.json` 新增 `"1004.name": {"source": "<原文>", "text": "", "confirmed": false, "status": "missing"}`

#### Scenario: Skip table without i18n fields
- **WHEN** 某张表没有任何 i18n 字段
- **THEN** sync 不为该表创建 lang 文件

### Requirement: Translation status state machine
sync 流程 SHALL 按以下规则计算并写入每个 lang 条目的 `status` 字段：

| 当前 source 中是否存在 key | lang 中是否存在 key | text | confirmed | → status |
|---|---|---|---|---|
| 否 | 是 | — | — | `orphan` |
| 是 | 否 | — | — | `missing`（创建新条目） |
| 是 | 是 | 空 | 任意 | `missing` |
| 是 | 是 | 非空 | `true` | `translated` |
| 是 | 是 | 非空 | `false` | `stale` |

字段更新规则：
- 若 `lang.source != current_source`：覆盖 `lang.source` 为 `current_source`，强制 `confirmed=false`，保留 `text`
- 若 `lang.source == current_source`：source/text/confirmed 不变
- 不在 source 中的 key（orphan）：source/text/confirmed 不动，仅状态字段变更

#### Scenario: Source change forces re-confirmation
- **WHEN** lang 中 `"1001.name"` 的 `source="铁剑"`、`text="Iron Sword"`、`confirmed=true`，主语言改为 "精铁剑" 后运行 sync
- **THEN** 该条目 `source` 更新为 "精铁剑"，`confirmed` 重置为 `false`，`text` 保留 "Iron Sword"，`status` 变为 `stale`

#### Scenario: Translator confirmation transitions stale to translated
- **WHEN** 翻译者把 stale 条目的 `text` 改为 "Refined Iron Sword"，把 `confirmed` 改为 `true`，再运行 sync
- **THEN** `status` 变为 `translated`，其他字段保持翻译者的修改

#### Scenario: Deleted source key marks orphan
- **WHEN** Excel 删除某行后运行 sync，lang 文件中对应 key 仍然存在
- **THEN** 该条目 `status` 变为 `orphan`，source/text/confirmed 保持不变

#### Scenario: Empty text always missing regardless of confirmed
- **WHEN** lang 条目 `text=""`、`confirmed=true`
- **THEN** sync 计算 `status` 为 `missing`（confirmed 不影响空文本判定）

### Requirement: Compact orphan entries
`ct i18n compact` 命令 SHALL 物理移除 lang 文件中所有 `status: orphan` 的条目，并保留其他条目原样。

命令 SHALL 支持下列选项：
- `--lang <lang>`：限定单一语言
- `--table <table>`：限定单一表
- `--dry-run`：仅打印将被删除的条目，不修改文件

#### Scenario: Compact removes orphan entries
- **WHEN** `i18n/en/item.json` 包含 2 个 `status: orphan` 条目和 5 个其他状态条目，执行 `ct i18n compact --lang en`
- **THEN** 文件保留 5 个非 orphan 条目，2 个 orphan 条目被移除，输出 `[compact] en/item: 移除 2 条 orphan`

#### Scenario: Dry run shows planned deletions without writing
- **WHEN** 执行 `ct i18n compact --lang en --dry-run`
- **THEN** 输出每个将被删除的 key 列表，但不修改任何文件

#### Scenario: Compact preserves non-orphan entries
- **WHEN** lang 文件中混杂 missing/stale/translated/orphan
- **THEN** compact 只删 orphan，其他状态完全不变

### Requirement: Status reporting
`ct i18n status` 命令 SHALL 计算并展示每语言每表的翻译进度。

支持三种渲染模式：
- 默认：每语言一行汇总（进度百分比 + 状态计数）
- `--by-table`：每语言每表一行（便于定位翻译瓶颈）
- `--json`：机器可读 JSON，供 CI 解析

#### Scenario: Default summary shows per-language progress
- **WHEN** 执行 `ct i18n status`
- **THEN** 每个 secondary_lang 输出一行：进度百分比、translated/missing/stale/orphan 的计数

#### Scenario: By-table breakdown
- **WHEN** 执行 `ct i18n status --by-table`
- **THEN** 每个 (lang, table) 组合输出一行，便于查看哪张表翻译落后

#### Scenario: JSON output for CI
- **WHEN** 执行 `ct i18n status --json`
- **THEN** 输出结构化 JSON，包含每语言每表的四态计数与总进度，stdout 不含其他文本

#### Scenario: Filter by language
- **WHEN** 执行 `ct i18n status --lang en`
- **THEN** 只输出 en 的进度报告，忽略其他语言

### Requirement: Compact JSON writer format
所有 source 与 lang 文件 SHALL 使用紧凑 JSON 写出格式：每个 top-level key 占一行，值字段在同一行内紧凑排列。文件首尾仅有 `{` 与 `}`。

key 排序规则：先按 id 升序（数值排序，非字典序），再按 schema 中字段出现顺序。

#### Scenario: Lang entry written on single line
- **WHEN** 写出包含 `"1001.name"` 的 lang 文件
- **THEN** 该条目占一行：`  "1001.name": {"source": "铁剑", "text": "Iron Sword", "confirmed": true, "status": "translated"},`

#### Scenario: Source entry written on single line
- **WHEN** 写出 source 文件
- **THEN** 每条占一行：`  "1001.name": "铁剑",`

#### Scenario: Numeric id sort beats lexicographic
- **WHEN** 表中存在 id=2、id=10、id=100
- **THEN** 文件中 key 顺序为 `"2.field"`、`"10.field"`、`"100.field"`（按数值，非字符串）

#### Scenario: Output is valid JSON
- **WHEN** 任意 source 或 lang 文件被写出
- **THEN** 文件内容可被标准 `json.loads` 成功解析，反序列化结果与写出前的内存对象等价

### Requirement: sync command runs end-to-end skeleton refresh
`ct i18n sync` SHALL 执行：解析所有 schema → 读取 Excel → 为每张含 i18n 表写出 source 文件 → 为每语言每表更新 lang 骨架与状态字段。

命令 SHALL 支持下列选项：
- `--lang <lang>`：限定一个语言
- `--table <table>`：限定一张表
- `--root <dir>`：指定项目根目录
- `--verbose`：打印每个文件的处理详情

#### Scenario: Default sync processes all langs and tables
- **WHEN** 执行 `ct i18n sync`
- **THEN** 工具更新所有 i18n 表的 source 文件和所有 secondary_lang 的 lang 文件

#### Scenario: Filter by language
- **WHEN** 执行 `ct i18n sync --lang en`
- **THEN** source 文件全量更新，但 lang 文件只更新 `i18n/en/`

#### Scenario: Filter by table
- **WHEN** 执行 `ct i18n sync --table item`
- **THEN** 只更新 `i18n/source/item.json` 与每个 lang 的 `item.json`

#### Scenario: Sync invoked internally by export
- **WHEN** 执行 `ct export`
- **THEN** 在解析完成后、生成产物前自动运行 sync 流程，确保 lang 骨架与最新 source 一致
