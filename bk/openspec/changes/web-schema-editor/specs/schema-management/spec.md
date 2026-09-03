## MODIFIED Requirements

### Requirement: Load schema from YAML files

工具 SHALL 从 `config/schemas/` 目录加载所有 `*.yaml` 文件，使用 Pydantic 模型校验结构完整性；同时 SHALL 从 `config/types/` 加载类型库（`TypeDef`，见 `schema-editor/type-library`）并在字段解析时校验 `type_ref` / `element_type_ref` 引用存在。加载失败时报告具体文件名和错误原因。

#### Scenario: Valid schema loaded
- **WHEN** `config/schemas/item.yaml` 包含合法的 table/primary/fields 定义
- **THEN** 工具成功解析并构建对应的 TableSchema 对象

#### Scenario: Schema missing required field
- **WHEN** YAML 文件缺少 `primary` 或 `fields` 字段
- **THEN** 工具报错并指明文件名和缺失字段，终止执行

#### Scenario: Duplicate table name
- **WHEN** 两个 schema 文件定义了相同的 `table` 名称
- **THEN** 工具报错指明冲突的文件名，终止执行

#### Scenario: 类型引用缺失
- **WHEN** 字段 `type_ref` 指向类型库中不存在的类型
- **THEN** 加载报错指明字段与缺失的类型名，终止执行

### Requirement: Build cross-table reference dependency graph

工具 SHALL 分析所有 schema 中的 `ref` 字段，构建有向依赖图，用于确定导出和校验顺序；依赖图 SHALL 同时覆盖类型字段间的 struct 嵌套引用（`type_ref`），并对类型图做环检测（递归 struct 环报错指明路径）。

#### Scenario: Valid reference graph
- **WHEN** item 的 `item_type_id` 字段引用 `item_type.id`
- **THEN** 依赖图中 item → item_type 存在边，item_type 先于 item 处理

#### Scenario: Circular reference detected
- **WHEN** 表 A 引用表 B，表 B 引用表 A
- **THEN** 工具报错指明循环路径（A → B → A），终止执行

#### Scenario: 类型 struct 环
- **WHEN** 类型 A 的字段引用类型 B，B 的字段又引用 A
- **THEN** 加载报错指明环路径（A → B → A），终止执行

### Requirement: Validate field type definitions

Schema 中每个字段 SHALL 声明合法的类型（`int32`, `int64`, `float`, `double`, `bool`, `string`, `enum`, `struct`, `vector`；原 `array` 已按 R2 改名为 `vector`）及可选标记（`i18n`, `ref`, `server_only`）。

#### Scenario: Invalid field type
- **WHEN** schema 字段 type 为 `integer`（非法值）
- **THEN** 工具报错指明文件名、字段名和合法类型列表

#### Scenario: 旧名 array 被拒绝
- **WHEN** schema 字段 type 为 `array`
- **THEN** 工具报错并提示改用 `vector`

### Requirement: Validate struct field definitions

`type: struct` 的字段 SHALL 包含非空的 `fields` 列表，子字段类型仅允许标量或嵌套 struct（FlatBuffers 约束收紧：不得含 string / vector / enum 等非标量，允许通过 `type_ref` 嵌套具名 struct）。

#### Scenario: Valid struct definition
- **WHEN** schema 定义 `type: struct, fields: [{name: min, type: int32}, {name: max, type: int32}]`
- **THEN** 工具成功加载，struct 深度计入最大嵌套深度计算

#### Scenario: Struct missing fields
- **WHEN** schema 定义 `type: struct` 但无 `fields` 键
- **THEN** 工具报错指明文件名和字段名

#### Scenario: struct 含非标量字段被拒
- **WHEN** struct 子字段类型为 string / vector / enum
- **THEN** 工具报错（FlatBuffers struct 仅允许标量或嵌套 struct）

### Requirement: Validate vector field definitions（原 Validate array field definitions）

`type: vector` 的字段 SHALL 包含元素声明：标量元素用 `element_type`，具名类型元素用 `element_type_ref`；元素允许基础类型、具名 enum 或具名 struct（`element_type_ref`，需配 `fixed_length` 定长）；嵌套 vector 不允许。支持可选的 `separator` 配置（默认 `,`）。

#### Scenario: Valid primitive vector
- **WHEN** schema 定义 `type: vector, element_type: int32`
- **THEN** 工具成功加载

#### Scenario: Vector with enum element
- **WHEN** schema 定义 `type: vector, element_type_ref: Rarity`
- **THEN** 工具成功加载，数据校验时逐元素校验枚举值

#### Scenario: vector<struct> 需定长
- **WHEN** schema 定义 `type: vector, element_type_ref: DropRange` 且无 `fixed_length`
- **THEN** 工具报错提示 vector 元素为 struct 时必须配 `fixed_length`

#### Scenario: 嵌套 vector 拒绝
- **WHEN** schema 定义 vector 元素为 vector
- **THEN** 工具在 schema 加载阶段报错：嵌套 vector 不支持

#### Scenario: Custom separator
- **WHEN** schema 定义 `separator: "|"`，Excel 填写 `"1|2|5"`
- **THEN** 工具按 `|` 分割，解析为 `[1, 2, 5]`

## ADDED Requirements

### Requirement: 撞名不变量加载时校验

类型名 SHALL 不得与任何表内字段名相同；该不变量 SHALL 在「加载 schema + 类型库」时统一校验（从 fbs 生成后检查前移），命中即报错提示改名。

#### Scenario: 类型名撞字段名
- **WHEN** 类型库存在类型 `Rarity` 且某表字段名为 `Rarity`
- **THEN** 加载报错指明冲突的类型与字段，提示改名
