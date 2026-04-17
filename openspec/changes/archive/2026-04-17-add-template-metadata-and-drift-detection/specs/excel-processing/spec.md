## MODIFIED Requirements

### Requirement: Generate Excel template headers from schema
`ct gen-template` 命令 SHALL 根据 schema 生成或更新 Excel 文件的模板头部，行数为 `max_nesting_depth + 2`（类型行 + 注释行）。当目标文件已存在且通过 `--update-header` 模式更新时，工具 SHALL 保留原有数据行原样追加到新表头之下，不丢失任何已填数据。非嵌套列跨多余行垂直合并，struct 分组列水平合并。

#### Scenario: Simple table header (no struct)
- **WHEN** schema 无嵌套 struct，max_depth=1
- **THEN** 生成 3 行头部：行1字段名、行2类型、行3注释，列顺序与 schema fields 一致

#### Scenario: Struct field expands to multiple columns
- **WHEN** schema 含 `drop_range: struct{min: int32, max: int32}`
- **THEN** drop_range 展开为 2 列（`drop_range.min`, `drop_range.max`），行1中 drop_range 跨 2 列水平合并，行2显示子字段名，行3显示类型

#### Scenario: Non-struct columns merged vertically
- **WHEN** 表头共 4 行（含一级 struct），id 字段无嵌套
- **THEN** id 对应的行1、行2单元格垂直合并为一格

#### Scenario: Two-level nested struct
- **WHEN** schema 含 `position: struct{area: struct{x: float, y: float}, z: float}`，max_depth=3
- **THEN** 生成 5 行头部，position 跨 3 列，area 跨 2 列，z 单列；z 的行3、行4垂直合并

#### Scenario: i18n field header
- **WHEN** schema 字段标记为 `i18n: true`，主语言为 zh
- **THEN** 类型行该列标注 `string[i18n]`，字段名行显示 `name#zh`

#### Scenario: ref field annotation
- **WHEN** schema 字段标记为 `ref: item_type.id`
- **THEN** 类型行该列标注 `int32[ref:item_type]`

#### Scenario: enum field annotation
- **WHEN** schema 字段 `type: enum, values: [common, rare, epic]`
- **THEN** 类型行标注 `enum[common,rare,epic]`

#### Scenario: array field annotation
- **WHEN** schema 字段 `type: array, element: int32, separator: ","`
- **THEN** 类型行标注 `array<int32>`，注释行补充 `分隔符: ,`

#### Scenario: Update header preserves data rows
- **WHEN** 目标 Excel 已有元数据 + 数据行，且 `--update-header` 被指定
- **THEN** 工具读取元数据中的 `ct_header_rows` 跳过旧表头，按新 schema 重建表头，再把所有非空旧数据行原样追加到新表头之下

#### Scenario: Update header on legacy file uses new schema header_rows
- **WHEN** 目标 Excel 已有数据但**无元数据**，`--update-header` 被指定
- **THEN** 工具用当前 schema 的 `header_rows` 推断旧表头行数，跳过该行数后保留剩余行；CLI 提示用户检查首尾行是否被误跳/误带

## ADDED Requirements

### Requirement: Write template metadata to Excel custom document properties
`generate_template` 与 `update_template` SHALL 在保存 Excel 时向 Workbook 的 Custom Document Properties 写入下列字段，作为模板"自描述"信息：

| 字段 | 类型 | 含义 |
|------|------|------|
| `ct_tool_version` | string | 当前工具版本号 |
| `ct_table_name` | string | schema.table 表名 |
| `ct_header_rows` | int | 表头行数（= schema.header_rows） |
| `ct_schema_hash` | string | schema 全字段哈希前 16 字符 |
| `ct_generated_at` | string | ISO 8601 生成时间戳 |

#### Scenario: New template carries metadata
- **WHEN** 用户对一张新表运行 `ct gen-template`
- **THEN** 生成的 Excel 文件中 Custom Document Properties 包含上述五个字段，值与当前工具版本、schema 一致

#### Scenario: Metadata invisible to spreadsheet user
- **WHEN** 策划在 Excel 中打开模板
- **THEN** 元数据不出现在任何可见单元格、Sheet 列表或公式管理器中

### Requirement: Compute schema hash including all template-visible fields
工具 SHALL 提供 `compute_schema_hash(schema)` 函数，对 `TableSchema` 的全部字段（包括字段注释、enum values、struct 嵌套子字段、ref / i18n / server_only 标记）做规范化 JSON 序列化（`sort_keys=True`），取 sha256 摘要的前 16 个十六进制字符。任何会写入表头的内容变更 MUST 导致哈希变化。

#### Scenario: Field added changes hash
- **WHEN** schema 新增一个字段
- **THEN** `compute_schema_hash` 返回的值与新增前不同

#### Scenario: Comment change changes hash
- **WHEN** 仅修改某字段的 comment（不改类型、名称、其他属性）
- **THEN** `compute_schema_hash` 返回的值与修改前不同

#### Scenario: Field reorder changes hash
- **WHEN** 调换两个字段在 schema 中的声明顺序
- **THEN** `compute_schema_hash` 返回的值与调换前不同

#### Scenario: Hash is deterministic
- **WHEN** 同一个 schema 在不同进程中两次计算
- **THEN** 两次返回的 hash 值完全相同

### Requirement: Read template metadata robustly
工具 SHALL 提供 `read_template_metadata(path)` 函数，读取 Excel 文件的 Custom Document Properties 并返回结构化对象。当文件不存在、无元数据、字段缺失或字段类型异常时，返回 `None`，不抛异常给上层调用。

#### Scenario: File without metadata returns None
- **WHEN** 文件存在但未写入 ct_* 元数据
- **THEN** `read_template_metadata` 返回 None

#### Scenario: Partial metadata returns None
- **WHEN** 文件只有 `ct_table_name` 而缺 `ct_schema_hash`
- **THEN** 函数返回 None（视为不可信元数据）

#### Scenario: Corrupted file does not crash caller
- **WHEN** 文件损坏导致 openpyxl 抛异常
- **THEN** 函数 catch 异常并返回 None

### Requirement: Detect schema drift via metadata comparison
工具 SHALL 在 `gen-template` 与 `status` 流程中，对每张表比较"当前 schema 计算出的 hash"与"模板元数据中的 ct_schema_hash"，识别以下三种状态：

| 状态 | 含义 |
|------|------|
| `matched` | 两个 hash 一致，模板与 schema 同步 |
| `drifted` | 两个 hash 不一致，schema 修改后模板未重建 |
| `untracked` | 模板无元数据（legacy 文件），无法跟踪 |

#### Scenario: Hash matches reports matched
- **WHEN** 模板元数据中的 hash 与当前 schema hash 相同
- **THEN** 状态为 `matched`

#### Scenario: Hash differs reports drifted
- **WHEN** schema 被修改（任何会进入 hash 的字段变更）
- **THEN** 状态为 `drifted`

#### Scenario: Missing metadata reports untracked
- **WHEN** 模板文件存在但 `read_template_metadata` 返回 None
- **THEN** 状态为 `untracked`