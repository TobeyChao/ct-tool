## Purpose

按 schema 的字段→列布局读取 Excel 数据，并根据 schema 生成 Excel 模板表头与布局元数据，作为策划填表与工具读取的一致真源。

## Requirements

### Requirement: Read Excel data according to schema
工具 SHALL 使用 openpyxl 读取 Excel 文件，从 schema 定义的起始数据行开始解析，忽略模板头部行（前 N 行由工具生成）。

整数标量列（`int8` / `uint8` / `int16` / `uint16` / `int32` / `uint32` / `int64` / `uint64`）的值 SHALL 落在该**声明类型**的值域内。越界值 SHALL 在解析校验阶段报为类型错误（`期望 <type> 类型`，定位到表、行与列），使 `ct validate` 与 `ct export` 一致失败；SHALL NOT 留到产物生成阶段由 flatbuffers builder 抛出 `TypeError`（导出主键存进 4 字节索引向量，越界值此前会以 Python traceback 结束）。

#### Scenario: Data parsed correctly
- **WHEN** Excel 文件包含正确的列头和数据行
- **THEN** 工具按字段顺序解析每行数据，空行自动跳过

#### Scenario: Extra columns ignored
- **WHEN** Excel 中存在 schema 未定义的列
- **THEN** 工具记录 warning 但继续处理，忽略多余列

#### Scenario: Excel file not found
- **WHEN** schema 引用的 Excel 文件不存在
- **THEN** 工具报错指明文件路径，终止该表的处理

#### Scenario: Out-of-range integer rejected
- **WHEN** `int32` 字段（含主键）的单元格填写 `5000000000`（超出 `[-2147483648, 2147483647]`）
- **THEN** 工具报类型错误 `期望 int32 类型` 并定位到该行该列，`ct validate` 返回非 0；`ct export` 在解析校验阶段中止，不写任何产物

### Requirement: Generate Excel template headers from schema
`ct gen-template` SHALL 将字段结构投影为以物理叶子列为底的节点树。设表内最深节点层级为 `D`，第 `d` 层注释行 SHALL 为 `2d-1`，字段行 SHALL 为 `2d`，表头总行数 SHALL 为 `2D`（即 `Layout.header_rows`），数据 SHALL 从 `2D+1` 行开始。每个 Record、vector 或 vector 槽位节点的注释格和字段格 SHALL 分别横向覆盖其全部后代叶子列；较浅叶子 SHALL 仅保留自身层的注释格，并将字段格纵向合并至第 `2D` 行。合并 SHALL 按节点身份与叶子跨度决定，不得按相邻文本是否相同决定。模板 SHALL 冻结全部表头行且 SHALL NOT 生成 AutoFilter。

#### Scenario: Simple table header (no Record)
- **WHEN** 表中所有字段均为第 1 层叶子且 `D=1`
- **THEN** 第 1 行逐列显示字段注释，第 2 行逐列显示字段名与类型，数据从第 3 行开始

#### Scenario: Record field expands to multiple columns
- **WHEN** `DropRange: ItemDropRange` 含叶子 `Min` 与 `Max`
- **THEN** 第 1、2 行分别横向合并显示 DropRange 注释与 `DropRange / ItemDropRange`，第 3、4 行分别逐列显示 Min/Max 的注释及字段与类型，数据从第 5 行开始

#### Scenario: Two-level nested Record
- **WHEN** `Position` 含 `Area.{X,Y}` 与叶子 `Z`，全表 `D=3`
- **THEN** Position 注释格和字段格横跨 X/Y/Z，Area 注释格和字段格只横跨 X/Y，Z 字段格从第 4 行纵向合并到第 6 行，X 与 Y 永不互相合并

#### Scenario: Non-Record columns merged vertically
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
- **THEN** vector 节点横跨三个数据列，第 2 层绘制三个独立槽位节点 `#1/#2/#3`，注释分别显示 `数据项[1]`、`数据项[2]`、`数据项[3]`

