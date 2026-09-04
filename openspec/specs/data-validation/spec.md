## Purpose

在导出前对工作空间数据做完整校验（字段类型强转、主键唯一、跨表 ref 外键存在性），任一问题即中止落盘，避免脏数据进入产物。

## Requirements

### Requirement: Validate field types against schema
工具 SHALL 检查每行每个字段的值是否符合 schema 声明的类型，并提供
**Excel 绝对行号、列字母和字段名**定位。

#### Scenario: Type mismatch detected with exact location
- **WHEN** schema 声明 `Price: float`，但 Excel 该格（第 6 行，列 C）填写了 `"贵"`
- **THEN** 报错：`[Item.xlsx] Excel 第6行 · 列C (Price) · 当前值 '贵' → 期望 float`

#### Scenario: Null in required field
- **WHEN** 非可选字段的 Excel 单元格为空
- **THEN** 报错指明表名、Excel 绝对行号、列字母与字段名

#### Scenario: Primary key uniqueness
- **WHEN** 同一张表中存在重复的主键值
- **THEN** 报错：`[Item.xlsx] Excel 第6行 · 列A (Id) · 当前值 1001 → 主键值 1001 重复（首次出现在第5行）`

### Requirement: Validate cross-table references
工具 SHALL 按拓扑顺序处理，校验 `ref` 字段的值在目标表的主键集合中存在。

#### Scenario: Valid reference
- **WHEN** `Item.ItemTypeId = 3`，且 ItemType 表中 id=3 存在
- **THEN** 校验通过，继续处理

#### Scenario: Invalid reference with exact location
- **WHEN** `Item.ItemTypeId = 99`，但 ItemType 表中无 id=99
- **THEN** 报错：`[Item.xlsx] Excel 第8行 · 列E (ItemTypeId) · 当前值 99 → 值 99 在引用表 ItemType.Id 中不存在`

#### Scenario: Referenced table not yet loaded
- **WHEN** 被引用表的 hash 未变化，从缓存读取其 id 集合
- **THEN** 校验正常进行，无需重新解析被引用表 Excel

### Requirement: Batch error reporting
工具 SHALL 在完成所有行的校验后统一报告全部错误，而非遇到第一个错误就终止。

#### Scenario: Multiple errors in one table
- **WHEN** 同一张表存在 3 处类型错误和 1 处引用错误
- **THEN** 一次性输出全部 4 条错误，方便策划批量修正
