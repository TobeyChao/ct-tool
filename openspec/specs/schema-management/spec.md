## Purpose

从 config/schemas 与 config/types 加载资源、解析类型表达式，构建跨表依赖图与拓扑序，为导出与校验提供结构化模型。

## Requirements

### Requirement: Load schema from YAML files
工具 SHALL 从 `config/schemas/` 目录加载所有 `*.yaml` 文件，使用 Pydantic 模型校验结构完整性。加载失败时报告具体文件名和错误原因。

#### Scenario: Valid schema loaded
- **WHEN** `config/schemas/item.yaml` 包含合法的 table/primary/fields 定义
- **THEN** 工具成功解析并构建对应的 TableSchema 对象

#### Scenario: Schema missing required field
- **WHEN** YAML 文件缺少 `primary` 或 `fields` 字段
- **THEN** 工具报错并指明文件名和缺失字段，终止执行

#### Scenario: Duplicate table name
- **WHEN** 两个 schema 文件定义了相同的 `table` 名称
- **THEN** 工具报错指明冲突的文件名，终止执行

### Requirement: Build cross-table reference dependency graph
工具 SHALL 分析所有 schema 中的 `ref` 字段，构建有向依赖图，用于确定导出和校验顺序。

#### Scenario: Valid reference graph
- **WHEN** item 的 `item_type_id` 字段引用 `item_type.id`
- **THEN** 依赖图中 item → item_type 存在边，item_type 先于 item 处理

#### Scenario: Circular reference detected
- **WHEN** 表 A 引用表 B，表 B 引用表 A
- **THEN** 工具报错指明循环路径（A → B → A），终止执行

### Requirement: Topological sort for processing order
工具 SHALL 对依赖图进行拓扑排序，输出确定性的表处理顺序，被引用表始终先于引用方处理。

#### Scenario: Correct ordering
- **WHEN** 存在 category → item_type → item 的引用链
- **THEN** 处理顺序为 category, item_type, item（或等价的合法顺序）

### Requirement: Validate field type definitions
Schema 中每个字段 SHALL 声明合法的类型（`int32`, `int64`, `float`, `double`, `bool`, `string`, `enum`, `struct`, `array`）及可选标记（`i18n`, `ref`, `server_only`）。

#### Scenario: Invalid field type
- **WHEN** schema 字段 type 为 `integer`（非法值）
- **THEN** 工具报错指明文件名、字段名和合法类型列表

### Requirement: Validate enum field definitions
每个 Enum 资源 SHALL 包含 1 至 256 个按序声明的结构化枚举项；每项 SHALL 含唯一、非空且合法标识符的 `name` 以及可为空的 `comment`。声明顺序 SHALL 确定 byte wire ordinal，首项的 `name` SHALL 为 canonical 类型默认值且 Binary SHALL 将其映射为 ordinal 0。旧的字符串 `values` 列表 SHALL 被拒绝。

#### Scenario: Valid enum definition
- **WHEN** Enum 定义 `values: [{name: Common, comment: 普通}, {name: Rare, comment: 稀有}]`
- **THEN** 工具加载两个枚举项，Common/Rare 的 ordinal 分别为 0/1，Common 同时为默认值

#### Scenario: Empty enum values
- **WHEN** Enum 的 values 为空
- **THEN** 工具在加载阶段报错并定位 Enum 资源

#### Scenario: Duplicate enum item rejected
- **WHEN** 两个枚举项具有相同 name
- **THEN** 工具拒绝资源并指出重复名称

#### Scenario: Legacy string values rejected
- **WHEN** Enum 仍声明 `values: [Common, Rare]`
- **THEN** canonical 加载拒绝该旧格式且不进入兼容分支

#### Scenario: Enum data validation
- **WHEN** Excel 填写的值不在 Enum item name 集合中
- **THEN** 校验报错并列出合法 name；comment 不作为可填写值

### Requirement: Validate field flag combinations
工具 SHALL 在 Schema 加载阶段校验字段标记的合法组合：i18n 与 server_only 互斥，主键不得 server_only，`excel_columns` 仅允许 vector 且 ref 不得 vector。字段模型 SHALL NOT 接受 `separator`；所有无 `excel_columns` 的标量/Enum/string vector 使用内置括号逗号文法，`vector<Record>` 必须配置 `excel_columns`。

#### Scenario: i18n + server_only rejected
- **WHEN** 字段同时标记 `i18n: true` 和 `server_only: true`
- **THEN** 工具在 Schema 加载阶段拒绝并定位字段

#### Scenario: primary key marked server_only rejected
- **WHEN** 主键字段标记 `server_only: true`
- **THEN** 工具拒绝该组合并说明客户端数据将失去主键

#### Scenario: separator on non-vector / record-vector field rejected
- **WHEN** 任意字段声明 `separator`
- **THEN** 工具将其视为未知 canonical 属性并拒绝，提示 vector 使用内置 `[...]` 逗号文法

#### Scenario: excel_columns only valid on vector
- **WHEN** 非 vector 字段声明 `excel_columns`
- **THEN** 工具拒绝并说明该属性仅表示 vector 的 Excel 最大展开槽位数

#### Scenario: Variable Record vector rejected
- **WHEN** `vector<Record>` 未声明 `excel_columns`
- **THEN** 工具拒绝并提示 Record 元素必须按固定最大槽位展开

#### Scenario: Reference vector rejected
- **WHEN** 带 ref 的字段声明 vector 类型
- **THEN** 工具拒绝该组合

