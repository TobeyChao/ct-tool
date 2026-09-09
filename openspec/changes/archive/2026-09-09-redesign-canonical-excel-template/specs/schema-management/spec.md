## MODIFIED Requirements

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

## ADDED Requirements

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
