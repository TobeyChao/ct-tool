## MODIFIED Requirements

### Requirement: Validate field flag combinations
工具 SHALL 在 schema 加载阶段校验字段标记的合法组合，禁止语义冲突的标记同时存在：i18n 与 server_only 互斥，主键不得 server_only，`excel_columns` 仅允许 vector 且 ref 不得 vector。字段模型 SHALL NOT 接受 `separator`；所有无 `excel_columns` 的标量/Enum/string vector 使用内置括号逗号文法，`vector<Record>` 必须配置 `excel_columns`。

#### Scenario: i18n + server_only rejected
- **WHEN** schema 字段同时标记 `i18n: true` 和 `server_only: true`
- **THEN** 工具在 schema 加载阶段报错：`字段 {name} 不能同时标记 i18n 和 server_only（i18n 字段用于客户端 UI，server_only 字段不进入 Binary）`

#### Scenario: primary key marked server_only rejected
- **WHEN** 表的主键字段同时标记 `server_only: true`
- **THEN** 工具在 schema 加载阶段报错，指明表名与主键字段名（主键是客户端与次语言 bundle 的主键，`server_only` 字段不进入客户端 Binary，组合会让客户端数据失去主键）

#### Scenario: separator on non-vector / record-vector field rejected
- **WHEN** 非 vector 字段（scalar / enum / ref / 具名 Record），或 `vector<Record>` 字段（按 `excel_columns` 展开为列组）声明 `separator`
- **THEN** 工具在 schema 加载阶段报错，指明表名、字段名与当前类型（`separator` 仅对单格 token 式 vector——即 `vector<Scalar>` / `vector<Enum>`——有意义）

#### Scenario: excel_columns only valid on vector
- **WHEN** 非 vector 字段（scalar / enum / ref / 具名 Record）声明 `excel_columns`
- **THEN** 工具在 schema 加载阶段报错，指明表名、字段名与当前类型（`excel_columns` 仅适用于 vector 的定长 Excel 列展开）

#### Scenario: Variable Record vector rejected
- **WHEN** `vector<Record>` 未声明 `excel_columns`
- **THEN** 工具拒绝并提示 Record 元素必须按固定最大槽位展开

#### Scenario: Reference vector rejected
- **WHEN** 带 ref 的字段声明 vector 类型
- **THEN** 工具拒绝该组合
