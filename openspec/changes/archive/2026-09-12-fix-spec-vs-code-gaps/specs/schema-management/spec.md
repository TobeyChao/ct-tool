## MODIFIED Requirements

### Requirement: Validate primary key type
工具 SHALL 在 schema 加载阶段校验主键字段的类型必须是 `int32`。主键在导出侧存进 4 字节索引向量、`idHash` 取 32 位、生成的 C# 查询签名恒为 `ByID(int)`，只有 `int32` 能让这条链自洽；其它类型（含 `string`、`bool`、`float`、`double`、`enum`，以及 `int8` / `int16` / `int64` / `uint*` 等其它整数标量）一律拒绝。报错 SHALL 指明表名、主键字段名与当前类型，且不得输出 Python traceback。

主键**值**（来自 Excel）SHALL 落在 `int32` 值域 `[-2147483648, 2147483647]` 内，越界由读取层的整数值域校验在解析校验阶段报为类型错误（见 `excel-processing`），SHALL NOT 留到产物生成阶段抛出 `TypeError`。

#### Scenario: Integer primary key accepted
- **WHEN** schema 定义 `primary: Id` 且 `Id` 字段 `type: int32`
- **THEN** 工具成功加载 schema，后续 validate / export / gen-template 正常执行

#### Scenario: String primary key rejected
- **WHEN** schema 定义 `primary: Code` 且 `Code` 字段 `type: string`
- **THEN** 工具在加载阶段报错，指明表名、主键字段名与当前类型（string），
  终止执行且不进入数据校验/导出阶段

#### Scenario: Other non-integer primary key rejected
- **WHEN** schema 定义 `primary: Name` 且 `Name` 字段 `type: bool`
  （或 `float`、`enum` 等其他非整数类型）
- **THEN** 工具在加载阶段报错，指明表名、主键字段名与当前类型

#### Scenario: Non-int32 integer primary key rejected
- **WHEN** schema 定义 `primary: Id` 且 `Id` 字段 `type: int64`（或 `int8`、`uint32` 等其它整数标量）
- **THEN** 工具在加载阶段报错，指明表名、主键字段名与当前类型，并说明索引向量、`idHash` 与 `ByID(int)` 均为 32 位承载