#### Scenario: Fixed Record vector renders slot subtrees
- **WHEN** `Rewards: vector<DropReward>` 配置 `excel_columns: 2` 且 DropReward 含 ItemId/Count
- **THEN** vector 节点横跨四列，第二层两个槽位各横跨自身 ItemId/Count，第三层逐列绘制对应叶子

#### Scenario: i18n field header
- **WHEN** string 字段标记 `i18n: true`
- **THEN** 字段格的类型注解追加 `[i18n]`，对应节点注释格保持独立

#### Scenario: ref field annotation
- **WHEN** 字段标记 `ref: ItemType.Id`
- **THEN** 字段格的类型注解追加 `[ref: ItemType.Id]`

#### Scenario: enum field annotation
- **WHEN** 字段引用具名 Enum `ItemRarity`
- **THEN** 字段格第二行显示 `ItemRarity [enum]`，不把全部候选值挤入表头文字

#### Scenario: vector field annotation
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
| `ct_tool_version` | string | 固定写入 `ct`（当前不是版本号） |
| `ct_table_name` | string | schema.table 表名 |
| `ct_header_rows` | int | 表头行数（= `Layout.header_rows`，即 `2D`） |
| `ct_schema_hash` | string | schema 全字段哈希前 16 字符 |
| `ct_generated_at` | string | ISO 8601 生成时间戳 |

工具当前**只写入、不读回**这些 Custom Document Properties；模板漂移判定改读 `excel/layout_manifests/{Table}.json`（见下条 Requirement）。

#### Scenario: New template carries metadata
- **WHEN** 用户对一张新表运行 `ct gen-template`
- **THEN** 生成的 Excel 文件中 Custom Document Properties 包含上述五个字段，值与当前工具写入的固定值、`Layout` 一致

#### Scenario: Metadata invisible to spreadsheet user
- **WHEN** 策划在 Excel 中打开模板
- **THEN** 元数据不出现在任何可见单元格、Sheet 列表或公式管理器中

### Requirement: Compute schema hash including all template-visible fields
工具 SHALL 提供 `compute_schema_hash(table, dependencies=())` 函数（`ct/schema/hashing.py`），对 `TableResource` 及其引用的 `RecordResource` / `EnumResource` 依赖（包括字段注释、Enum values、Record 嵌套子字段、ref / i18n / server_only 标记）做规范化 JSON 序列化（`sort_keys=True`），取 sha256 摘要的前 16 个十六进制字符。任何会写入表头的内容变更 MUST 导致哈希变化。

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

### Requirement: Read the layout manifest robustly

工具 SHALL 提供 `load_manifest(manifest_dir, table)` 函数（`ct/excel/layout_manifest.py`），读取 `excel/layout_manifests/{Table}.json` 并返回 `LayoutManifest`。当文件不存在、无法读取、JSON 解析失败、`format` 不是 `template-layout/2`，或 `columns` / `nodes` 等字段类型异常时，SHALL 返回 `None`（视为不可信 manifest），不抛异常给上层调用。

manifest 的字段集合 SHALL 恰好为：`format`、`schema_hash`、`header_rows`、`columns`、`nodes`、`slot_offsets`。这六项 SHALL 全部是 schema 的纯函数，SHALL NOT 随 Excel 数据变化；`uniform` 与 `fill_rate` SHALL NOT 出现在 manifest 中（前者是 schema 声明，后者是导出期诊断数字，两者都不参与布局决策、也不需要被持久化）。

`uniform: false` 的表 SHALL 写空的 `slot_offsets`。

#### Scenario: Missing manifest returns None

- **WHEN** 表没有对应的 layout manifest 文件
- **THEN** `load_manifest` 返回 None

#### Scenario: Incompatible or malformed manifest returns None

- **WHEN** manifest 是合法 JSON，但 `format` 不是 `template-layout/2`，或 `columns` / `nodes` 等字段类型异常
- **THEN** 函数返回 None（视为不可信 manifest）

#### Scenario: Corrupted file does not crash caller

- **WHEN** manifest 无法读取或 JSON 解析失败
- **THEN** 函数 catch 异常并返回 None

#### Scenario: manifest 字段集合固定

