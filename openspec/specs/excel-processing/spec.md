## Purpose

按 schema 的字段→列布局读取 Excel 数据，并根据 schema 生成 Excel 模板表头与布局元数据，作为策划填表与工具读取的一致真源。

## Requirements

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
`ct gen-template` SHALL 将字段结构投影为以物理叶子列为底的节点树。设表内最深节点层级为 `D`，第 `d` 层注释行 SHALL 为 `2d-1`，字段行 SHALL 为 `2d`，表头总行数 SHALL 为 `2D`，数据 SHALL 从 `2D+1` 行开始。每个 Record、数组或数组槽位节点的注释格和字段格 SHALL 分别横向覆盖其全部后代叶子列；较浅叶子 SHALL 仅保留自身层的注释格，并将字段格纵向合并至第 `2D` 行。合并 SHALL 按节点身份与叶子跨度决定，不得按相邻文本是否相同决定。模板 SHALL 冻结全部表头行且 SHALL NOT 生成 AutoFilter。

#### Scenario: Simple table header (no struct)
- **WHEN** 表中所有字段均为第 1 层叶子且 `D=1`
- **THEN** 第 1 行逐列显示字段注释，第 2 行逐列显示字段名与类型，数据从第 3 行开始

#### Scenario: Struct field expands to multiple columns
- **WHEN** `DropRange: ItemDropRange` 含叶子 `Min` 与 `Max`
- **THEN** 第 1、2 行分别横向合并显示 DropRange 注释与 `DropRange / ItemDropRange`，第 3、4 行分别逐列显示 Min/Max 的注释及字段与类型，数据从第 5 行开始

#### Scenario: Two-level nested struct
- **WHEN** `Position` 含 `Area.{X,Y}` 与叶子 `Z`，全表 `D=3`
- **THEN** Position 注释格和字段格横跨 X/Y/Z，Area 注释格和字段格只横跨 X/Y，Z 字段格从第 4 行纵向合并到第 6 行，X 与 Y 永不互相合并

#### Scenario: Non-struct columns merged vertically
- **WHEN** 顶层 Id 与三级嵌套 Record 共存
- **THEN** Id 注释只占第 1 行，Id 字段格从第 2 行纵向合并到第 6 行

#### Scenario: Equal sibling text does not merge nodes
- **WHEN** 两个相邻叶子或槽位拥有相同名称、类型或注释文本
- **THEN** 模板仍按各自节点边界绘制独立单元格，不因文本相同而合并

#### Scenario: Every schema node keeps its own comment
- **WHEN** 顶层 Record、嵌套 Record 与各叶子分别声明不同 `FieldDef.comment`
- **THEN** 每个节点只在自身深度的注释行显示自己的 comment；空 comment 保留空单元格和层级，不借用父级或子级文字

#### Scenario: Fixed scalar vector renders slots
- **WHEN** `Weights: vector<float>` 配置 `excel_columns: 3`
- **THEN** 数组节点横跨三个数据列，第 2 层绘制三个独立槽位节点 `#1/#2/#3`，注释分别显示 `数据项[1]`、`数据项[2]`、`数据项[3]`

#### Scenario: Fixed Record vector renders slot subtrees
- **WHEN** `Rewards: vector<DropReward>` 配置 `excel_columns: 2` 且 DropReward 含 ItemId/Count
- **THEN** 数组节点横跨四列，第二层两个槽位各横跨自身 ItemId/Count，第三层逐列绘制对应叶子

#### Scenario: i18n field header
- **WHEN** string 字段标记 `i18n: true`
- **THEN** 字段格的类型注解追加 `[i18n]`，对应节点注释格保持独立

#### Scenario: ref field annotation
- **WHEN** 字段标记 `ref: ItemType.Id`
- **THEN** 字段格的类型注解追加 `[ref: ItemType.Id]`

#### Scenario: enum field annotation
- **WHEN** 字段引用具名 Enum `ItemRarity`
- **THEN** 字段格第二行显示 `ItemRarity [enum]`，不把全部候选值挤入表头文字

#### Scenario: array field annotation
- **WHEN** 字段类型为 `vector<int32>`
- **THEN** 字段格显示 canonical vector 类型；无 `excel_columns` 时注释提示 `[...]` 文法，有 `excel_columns` 时显示最大槽位数

#### Scenario: Update header preserves data rows
- **WHEN** 目标 Excel 含可按受支持的 `template-layout/2` manifest 稳定叶子路径读取的数据并重新生成模板
- **THEN** 工具将可映射的数据值搬到新表头后的对应叶子列，所有工具管理的格式与辅助效果重新生成

#### Scenario: Layout manifest is diff-friendly
- **WHEN** 工具在 `excel/layout_manifests` 生成或更新 `template-layout/2` manifest
- **THEN** manifest 使用键排序、4 空格缩进和单个文件末尾换行的完整 pretty JSON；此规则不改变 `output/json` 业务数据的一记录一行格式

