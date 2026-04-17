## ADDED Requirements

### Requirement: Validate field types against schema
工具 SHALL 检查每行每个字段的值是否符合 schema 声明的类型，并提供行号和字段名定位。

#### Scenario: Type mismatch detected
- **WHEN** schema 声明 `price: float`，但 Excel 该格填写了 `"贵"`
- **THEN** 报错：`[item.xlsx] 第 5 行 price 字段：期望 float，实际值 "贵"`

#### Scenario: Null in required field
- **WHEN** 非可选字段的 Excel 单元格为空
- **THEN** 报错指明表名、行号、字段名

#### Scenario: Primary key uniqueness
- **WHEN** 同一张表中存在重复的主键值
- **THEN** 报错：`[item.xlsx] 主键 id 重复：值 1001 出现在第 5、12 行`

### Requirement: Validate cross-table references
工具 SHALL 按拓扑顺序处理，校验 `ref` 字段的值在目标表的主键集合中存在。

#### Scenario: Valid reference
- **WHEN** `item.item_type_id = 3`，且 item_type 表中 id=3 存在
- **THEN** 校验通过，继续处理

#### Scenario: Invalid reference
- **WHEN** `item.item_type_id = 99`，但 item_type 表中无 id=99
- **THEN** 报错：`[item.xlsx] 第 7 行 item_type_id：引用 item_type.id=99 不存在`

#### Scenario: Referenced table not yet loaded
- **WHEN** 被引用表的 hash 未变化，从缓存读取其 id 集合
- **THEN** 校验正常进行，无需重新解析被引用表 Excel

### Requirement: Batch error reporting
工具 SHALL 在完成所有行的校验后统一报告全部错误，而非遇到第一个错误就终止。

#### Scenario: Multiple errors in one table
- **WHEN** 同一张表存在 3 处类型错误和 1 处引用错误
- **THEN** 一次性输出全部 4 条错误，方便策划批量修正
