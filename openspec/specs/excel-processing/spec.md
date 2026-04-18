## ADDED Requirements

### Requirement: Read Excel data according to schema
工具 SHALL 使用 openpyxl 读取 Excel 文件，从 schema 定义的起始数据行开始解析，忽略模板头部行（前 N 行由工具生成）。

#### Scenario: Data parsed correctly
- **WHEN** Excel 文件包含正确的列头和数据行
- **THEN** 工具按字段顺序解析每行数据，空行自动跳过

#### Scenario: Extra columns ignored
- **WHEN** Excel 中存在 schema 未定义的列
- **THEN** 工具记录 warning 但继续处理，忽略多余列

#### Scenario: Excel file not found
- **WHEN** schema 引用的 Excel 文件不存在
- **THEN** 工具报错指明文件路径，终止该表的处理

### Requirement: Generate Excel template headers from schema
`ct gen-template` 命令 SHALL 根据 schema 生成或更新 Excel 文件的模板头部，行数为 `max_nesting_depth + 1`（字段名+类型行 N 行 + 注释行 1 行）。当目标文件已存在且通过 `--update-header` 模式更新时，工具 SHALL 保留原有数据行原样追加到新表头之下，不丢失任何已填数据。非嵌套列跨多余行垂直合并，struct 分组列水平合并。每个字段单元格内通过富文本（`CellRichText`）同时承载字段名（12pt 粗体白）与类型注解（9pt 斜体浅绿 `D8F3DC`），中间用换行分隔；不再存在独立的 type 行。struct 横向合并单元格的类型注解为 `to_pascal_case(field.name)`（与 FBS 生成的 table 名一致）。

#### Scenario: Simple table header (no struct)
- **WHEN** schema 无嵌套 struct，max_depth=1
- **THEN** 生成 2 行头部：行1每格内含字段名+类型富文本（如 "id" / "int32"），行2为注释行，列顺序与 schema fields 一致

#### Scenario: Struct field expands to multiple columns
- **WHEN** schema 含 `drop_range: struct{min: int32, max: int32}`
- **THEN** drop_range 展开为 2 列（`drop_range.min`, `drop_range.max`），行1中 drop_range 横向合并为 1 格，单元格内含富文本 "drop_range" + "DropRange"；行2显示子字段名 + 类型（如 "min" / "int32"）；行3为注释行

#### Scenario: Non-struct columns merged vertically
- **WHEN** 表头共 3 行（含一级 struct），id 字段无嵌套
- **THEN** id 对应的行1、行2单元格垂直合并为一格，富文本 "id" + "int32" 显示在合并单元格内

#### Scenario: Two-level nested struct
- **WHEN** schema 含 `position: struct{area: struct{x: float, y: float}, z: float}`，max_depth=3
- **THEN** 生成 4 行头部，position 横跨 3 列且单元格内显示 "position" + "Position"，area 横跨 2 列显示 "area" + "Area"，z 单列垂直合并行2与行3且显示 "z" + "float"；行4 为注释行

#### Scenario: i18n field header
- **WHEN** schema 字段标记为 `i18n: true`，主语言为 zh
- **THEN** 该字段单元格内富文本第二行显示 `string[i18n]`

#### Scenario: ref field annotation
- **WHEN** schema 字段标记为 `ref: item_type.id`
- **THEN** 该字段单元格内富文本第二行显示 `int32[ref:item_type.id]`

#### Scenario: enum field annotation
- **WHEN** schema 字段 `type: enum, values: [common, rare, epic]`
- **THEN** 该字段单元格内富文本第二行显示 `enum[common,rare,epic]`

#### Scenario: array field annotation
- **WHEN** schema 字段 `type: array, element: int32, separator: ","`
- **THEN** 该字段单元格内富文本第二行显示 `array<int32>`，注释行（最末行）补充 `分隔符: ,`

#### Scenario: Update header preserves data rows
- **WHEN** 目标 Excel 已有元数据 + 数据行，且 `--update-header` 被指定
- **THEN** 工具读取元数据中的 `ct_header_rows` 跳过旧表头（无论旧值是 `+2` 还是 `+1` 时代生成），按新 schema 重建 `+1` 行表头，再把所有非空旧数据行原样追加到新表头之下

#### Scenario: Update header on legacy file uses new schema header_rows
- **WHEN** 目标 Excel 已有数据但**无元数据**，`--update-header` 被指定
- **THEN** 工具用当前 schema 的 `header_rows`（`+1` 公式）推断旧表头行数，跳过该行数后保留剩余行；CLI 提示用户检查首尾行是否被误跳/误带

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

### Requirement: Read Excel data with struct and array fields
工具 SHALL 根据 schema 将展开的 struct 多列数据重组为嵌套对象，将 array 单列按分隔符拆分为列表。

#### Scenario: Struct columns reassembled
- **WHEN** Excel 中 `drop_range.min=10`, `drop_range.max=20`
- **THEN** 解析结果为 `{"drop_range": {"min": 10, "max": 20}}`

#### Scenario: Array parsed with separator
- **WHEN** Excel 中 tags 列值为 `"1,2,5"`，separator 为 `,`
- **THEN** 解析结果为 `{"tags": [1, 2, 5]}`

#### Scenario: Array with custom separator
- **WHEN** schema 定义 `separator: "|"`，Excel 填写 `"1|2|5"`
- **THEN** 解析结果为 `{"tags": [1, 2, 5]}`

#### Scenario: Array element type validated
- **WHEN** array<int32> 的单元格填写 `"1,abc,5"`
- **THEN** 报错：`[item.xlsx] 第N行 tags：第2个元素 "abc" 无法转换为 int32`

### Requirement: Detect changes via file hash
工具 SHALL 对每个 Excel 文件计算 MD5 hash，与缓存中的上次 hash 比对，确定是否需要重新导出。

#### Scenario: File unchanged
- **WHEN** Excel 文件内容与缓存 hash 一致
- **THEN** 跳过该表的导出，输出 "unchanged: item" 提示

#### Scenario: File changed
- **WHEN** Excel 文件 hash 与缓存不一致
- **THEN** 将该表加入待导出队列
