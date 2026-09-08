## MODIFIED Requirements

### Requirement: Schema workbench resource editing
Schema 工作台 SHALL 在同一工作区提供 Tables、Records、Enums 三类资源导航；Table/Record 使用字段编辑器，Enum 使用按序 item 编辑器。Enum item SHALL 显示不可编辑的当前 ordinal、可编辑 name 与 comment，并支持追加、重命名、删除和显式重排；可能改变数据或 wire ordinal 的操作 SHALL 在计划中呈现风险。

#### Scenario: Navigate to named record definition
- **WHEN** 用户点击 `vector<DropReward>` 中的 DropReward
- **THEN** 主编辑区打开 DropReward，导航历史保留来源字段且 Workspace Draft 不变

#### Scenario: Edit enum resource
- **WHEN** 用户编辑 ItemRarity.Rare 的 comment
- **THEN** 草稿只记录注释变化，Rare 的 name、位置和 ordinal 不变

#### Scenario: Reorder Enum items shows wire risk
- **WHEN** 用户拖动或命令式重排 Enum item
- **THEN** 工作台在 Apply 前显示所有受影响 item 的旧/新 ordinal

#### Scenario: Add Enum item defaults to append
- **WHEN** 用户新增 Enum item
- **THEN** 新项默认追加到列表尾部并获得下一个 ordinal

#### Scenario: Rename Enum item is explicit
- **WHEN** 用户修改已有 Enum item 的 name 并确认重命名
- **THEN** Draft 记录包含 oldName、newName 与 originalOrdinal 的显式 rename 命令，Change Plan 显示 Excel 值迁移数量和生成 API 名称影响，而不是推断为删除后新增

### Requirement: Add-field role and constraint mutual exclusion
添加字段流程 SHALL 依据 canonical 类型与角色约束产出合法字段。主键 Id 固定存在、Code 为可选固定名、vector 为类型修饰符；变长 scalar/Enum/string vector 使用内置 `[...]` 逗号文法且不提供 separator，定长形态使用 `excel_columns` 表示最大槽位数，Record vector 仅允许定长展开，ref 不允许 vector。

#### Scenario: Primary key field is fixed and not offered in add-field
- **WHEN** 用户打开添加字段流程
- **THEN** 不提供主键指派，Id 的整数类型及角色约束由模型保障

#### Scenario: I18N role restricted to string type
- **WHEN** 角色选择 I18N
- **THEN** 类型仅允许非 vector string，或提交时返回明确校验错误

#### Scenario: Codename (Code) is optional with a fixed name and role
- **WHEN** 用户选择添加 Code 字段
- **THEN** 名称固定 Code、类型固定 string、角色为无，并保障一表至多一个

#### Scenario: Vector is a modifier with built-in separator
- **WHEN** 用户为 scalar、Enum 或 string 勾选 vector 并选择变长
- **THEN** 提交 `vector<T>`、不携带 excel_columns 或 separator，并显示对应 `[...]` 输入示例

#### Scenario: Fixed vector explains maximum slots
- **WHEN** 用户选择定长 vector 并填写 N
- **THEN** 提交 `excel_columns: N` 且 UI 明确 N 是最大槽位数、末尾空槽位不计入长度

#### Scenario: Record and reference vector constraints
- **WHEN** 基础类型是 Record 或 ref
- **THEN** Record vector 只允许配置 excel_columns 的展开形态，ref 禁止 vector

#### Scenario: Informational constraints only
- **WHEN** 字段涉及 ref 有效性或 Code 唯一性等工具强制约束
- **THEN** 弹窗只显示说明，不创建无对应 Schema 语义的开关
