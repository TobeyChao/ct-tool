## ADDED Requirements

### Requirement: Load schema from YAML files
工具 SHALL 从 `config/schemas/` 目录加载所有 `*.yaml` 文件，使用 Pydantic 模型校验结构完整性。加载失败时报告具体文件名和错误原因。

#### Scenario: Valid schema loaded
- **WHEN** `config/schemas/item.yaml` 包含合法的 table/primary/fields 定义
- **THEN** 工具成功解析并构建对应的 TableSchema 对象

#### Scenario: Schema missing required field
- **WHEN** YAML 文件缺少 `primary` 或 `fields` 字段
- **THEN** 工具报错并指明文件名和缺失字段，终止执行

#### Scenario: Duplicate table name
- **WHEN** 两个 schema 文件定义了相同的 `table` 名称
- **THEN** 工具报错指明冲突的文件名，终止执行

### Requirement: Build cross-table reference dependency graph
工具 SHALL 分析所有 schema 中的 `ref` 字段，构建有向依赖图，用于确定导出和校验顺序。

#### Scenario: Valid reference graph
- **WHEN** item 的 `item_type_id` 字段引用 `item_type.id`
- **THEN** 依赖图中 item → item_type 存在边，item_type 先于 item 处理

#### Scenario: Circular reference detected
- **WHEN** 表 A 引用表 B，表 B 引用表 A
- **THEN** 工具报错指明循环路径（A → B → A），终止执行

### Requirement: Topological sort for processing order
工具 SHALL 对依赖图进行拓扑排序，输出确定性的表处理顺序，被引用表始终先于引用方处理。

#### Scenario: Correct ordering
- **WHEN** 存在 category → item_type → item 的引用链
- **THEN** 处理顺序为 category, item_type, item（或等价的合法顺序）

### Requirement: Validate field type definitions
Schema 中每个字段 SHALL 声明合法的类型（`int32`, `int64`, `float`, `double`, `bool`, `string`, `enum`, `struct`, `array`）及可选标记（`i18n`, `ref`, `server_only`）。

#### Scenario: Invalid field type
- **WHEN** schema 字段 type 为 `integer`（非法值）
- **THEN** 工具报错指明文件名、字段名和合法类型列表

### Requirement: Validate enum field definitions
`type: enum` 的字段 SHALL 包含非空的 `values` 列表，每个值为合法标识符字符串。工具在 schema 加载阶段校验，而非数据校验阶段。

#### Scenario: Valid enum definition
- **WHEN** schema 定义 `type: enum, values: [common, rare, epic]`
- **THEN** 工具成功加载，生成对应枚举类型

#### Scenario: Empty enum values
- **WHEN** schema 定义 `type: enum, values: []`
- **THEN** 工具在加载阶段报错指明文件名和字段名

#### Scenario: Enum data validation
- **WHEN** Excel 中该字段填写了 `legendary`，但 values 中不含此值
- **THEN** 校验报错：`[item.xlsx] 第N行 rarity：值 "legendary" 不在枚举列表 [common, rare, epic] 中`

### Requirement: Validate struct field definitions
`type: struct` 的字段 SHALL 包含非空的 `fields` 列表，子字段类型仅允许基础类型和 `enum`（不允许再嵌套 `array`，允许嵌套 `struct`）。

#### Scenario: Valid struct definition
- **WHEN** schema 定义 `type: struct, fields: [{name: min, type: int32}, {name: max, type: int32}]`
- **THEN** 工具成功加载，struct 深度计入最大嵌套深度计算

#### Scenario: Struct missing fields
- **WHEN** schema 定义 `type: struct` 但无 `fields` 键
- **THEN** 工具报错指明文件名和字段名

### Requirement: Validate array field definitions
`type: array` 的字段 SHALL 包含 `element` 声明，`element` 类型仅允许基础类型和 `enum`，不允许 `struct`。支持可选的 `separator` 配置（默认 `,`）。

#### Scenario: Valid primitive array
- **WHEN** schema 定义 `type: array, element: int32`
- **THEN** 工具成功加载

#### Scenario: Array with enum element
- **WHEN** schema 定义 `type: array, element: enum, values: [common, rare]`
- **THEN** 工具成功加载，数据校验时逐元素校验枚举值

#### Scenario: array<struct> rejected
- **WHEN** schema 定义 `type: array, element: struct`
- **THEN** 工具在 schema 加载阶段报错：`array<struct> 不支持，请使用独立子表 + ref 实现一对多关系`

#### Scenario: Custom separator
- **WHEN** schema 定义 `separator: "|"`，Excel 填写 `"1|2|5"`
- **THEN** 工具按 `|` 分割，解析为 `[1, 2, 5]`

### Requirement: Validate field flag combinations
工具 SHALL 在 schema 加载阶段校验字段标记的合法组合，禁止语义冲突的标记同时存在。

#### Scenario: i18n + server_only rejected
- **WHEN** schema 字段同时标记 `i18n: true` 和 `server_only: true`
- **THEN** 工具在 schema 加载阶段报错：`字段 {name} 不能同时标记 i18n 和 server_only（i18n 字段用于客户端 UI，server_only 字段不进入 Binary）`

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
