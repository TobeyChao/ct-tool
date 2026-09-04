## MODIFIED Requirements

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
## ADDED Requirements

### Requirement: Load named schema resources
工具 SHALL 从配置仓库加载 Table、Record、Enum 资源并构建一个 WorkspaceSnapshot；资源 ID、名称、来源文件和类型 SHALL 可稳定定位，重复名称或缺失来源 SHALL 在加载时报告。

#### Scenario: Load a mixed workspace
- **WHEN** 配置包含多个 Table、Record 和 Enum
- **THEN** WorkspaceSnapshot 包含全部资源及确定性顺序，字段命名引用可解析到唯一目标

### Requirement: Build workspace dependency and reverse-reference graph
工具 SHALL 同时分析 named 类型引用和跨表 `ref`，构建确定性的正向依赖与反向引用图；Candidate SHALL 拒绝失效目标、非法环和删除仍被引用的节点。

#### Scenario: Record dependency chain
- **WHEN** Item 引用 DropReward，DropReward 引用 ItemRarity
- **THEN** 图中存在对应依赖边，反向查询 ItemRarity 返回 DropReward 的精确字段路径

#### Scenario: Missing named target
- **WHEN** 字段引用不存在的 Reward
- **THEN** 加载或 Candidate 校验失败并定位引用字段与缺失名称

## REMOVED Requirements

### Requirement: Validate struct field definitions
**Reason**: 旧 `struct` 实际生成 FlatBuffers table，与 FlatBuffers native struct 语义冲突；可复用对象结构由具名 Record 替代。

**Migration**: 在实现期的单次仓库切换提交中，将现有 1 个内联 struct 直接提升为具名 Record 并更新字段引用、Excel 与 fixture；产品不包含通用迁移器。native struct 不在本 change 内。

### Requirement: Validate array field definitions
**Reason**: 旧 `array` 表示的是 FlatBuffers vector，名称与目标格式冲突且不能承载统一命名类型引用。

**Migration**: 在实现期的单次仓库切换提交中，将现有 1 个 `array<T>` 直接改为 canonical `vector<T>`，同步 separator/Excel layout 与 fixture，并用切换前后 golden 验证；产品不包含兼容 reader/writer。