- **WHEN** 导出后检查任一表的 layout manifest
- **THEN** 其键集合恰好是 `format` / `schema_hash` / `header_rows` / `columns` / `nodes` / `slot_offsets`
- **AND** 改 Excel 数据（不改 schema）后重导，manifest 逐字节不变

#### Scenario: 旧键被忽略

- **WHEN** manifest 里存在多余的旧键（如历史上的 `uniform` / `fill_rate` / `layout_revision`）
- **THEN** `parse` 忽略它们，不影响读取结果

### Requirement: Detect template drift via layout manifest comparison
`ct status` SHALL 为每张表计算并分别列出三个状态：`missing`（schema 引用的 Excel 文件不存在，该表不再参与其余判断）、`changed`（Excel 文件 sha256 与缓存台账不一致，或该表从未导出）、`drifted`（layout manifest 缺失/不可信，或其 `schema_hash` 与当前 schema 计算值不一致，或工作表列数与当前 `Layout.column_count` 不一致）。`drifted` 提示重建模板（`ct gen-template --table {Table}`）。

不存在单独的 `untracked` 状态：manifest 缺失即 `drifted`；「无元数据的 legacy 模板」因此不再与「schema 改过」区分。

#### Scenario: Matching manifest is not reported as drifted
- **WHEN** manifest 的 `schema_hash` 与当前 schema hash 相同，且工作表列数等于当前 `Layout.column_count`
- **THEN** 该表不出现在 `drifted`

#### Scenario: Schema change reports drifted
- **WHEN** schema 被修改（任何会进入 hash 的字段变更）而 manifest 未更新
- **THEN** 该表出现在 `drifted`

#### Scenario: Missing manifest reports drifted
- **WHEN** 表存在 Excel 文件但没有可信的 layout manifest
- **THEN** 该表出现在 `drifted`（没有独立的 `untracked` 状态）

#### Scenario: Missing workbook reports missing
- **WHEN** schema 引用的 Excel 文件不存在
- **THEN** 该表出现在 `missing`，不进入 `changed` / `drifted`

### Requirement: Read Excel data with Record and vector fields
工具 SHALL 按 Layout 将具名 Record 的物理叶子列重组为嵌套对象。无 `excel_columns` 的 `vector<Scalar>`、`vector<Enum>` 和 `vector<string>` SHALL 从单元格读取括号 `[...]` 文法；有 `excel_columns: N` 的 vector SHALL 将 N 个物理槽位读取为运行时变长 vector，最后一个显式填写槽位决定长度，其前方全空槽位及已填写 Record 槽位中的空叶子递归补类型默认值，末尾全空槽位不生成元素。

#### Scenario: Record columns reassembled
- **WHEN** Excel 中 `DropRange.Min=10`、`DropRange.Max=20`
- **THEN** 解析结果包含 `{"DropRange": {"Min": 10, "Max": 20}}`

#### Scenario: Nested Record columns reassembled recursively
- **WHEN** Excel 中填写 `Position.Area.X=1`、`Position.Area.Y=2`、`Position.Z=3`
- **THEN** 解析结果包含 `{"Position": {"Area": {"X": 1, "Y": 2}, "Z": 3}}`，同名但不同父路径的叶子不会互相覆盖

#### Scenario: Vector parsed with separator
- **WHEN** `Tags: vector<int32>` 单元格填写 `[1, 2, 5]`
- **THEN** 内置英文逗号作为 canonical token 分隔符，解析结果为 `{"Tags": [1, 2, 5]}`，Schema 不再配置 separator

#### Scenario: Empty variable vector parsed
- **WHEN** 变长 vector 单元格为空、`[]` 或 `[   ]`
- **THEN** 解析结果均为空数组

#### Scenario: Vector with custom separator
- **WHEN** Schema 声明自定义 `separator: "|"` 或单元格填写 `[1|2|5]`
- **THEN** 工具拒绝自定义分隔符并提示使用内置 `[...]` 英文逗号文法

