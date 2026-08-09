## MODIFIED Requirements

### Requirement: Designer-friendly error messages
所有校验错误 SHALL 以中文输出，包含表名、**Excel 绝对行号**、列字母、
字段名、当前单元格值与错误说明，不暴露 Python 堆栈跟踪给非技术用户。
程序员可通过 `--verbose` 查看详细堆栈。

#### Scenario: User-friendly validation error with exact location
- **WHEN** item 表头（3 行）之下第 3 条数据位于 Excel 第 6 行，Price 列（列 C）填写了非数值 `"贵"`
- **THEN** 输出 `[Item.xlsx] Excel 第6行 · 列C (Price) · 当前值 '贵' → 期望 float`，而非 Python 异常

#### Scenario: Absolute row survives blank lines
- **WHEN** Excel 数据区存在空行，出错行是数据区第 3 行但 Excel 绝对行号为 7
- **THEN** 错误输出使用绝对行号 `第7行`，而非跳过空行后的相对序号

#### Scenario: Verbose mode for developers
- **WHEN** 发生未预期异常且用户使用 `--verbose` 标志
- **THEN** 输出完整 Python traceback
