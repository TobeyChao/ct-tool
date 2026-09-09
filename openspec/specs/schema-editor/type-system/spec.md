# schema-editor/type-system Specification

## Purpose
定义 Schema 的统一类型表达、Table/Record/Enum 资源边界及命名引用语义，使 Excel、校验、JSON、FlatBuffers、Binary 和 Accessor 消费同一 canonical model，并正式支持可复用 Record 与 `vector<record>`。

## Requirements

### Requirement: Canonical recursive Type Expression
系统 SHALL 将字段类型解析为递归 Type Expression，至少包含 scalar、named 和 vector 节点；所有导出和编辑模块 SHALL 消费同一 canonical 表达，不得分别猜测互斥字段组合。

#### Scenario: Parse a vector of a named record
- **WHEN** Schema 声明字段类型为 `vector<DropReward>` 或等价结构化表示
- **THEN** canonical model 为 vector 节点包装 named `DropReward` 节点，所有下游获得同一对象语义

#### Scenario: Reject nested vectors
- **WHEN** Schema 声明 `vector<vector<int32>>`
- **THEN** 加载阶段拒绝并定位字段，提示使用命名 Record 包装所需结构

### Requirement: Table Record and Enum resources
系统 SHALL 将 Table、Record、Enum 作为具名工作区资源；Record SHALL 生成 FlatBuffers table 并可复用。Enum SHALL 维护按序的 `{name, comment}` 项，字段使用处仅保存命名引用，item name 用于 Excel/JSON/FBS/Binary/Accessor，item comment 用于编辑器与 Excel Note；Enum byte wire type SHALL 固定且声明顺序 SHALL 决定 ordinal。

#### Scenario: Reuse one record from multiple tables
- **WHEN** Item.Rewards 与 Quest.Rewards 均引用 DropReward
- **THEN** 工作区只存在一个 DropReward 定义，两个字段的输出和校验均引用该定义

#### Scenario: Prevent local record overrides
- **WHEN** 用户在 Item.Rewards 使用处查看 DropReward
- **THEN** 使用处只允许编辑字段自身属性，Record 结构只能在 DropReward 资源页修改

#### Scenario: Display fixed enum wire type
- **WHEN** 用户打开 ItemRarity Enum
- **THEN** 工作台只读显示 byte wire type，并显示每项 name、comment 和由顺序确定的 ordinal

### Requirement: End-to-end vector of record
系统 SHALL 支持 `vector<Record>` 以及 scalar/Enum/string vector 从 Schema、Excel、校验和各导出的完整链路。`excel_columns: N` SHALL 表示 Excel 最大槽位数而不改变运行时 vector 类型；最后显式填写槽位决定运行时长度，其前空槽位合成元素默认值。无 `excel_columns` 的 scalar/Enum/string vector SHALL 使用内置 `[...]` 逗号文法；`vector<Record>` SHALL 只允许展开槽位形态。

#### Scenario: Read expanded record groups
- **WHEN** `Rewards: vector<DropReward>` 配置三个槽位，#1 为空、#2 已填、#3 为空
- **THEN** 读取结果长度为 2，#1 为默认 DropReward，#2 为填写值，#3 不生成元素

#### Scenario: Increase Excel columns without changing wire type
- **WHEN** `excel_columns` 从 3 增加到 5
- **THEN** Layout 新增槽位列，但 FlatBuffers 字段和 Accessor 返回类型仍为运行时 vector

#### Scenario: Read a variable scalar vector
- **WHEN** `Tags: vector<int32>` 无 excel_columns 且 Excel 填写 `[1,2,3]`
- **THEN** 全链路获得 int32 vector `[1,2,3]`

### Requirement: Canonical variable vector cell grammar
类型系统 SHALL 为无 `excel_columns` 的 scalar/Enum/string vector 定义唯一 Excel 单格文法：方括号包围、英文逗号分隔、禁止嵌套；数字不加引号，bool 使用小写字面量，Enum 使用标识符，string 使用 JSON 双引号和转义。Schema SHALL NOT 暴露自定义 separator。

#### Scenario: Editor explains built-in vector grammar
- **WHEN** 用户选择标量、Enum 或 string 的变长 vector 形态
- **THEN** 编辑器显示对应 `[...]` 示例且不显示 separator 控件

#### Scenario: Nested vector remains rejected
- **WHEN** 用户尝试构造 `vector<vector<int32>>`
- **THEN** 类型系统在进入草稿前拒绝

### Requirement: Named reference integrity
系统 SHALL 为 named 类型与跨表 `ref` 建立正向依赖和反向引用；删除被引用资源或字段默认阻止，改名 SHALL 作为显式命令原子更新所有引用。

#### Scenario: Delete a referenced record
- **WHEN** 用户尝试删除仍被 Item.Rewards 与 Quest.Rewards 引用的 DropReward
- **THEN** 系统阻止删除并返回两个可定位的引用路径，不提供 cascade delete

#### Scenario: Rename a named enum
- **WHEN** 用户将 ItemRarity 显式改名为 RarityCode
- **THEN** Candidate Workspace 原子更新所有引用，并在 Change Plan 中保留旧名到新名映射及生成 API 影响

### Requirement: Type and name constraints
资源名、字段名和生成的 FlatBuffers 类型名 SHALL 在候选工作区中执行确定性校验；Record 与 Enum 名称不得造成生成器的类型/字段撞名，错误 SHALL 在 apply 前报告完整冲突位置。

#### Scenario: Generated name collides with field
- **WHEN** 新 Enum 的生成类型名会与同作用域字段名冲突
- **THEN** Candidate Workspace 校验失败并列出资源、字段和冲突的生成名称，不写入任何文件
