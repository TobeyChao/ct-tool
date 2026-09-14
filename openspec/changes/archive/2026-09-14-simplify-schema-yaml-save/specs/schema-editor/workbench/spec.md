## MODIFIED Requirements

### Requirement: Schema workbench resource editing
Schema 工作台 SHALL 在同一工作区提供 Tables、Records、Enums 三类资源导航；Table 与 Record 使用字段结构编辑器，Enum 使用值编辑器；Enum item SHALL 显示不可编辑的当前 ordinal、可编辑 name 与 comment，并支持追加、重命名、删除和显式重排；可能改变数据或 wire ordinal 的操作 SHALL 在保存前的净差异摘要中呈现风险。命名类型与 ref 引用链接（`Table.Field` 形式）跳转 SHALL 复用主编辑区而不是叠加编辑模态。

#### Scenario: Navigate to named record definition
- **WHEN** 用户点击 `vector<DropReward>` 中的 DropReward
- **THEN** 主编辑区打开 DropReward 定义，导航历史保留来源字段且 Workspace Draft 不变

#### Scenario: Jump to referenced table from a ref link
- **WHEN** 用户点击字段表中 `ItemType.Id` 引用链接
- **THEN** 主编辑区打开 ItemType，资源树选中并滚动到 ItemType，Workspace Draft 不变

#### Scenario: Edit enum resource
- **WHEN** 用户从 Enums 分组打开 ItemRarity
- **THEN** 主编辑区显示枚举值、wire type、引用数量与草稿状态，不显示 Table 专属查询索引

#### Scenario: Reorder Enum items shows wire risk
- **WHEN** 用户拖动或命令式重排 Enum item
- **THEN** 工作台在保存前显示所有受影响 item 的旧/新 ordinal

#### Scenario: Add Enum item defaults to append
- **WHEN** 用户新增 Enum item
- **THEN** 新项默认追加到列表尾部并获得下一个 ordinal

#### Scenario: Rename Enum item is explicit
- **WHEN** 用户修改已有 Enum item 的 name 并确认重命名
- **THEN** Draft 记录包含 oldName、newName 与 originalOrdinal 的显式 rename 命令，净差异摘要按最终身份显示生成 API 名称影响，而不是推断为删除后新增

### Requirement: Add-field role and constraint mutual exclusion
添加字段流程 SHALL 依据真实 schema 功能联动「角色」「约束」与「类型修饰」，禁止产出非法或客户端不可用的字段配置；主键字段 `Id` 为固定必有不通过添加字段指派，代号字段 `CodeName` 为可选固定名字段，`vector` 为可选类型修饰符；变长 scalar/Enum/string vector 使用内置 `[...]` 逗号文法且不提供 separator，定长形态使用 `excel_columns` 表示最大槽位数，Record vector 仅允许定长展开，ref 不允许 vector；无真实语义的约束只作信息提示，不进入草稿命令。

#### Scenario: Primary key field is fixed and not offered in add-field
- **WHEN** 用户打开添加字段流程
- **THEN** 不提供「主键」指派（主键是固定字段 `Id`，由表定义与固定字段编辑维护；其类型 `int32`、非 `i18n`、非 `server_only` 由模型校验保障——主键在索引向量、`idHash` 与生成的 `ByID(int)` 上均以 32 位承载，故除 `int32` 外的整数标量在保存时同样被模型拒绝）

#### Scenario: I18N role restricted to string type
- **WHEN** 角色选择 I18N 后选择非 `string` 类型（含勾选 vector）
- **THEN** 类型选择对 I18N 角色仅允许 `string`，或提交时给出校验错误

#### Scenario: Codename (CodeName) is optional with a fixed name and role
- **WHEN** 用户选择添加代号字段
- **THEN** 弹窗固定字段名为 `CodeName`、类型为 `string`、角色仅为「无」（非 `i18n`、非 `server_only`）；一表至多一个 `CodeName`，已存在时阻止并提示
- **AND WHEN** 用户为该表声明 codename 索引
- **THEN** 提示「CodeName 索引要求：非空 · 表内唯一 · 非 i18n string」；该约束只作用于**声明了索引的表**，未声明索引时 `CodeName` 是可选、可重复的普通字段

#### Scenario: Vector is a modifier with built-in separator
- **WHEN** 用户勾选「vector」修饰符
- **THEN** 基础类型字段保持所选 T（标量 / Enum / Record），提交类型为 `vector<${T}>`；形态可选择「定长」或「变长」
- **AND WHEN** 基础类型 T 为 Record
- **THEN** 形态仅允许「定长」（变长禁用），并需配置展开组数 `excel_columns`
- **AND WHEN** 基础类型 T 为标量 / Enum / string
- **THEN** 可选择单格变长录入或固定列数录入；变长使用内置分隔符，定长配置 `excel_columns`；两者运行时都生成普通变长 vector
- **AND WHEN** 基础类型 T 为 ref 外键
- **THEN** 不支持勾选 vector

#### Scenario: Fixed vector explains maximum slots
- **WHEN** 用户选择定长 vector 并填写 N
- **THEN** 提交 `excel_columns: N` 且 UI 明确 N 是最大槽位数、末尾空槽位不计入长度

#### Scenario: Record and reference vector constraints
- **WHEN** 基础类型是 Record 或 ref
- **THEN** Record vector 只允许配置 excel_columns 的展开形态，ref 禁止 vector

#### Scenario: Informational constraints only
- **WHEN** 字段涉及工具强制的约束（ref 外键有效性、声明了 codename 索引的表的 `CodeName` 非空唯一等）
- **THEN** 弹窗以只读提示呈现，不提供无真实语义的勾选（如「必填」、可配置分隔符），且提示不进入草稿命令