#### Scenario: Vector element type validated
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
工具 SHALL 对每个 Excel 文件计算 sha256（`_file_sha256`），与缓存 `excel_hashes` 台账中的上次 hash 比对，把「hash 不一致或缓存无记录（从未导出）」的表列为 `changed`，供 `ct status` 报告。该状态只用于报告：`ct export` SHALL NOT 因「文件未变更」跳过任何表的导出工作；不带过滤的导出会先清空 `output/{fbs,generated,json,binary}` 再重建全部产物，导出步骤为 `CANONICAL_STEPS = ("解析校验", "JSON", "Accessor", "FBS", "Bundle")`。

#### Scenario: Unchanged file is not reported as changed
- **WHEN** Excel 文件的 sha256 与缓存台账一致
- **THEN** 该表不出现在 `changed`（不存在「跳过该表导出」的分支，`ct export` 仍照常重建该表产物）

#### Scenario: File changed
- **WHEN** Excel 文件 hash 与缓存不一致
- **THEN** 将该表列为 `changed`

#### Scenario: Never exported table
- **WHEN** 缓存中没有该表的 `excel_hashes` 记录
- **THEN** 该表列为 `changed`

### Requirement: Plan Excel data changes by stable paths
Excel 迁移预检 SHALL 仅在用户显式更新模板时执行，不属于 YAML 保存。预检 SHALL 比较可信旧布局与新布局的稳定路径，扫描删除、收缩和类型转换处的数据；无法证明无损时 SHALL 在写回前停止并保留原 Excel 与 manifest。保存后的重命名 SHALL NOT 仅凭同列位置或名称相似性推断映射，本变更不要求持久化跨保存迁移映射。

#### Scenario: Rename retains values
- **WHEN** 用户显式更新模板，涉及重命名的数据已经由用户另行处理且可按可信 manifest 稳定路径无损映射
- **THEN** 可映射数据被保留，不产生重复数据列；无法证明重命名映射时适用拒绝自动迁移场景

#### Scenario: Rename without a proven mapping
- **WHEN** YAML 中 A 已改为 C，旧 A 列有数据且模板更新没有可靠映射
- **THEN** 更新拒绝自动搬移并报告无法映射的位置，原工作簿与 manifest 不变

#### Scenario: Type conversion failure
- **WHEN** 用户显式更新 string→int32 模板且旧列含不可转换值
- **THEN** 更新列出失败位置和值并停止；之前独立保存的 YAML 不被回滚

### Requirement: Verify reading compatibility before data preparation
validate/export SHALL 在按当前 Schema 读取实际参与校验的工作簿（含引用依赖表）前，验证可信 manifest、工作簿受管表头结构与当前读取布局兼容。表头行数、字段路径、列顺序、类型及展开槽位不匹配，或无法可靠确定兼容性时 SHALL 阻止读取并定位需更新模板的表；SHALL NOT 通过导出刷新 manifest 掩盖不匹配。额外未受管尾列仍可警告并忽略。

#### Scenario: Same-type columns are reordered
- **WHEN** YAML 交换两个同类型字段，Excel 与 manifest 仍是旧顺序
- **THEN** validate/export 在数据解释前拒绝，不能按新顺序静默交换值

#### Scenario: Nested layout changes
- **WHEN** Record 嵌套深度或 vector 展开数量改变但模板未更新
- **THEN** validate/export 报告读取布局不兼容，导出产物、manifest 和成功账本不变

#### Scenario: Cosmetic drift remains readable
- **WHEN** 仅注释等展示内容变化且完整读取结构仍可证明兼容
- **THEN** 模板可提示 drifted，但 validate/export 不因完整 schema hash 不同而拒绝，仍执行正常数据校验

#### Scenario: Referenced workbook is incompatible
- **WHEN** 过滤导出选中表依赖的外键目标表模板不兼容
- **THEN** 闸门同样拒绝该依赖表的读取，不允许只检查显式选中表

#### Scenario: Manifest cannot prove compatibility
- **WHEN** manifest 缺失、损坏或与真实受管表头不符
- **THEN** 拒绝猜测读取并提示独立处理模板，不修改工作簿
