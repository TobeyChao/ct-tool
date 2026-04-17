## ADDED Requirements

### Requirement: ct export command
`ct export` SHALL 执行增量导出流程：变更检测 → 解析 → 校验 → i18n 提取合并 → JSON/Binary 输出 → 缓存更新。

#### Scenario: Default incremental export
- **WHEN** 用户执行 `ct export`
- **THEN** 只导出 hash 变化的表，输出进度信息，成功后显示导出摘要

#### Scenario: Export specific tables
- **WHEN** 用户执行 `ct export --table item,item_type`
- **THEN** 只处理指定的表（仍走增量检测）

#### Scenario: Export with specific languages
- **WHEN** 用户执行 `ct export --lang zh,en`
- **THEN** 只导出 zh 和 en 语言的产物，忽略其他配置的语言

#### Scenario: Validation failure stops export
- **WHEN** 某张表校验失败
- **THEN** 该表不生成任何产物，其他无错误的表正常导出，退出码非 0

### Requirement: ct validate command
`ct validate` SHALL 只执行解析和校验流程，不生成任何输出文件。

#### Scenario: Validate all tables
- **WHEN** 用户执行 `ct validate`
- **THEN** 校验所有表，报告错误总数，不修改任何文件

#### Scenario: Validate passes
- **WHEN** 所有表校验通过
- **THEN** 输出 `✓ 所有表校验通过（共 N 张表）`，退出码 0

### Requirement: ct gen-template command
`ct gen-template` SHALL 根据 schema 生成或更新 Excel 文件的模板头部，不影响数据行。

#### Scenario: Generate template for all tables
- **WHEN** 用户执行 `ct gen-template --all`
- **THEN** 为所有 schema 对应的 Excel 创建或更新头部

### Requirement: ct status command
`ct status` SHALL 对比当前 Excel hash 与缓存，显示哪些表有未导出的变更。

#### Scenario: Show pending changes
- **WHEN** item.xlsx 已修改但未导出
- **THEN** 输出 `[changed] item` 列表；无变更时输出 `所有表已是最新`

### Requirement: Designer-friendly error messages
所有校验错误和运行时错误 SHALL 以中文输出，包含表名、行号、字段名，不暴露 Python 堆栈跟踪给非技术用户。程序员可通过 `--verbose` 查看详细堆栈。

#### Scenario: User-friendly validation error
- **WHEN** item.xlsx 第 5 行 price 字段类型错误
- **THEN** 输出：`❌ [item.xlsx] 第 5 行 price：期望 float，实际值 "贵"`，而非 Python 异常

#### Scenario: Verbose mode for developers
- **WHEN** 发生未预期异常且用户使用 `--verbose` 标志
- **THEN** 输出完整 Python traceback
