## ADDED Requirements

### Requirement: Add-field role and constraint mutual exclusion
添加字段流程 SHALL 依据真实 schema 功能联动「角色」「约束」与「类型修饰」，禁止产出非法或客户端不可用的字段配置；主键字段 `Id` 为固定必有不通过添加字段指派，代号字段 `Code` 为可选固定名字段，`vector` 为可选类型修饰符；无真实语义的约束只作信息提示，不进入草稿命令。

#### Scenario: Primary key field is fixed and not offered in add-field
- **WHEN** 用户打开添加字段流程
- **THEN** 不提供「主键」指派（主键是固定字段 `Id`，由表定义与固定字段编辑维护；其类型 `int32`/`int64`、非 `i18n`、非 `server_only` 由模型校验保障）

#### Scenario: I18N role restricted to string type
- **WHEN** 角色选择 I18N 后选择非 `string` 类型（含勾选 vector）
- **THEN** 类型选择对 I18N 角色仅允许 `string`，或提交时给出校验错误

#### Scenario: Codename (Code) is optional with a fixed name and role
- **WHEN** 用户选择添加代号字段
- **THEN** 弹窗固定字段名为 `Code`、类型为 `string`、角色仅为「无」（非 `i18n`、非 `server_only`），并提示「Code 索引要求：非空 · 表内唯一 · 非 i18n string」；一表至多一个 `Code`，已存在时阻止并提示

#### Scenario: Vector is a modifier with built-in separator
- **WHEN** 用户勾选「vector」修饰符
- **THEN** 基础类型字段保持所选 T（标量 / Enum / Record），提交类型为 `vector<${T}>`；形态可选择「定长」或「变长」
- **AND WHEN** 基础类型 T 为 Record
- **THEN** 形态仅允许「定长」（变长禁用），并需配置展开组数 `excel_columns`
- **AND WHEN** 基础类型 T 为标量 / Enum / string
- **THEN** 可选择单格变长录入或固定列数录入；变长使用内置分隔符，定长配置 `excel_columns`；两者运行时都生成普通变长 vector
- **AND WHEN** 基础类型 T 为 ref 外键
- **THEN** 不支持勾选 vector

#### Scenario: Informational constraints only
- **WHEN** 字段涉及工具强制的约束（ref 外键有效性、Code 索引非空唯一等）
- **THEN** 弹窗以只读提示呈现，不提供无真实语义的勾选（如「必填」、可配置分隔符），且提示不进入草稿命令
