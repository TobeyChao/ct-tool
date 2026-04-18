## MODIFIED Requirements

### Requirement: Calculate maximum nesting depth
工具 SHALL 根据 schema 计算每张表的最大嵌套深度，用于确定 Excel 模板头部行数（`max_nesting_depth + 1`）。

#### Scenario: Flat table depth
- **WHEN** 所有字段均为基础类型、enum 或 array
- **THEN** `max_nesting_depth = 1`，头部行数 = 2

#### Scenario: Single level struct depth
- **WHEN** 表含 `drop_range: struct{min: int32, max: int32}`，无更深嵌套
- **THEN** `max_nesting_depth = 2`，头部行数 = 3

#### Scenario: Nested struct depth
- **WHEN** 表含 `position: struct{area: struct{x: float, y: float}, z: float}`
- **THEN** `max_nesting_depth = 3`，头部行数 = 4

#### Scenario: Depth calculation rule
- **WHEN** 计算字段深度
- **THEN** 基础类型/enum/array = depth 1；struct = 1 + max(子字段 depth)；表的 max_nesting_depth = max(所有字段 depth)