### Requirement: Calculate maximum nesting depth
工具 SHALL 以表头节点树计算最大节点深度 D：顶层字段为第 1 层；Record 子字段增加一层；定长 scalar/Enum/string vector 的槽位增加一层；定长 Record vector 的槽位增加一层且 Record 子字段继续逐层增加。模板表头行数 SHALL 为 `2D`。

#### Scenario: Flat table depth
- **WHEN** 所有字段均为顶层叶子或无展开单格 vector
- **THEN** `D=1` 且表头行数为 2

#### Scenario: Single level struct depth
- **WHEN** DropRange Record 直接包含 Min/Max 叶子
- **THEN** `D=2` 且表头行数为 4

#### Scenario: Nested struct depth
- **WHEN** Position 含 Area.{X,Y} 与 Z
- **THEN** `D=3` 且表头行数为 6

#### Scenario: Fixed scalar vector depth
- **WHEN** 顶层 `vector<float>` 配置 `excel_columns`
- **THEN** 数组节点为第 1 层、槽位叶子为第 2 层，`D` 至少为 2

#### Scenario: Fixed Record vector depth
- **WHEN** 顶层 `vector<DropReward>[N]` 且 DropReward 直接包含叶子
- **THEN** 数组、槽位 Record、Record 叶子分别位于第 1、2、3 层

#### Scenario: Depth calculation rule
- **WHEN** 计算任意字段节点深度
- **THEN** 顶层节点深度为 1，Record 后代和定长 vector 槽位每经过一层结构节点加 1，表头行数为全表最大深度的两倍

### Requirement: Preserve enum ordinal semantics across edits
Enum comment 修改 SHALL NOT 改变 ordinal；新增项默认 SHALL 追加。重命名、删除、插入或重排 SHALL 在 Change Plan 中展示受影响值与 ordinal 变化。显式 item rename SHALL 保持位置/ordinal 并原子迁移 Excel 中 scalar Enum、定长 Enum 槽位及变长 Enum vector 的精确旧 name；工具 SHALL NOT 将未配对的删除+新增猜测为重命名。删除 SHALL 扫描现有 Excel 使用位置并在仍有引用时阻止 Apply。

#### Scenario: Comment-only edit is wire-safe
- **WHEN** 仅修改 Rare 的 comment
- **THEN** 所有 item name 和 ordinal 保持不变，Change Plan 不报告 wire ordinal 风险

#### Scenario: Reorder reports ordinal changes
- **WHEN** 用户交换 Rare 与 Epic 的声明顺序
- **THEN** Change Plan 列出两个值的旧/新 ordinal，并将操作标为 wire-level 风险

#### Scenario: Explicit rename migrates values without changing ordinal
- **WHEN** 用户通过显式命令将 ordinal 1 的 Rare 重命名为 Uncommon
- **THEN** Change Plan 报告各形态 Excel 使用位置和迁移数量，Apply 原子改写精确 Rare token，ordinal 1 保持不变并报告生成 API 名称变化

#### Scenario: Delete and add is not inferred as rename
- **WHEN** Candidate 删除 Rare 并新增 Uncommon 但不存在显式 rename 命令
- **THEN** 工具按删除与新增分别规划；若 Rare 仍被使用则阻止 Apply

#### Scenario: Delete used value is blocked
- **WHEN** 删除仍出现在 Excel 数据中的 Enum item
- **THEN** Change Plan 定位表、字段、Excel 行和值并阻止 Apply

### Requirement: Validate primary key type
工具 SHALL 在 schema 加载阶段校验主键字段的类型必须是 `int32` 或
`int64`；其他类型（含 `string`、`bool`、`float`、`double`、`enum` 等）
一律拒绝。报错 SHALL 指明表名、主键字段名与当前类型，且不得输出
Python traceback。

#### Scenario: Integer primary key accepted
- **WHEN** schema 定义 `primary: Id` 且 `Id` 字段 `type: int32`（或 `int64`）
- **THEN** 工具成功加载 schema，后续 validate / export / gen-template 正常执行

#### Scenario: String primary key rejected
- **WHEN** schema 定义 `primary: Code` 且 `Code` 字段 `type: string`
- **THEN** 工具在加载阶段报错，指明表名、主键字段名与当前类型（string），
  终止执行且不进入数据校验/导出阶段

#### Scenario: Other non-integer primary key rejected
- **WHEN** schema 定义 `primary: Name` 且 `Name` 字段 `type: bool`
  （或 `float`、`enum` 等其他非整数类型）
- **THEN** 工具在加载阶段报错，指明表名、主键字段名与当前类型

### Requirement: Load named schema resources
工具 SHALL 从配置仓库加载 Table、Record、Enum 资源并构建一个 WorkspaceSnapshot；资源 ID、名称、来源文件和类型 SHALL 可稳定定位，重复名称或缺失来源 SHALL 在加载时报告。

#### Scenario: Load a mixed workspace
- **WHEN** 配置包含多个 Table、Record 和 Enum
- **THEN** WorkspaceSnapshot 包含全部资源及确定性顺序，字段命名引用可解析到唯一目标

### Requirement: Build workspace dependency and reverse-reference graph
工具 SHALL 同时分析 named 类型引用和跨表 `ref`，构建确定性的正向依赖与反向引用图；Candidate SHALL 拒绝失效目标、非法环和删除仍被引用的节点。

#### Scenario: Record dependency chain
- **WHEN** Item 引用 DropReward，DropReward 引用 ItemRarity
- **THEN** 图中存在对应依赖边，反向查询 ItemRarity 返回 DropReward 的精确字段路径

#### Scenario: Missing named target
- **WHEN** 字段引用不存在的 Reward
- **THEN** 加载或 Candidate 校验失败并定位引用字段与缺失名称