#### Scenario: Update header on legacy file uses new schema header_rows
- **WHEN** 已存在的 Excel 缺少可信 manifest、manifest 损坏或仍为 `template-layout/1`
- **THEN** 本次 cutover 不猜测旧表头行数且不写回文件，而是报告需备份并删除旧文件后重建空模板

#### Scenario: No auto-filter is generated
- **WHEN** 打开任意新生成模板
- **THEN** 工作表不包含 AutoFilter 范围或筛选箭头

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
工具 SHALL 按 Layout 将具名 Record 的物理叶子列重组为嵌套对象。无 `excel_columns` 的 `vector<Scalar>`、`vector<Enum>` 和 `vector<string>` SHALL 从单元格读取括号数组文法；有 `excel_columns: N` 的 vector SHALL 将 N 个物理槽位读取为运行时变长 vector，最后一个显式填写槽位决定长度，其前方全空槽位及已填写 Record 槽位中的空叶子递归补类型默认值，末尾全空槽位不生成元素。

#### Scenario: Struct columns reassembled
- **WHEN** Excel 中 `DropRange.Min=10`、`DropRange.Max=20`
- **THEN** 解析结果包含 `{"DropRange": {"Min": 10, "Max": 20}}`

#### Scenario: Nested Record columns reassembled recursively
- **WHEN** Excel 中填写 `Position.Area.X=1`、`Position.Area.Y=2`、`Position.Z=3`
- **THEN** 解析结果包含 `{"Position": {"Area": {"X": 1, "Y": 2}, "Z": 3}}`，同名但不同父路径的叶子不会互相覆盖

#### Scenario: Array parsed with separator
- **WHEN** `Tags: vector<int32>` 单元格填写 `[1, 2, 5]`
- **THEN** 内置英文逗号作为 canonical token 分隔符，解析结果为 `{"Tags": [1, 2, 5]}`，Schema 不再配置 separator

#### Scenario: Empty variable vector parsed
- **WHEN** 变长 vector 单元格为空、`[]` 或 `[   ]`
- **THEN** 解析结果均为空数组

#### Scenario: Array with custom separator
- **WHEN** Schema 声明自定义 `separator: "|"` 或单元格填写 `[1|2|5]`
- **THEN** 工具拒绝自定义分隔符并提示使用内置 `[...]` 英文逗号文法

#### Scenario: Array element type validated
- **WHEN** `vector<int32>` 单元格填写 `[1,abc,5]`
- **THEN** 工具报错定位第 2 个元素 `abc` 无法转换为 int32

#### Scenario: Unbracketed variable vector rejected
- **WHEN** `vector<int32>` 单元格填写 `1,2,5`
- **THEN** 工具报错指出该 Excel 绝对行、列、字段及“变长 vector 必须使用 [...] 格式”

#### Scenario: Fixed scalar vector fills holes with defaults
- **WHEN** `vector<int32>[3]` 的物理槽位为 `10, 空, 30`
- **THEN** 最后填写槽位为 #3，读取结果为 `[10, 0, 30]`

#### Scenario: Trailing empty slots do not extend length
- **WHEN** `vector<int32>[3]` 的物理槽位为 `10, 空, 空`
- **THEN** 读取结果为 `[10]`

#### Scenario: Fixed Record vector fills an empty prior slot
- **WHEN** `vector<DropReward>[2]` 的 Slot #1 全空而 Slot #2 含 `{ItemId: 2001, Count: 3}`
- **THEN** 读取结果长度为 2，Slot #1 为递归类型默认值 `{ItemId: 0, Count: 0}`

#### Scenario: Partially filled Record slot defaults blank leaves
- **WHEN** DropReward Slot 中 ItemId 已填而 Count 为空
- **THEN** 该 Slot 计入长度且 Count 使用 int32 默认值 0

### Requirement: Detect changes via file hash
工具 SHALL 对每个 Excel 文件计算 MD5 hash，与缓存中的上次 hash 比对，确定是否需要重新导出。

#### Scenario: File unchanged
- **WHEN** Excel 文件内容与缓存 hash 一致
- **THEN** 跳过该表的导出，输出 "unchanged: item" 提示

#### Scenario: File changed
- **WHEN** Excel 文件 hash 与缓存不一致
- **THEN** 将该表加入待导出队列

### Requirement: Plan Excel data changes by stable paths
Workspace Change Plan SHALL 比较旧/新列路径和显式 rename command，生成可审查映射，并扫描删除、收缩和类型转换位置的非空数据；无法无损处理的数据 SHALL 阻止 Apply。

#### Scenario: Rename retains values
- **WHEN** `Item.Name` 显式改名为 `Item.DisplayName`
- **THEN** 所有旧 Name 单元格映射到 DisplayName，计划显示搬移数量且不创建重复列

#### Scenario: Type conversion failure
- **WHEN** string 字段改为 int32 且存在不可转换值
- **THEN** Change Plan 列出失败行列和原值并阻止 Apply
