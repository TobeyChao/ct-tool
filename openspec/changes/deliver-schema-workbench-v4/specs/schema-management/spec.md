## MODIFIED Requirements

### Requirement: Load schema from YAML files
工具 SHALL 从 `config/schemas/*.yaml` 加载 Table，从 `config/types/*.yaml` 加载具名 Record 与 Enum，并用同一 canonical repository 构建 WorkspaceSnapshot。加载失败 SHALL 报告来源文件、资源 kind 与原因；所有资源名称 SHALL 在统一命名域中唯一。

#### Scenario: Valid table schema loaded
- **WHEN** `config/schemas/Item.yaml` 包含合法的 table、primary 和 fields 定义
- **THEN** 工具成功解析为 Table 资源并保留来源文件位置

#### Scenario: Valid named types loaded
- **WHEN** `config/types/DropReward.yaml` 与 `config/types/ItemRarity.yaml` 分别定义 Record 和 Enum
- **THEN** 工具加载两个具名资源，Table 字段可将 named Type Expression 解析到唯一目标

#### Scenario: Schema missing required field
- **WHEN** 任一 Table、Record 或 Enum YAML 缺少其 kind 所需的字段
- **THEN** 工具报错并指明文件、资源 kind 和缺失字段，终止执行

#### Scenario: Duplicate resource name across repositories
- **WHEN** `config/schemas/Item.yaml` 与 `config/types/Item.yaml` 定义相同资源名
- **THEN** 工具报错并列出两个冲突来源，终止执行

### Requirement: Validate field type definitions
Schema 中每个字段 SHALL 声明可解析为 canonical Type Expression 的合法类型；首版支持 scalar、具名 Enum、具名 Record 与单层 vector 修饰，并支持可选 `i18n`、`ref`、`server_only`、comment 和 Excel 输入布局。产品 loader SHALL 拒绝旧 `array`、表示 FlatBuffers table 的内联 `struct` 与内联 Enum values，并返回文件与字段位置；产品代码不得兼容读取、自动转换或写出旧格式。

#### Scenario: Invalid field type
- **WHEN** Schema 字段类型为未支持的 `integer`
- **THEN** 工具报错并指明文件、资源、字段和合法类型集合

#### Scenario: Valid named record vector
- **WHEN** 字段声明为 `vector<DropReward>` 且 DropReward 是工作区 Record
- **THEN** 工具成功解析为 canonical vector(named) 表达并建立命名依赖

#### Scenario: Nested vector rejected
- **WHEN** 字段声明为 `vector<vector<int32>>`
- **THEN** 工具在加载阶段拒绝并给出使用命名 Record 包装的修复提示

#### Scenario: Old inline type rejected without mutation
- **WHEN** loader 遇到 `type: struct`、`type: array` 或字段内联 enum values
- **THEN** 工具报错并指出文件、字段和新格式示例，不修改 Schema、Excel 或 cache，也不暴露迁移命令

### Requirement: Validate enum field definitions
Enum SHALL 是具有非空值列表的具名工作区资源，每个值为合法且资源内唯一的标识符；字段 SHALL 通过 named Type Expression 引用 Enum。加载和 Candidate 校验 SHALL 在数据校验前完成资源存在性、重名和引用检查。

#### Scenario: Valid enum definition
- **WHEN** 工作区定义 ItemRarity 值 `[Common, Rare, Epic]` 且字段引用 ItemRarity
- **THEN** 工具成功加载并将字段解析为 named Enum 引用

#### Scenario: Empty enum values
- **WHEN** ItemRarity 定义空值列表
- **THEN** 工具在加载或 Candidate 阶段报错并定位 ItemRarity

#### Scenario: Enum data validation
- **WHEN** Excel 中字段填写 `Legendary` 但 ItemRarity 不包含该值
- **THEN** 校验报错并包含 Excel 行号、列、字段路径、当前值和允许值

### Requirement: Validate field flag combinations
工具 SHALL 在加载和 Candidate 校验阶段验证字段角色组合。`i18n` 只允许用于 Table 顶层 string 字段，`server_only` 只允许用于 Table 顶层字段，二者不得同时存在；首版 Record 字段不得声明 `i18n` 或 `server_only`，以保持共享类型在全部使用处具有单一语义。

#### Scenario: i18n and server only rejected together
- **WHEN** Table 顶层字段同时声明 `i18n: true` 与 `server_only: true`
- **THEN** 工具拒绝并定位字段，说明客户端本地化字段不能同时被客户端 Binary 排除

#### Scenario: Record i18n leaf rejected
- **WHEN** DropReward Record 的 Name string 字段声明 `i18n: true`
- **THEN** 工具在 Candidate 阶段拒绝并说明首版 i18n 仅支持 Table 顶层 string 字段

#### Scenario: Record server only leaf rejected
- **WHEN** 一个被多个 Table 复用的 Record 叶子声明 `server_only: true`
- **THEN** 工具拒绝该定义，不生成因使用处不同而分裂的客户端 Record 类型

#### Scenario: Top level table roles accepted
- **WHEN** Table 顶层 Name string 仅声明 i18n，另一个 DebugNote 字段仅声明 server_only
- **THEN** 两个字段通过角色校验，并分别进入既有 i18n 与客户端排除流程

### Requirement: Calculate maximum nesting depth
工具 SHALL 根据字段 Type Expression 与 Excel 输入布局计算模板头部所需深度。scalar、Enum 与单格 vector 深度为 1；展开 Record 的深度来自 Record 字段树；`vector<Record>` 展开模式 SHALL 在每个组下复用 Record 叶子路径。

#### Scenario: Flat table depth
- **WHEN** 所有字段均为 scalar、Enum 或单格 vector
- **THEN** `max_nesting_depth = 1` 且头部行数为 2

#### Scenario: Expanded record depth
- **WHEN** Table 含展开录入的 DropRange Record，Record 含 Min 与 Max scalar
- **THEN** 模板为资源字段、Record 叶子和注释生成所需层级，深度计算结果确定且可复现

#### Scenario: Vector record group depth
- **WHEN** `Rewards: vector<DropReward>` 使用展开模式且 `excel_columns: 3`
- **THEN** 三组共享相同的 Record 叶子深度，组数改变列数但不改变 canonical 运行时类型

### Requirement: Validate primary key type
Table 主键 SHALL 继续限制为 `int32` 或 `int64`。Code lookup SHALL 是基于 string 字段的辅助唯一查询契约，不替代主键、不改变引用和 Bundle 身份语义。

#### Scenario: Integer primary key accepted
- **WHEN** Table 的 Id 字段为 int32 或 int64 且被指定为 primary
- **THEN** Schema 通过主键校验，后续可另选 string 字段配置 Code lookup

#### Scenario: String primary key rejected even when it is a code
- **WHEN** Table 将 string CodeName 同时指定为 primary
- **THEN** 工具拒绝该主键并提示保留整数 primary、把 CodeName 配置为 Code lookup

#### Scenario: Other non integer primary key rejected
- **WHEN** Table 将 bool、float、double、Record 或 Enum 字段指定为 primary
- **THEN** 工具拒绝并报告表名、字段名与当前类型

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
