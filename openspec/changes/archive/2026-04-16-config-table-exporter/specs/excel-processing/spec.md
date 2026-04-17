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
`ct gen-template` 命令 SHALL 根据 schema 生成或更新 Excel 文件的模板头部，行数为 `max_nesting_depth + 2`（类型行 + 注释行），不影响已有数据行。非嵌套列跨多余行垂直合并，struct 分组列水平合并。

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
