## MODIFIED Requirements

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
