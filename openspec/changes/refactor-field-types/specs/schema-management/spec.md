## ADDED Requirements

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
