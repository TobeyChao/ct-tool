## MODIFIED Requirements

### Requirement: Generate .fbs files from schema
工具 SHALL 从 canonical Workspace 生成合法 `.fbs` 与 Bundle 容器。全部具名 Record 和 Enum SHALL 按稳定依赖顺序在唯一的 `types.fbs` 中各定义一次；每个 Table `.fbs` SHALL include 该共享文件并只定义 Table 自身、索引和必要容器结构。Table 和 Record SHALL 均生成 FlatBuffers table，Enum wire type SHALL 固定为 `byte`；字段 SHALL 支持 scalar、具名 Enum、具名 Record 与 vector；有 i18n 字段的 Table SHALL 生成对应变体，Table 顶层 `server_only` 字段 SHALL 从客户端 FBS 排除。

#### Scenario: Basic table fbs generation
- **WHEN** Item Table 含 Id(int32)、Name(string)、Price(float)
- **THEN** 生成包含 `table Item` 与对应集合容器的 FBS

#### Scenario: Named enum field fbs generation
- **WHEN** Item.Rarity 引用 ItemRarity Enum
- **THEN** `types.fbs` 只生成一次 `enum ItemRarity : byte` 定义，Item schema include 它并让字段使用该类型

#### Scenario: Record generated as FlatBuffers table
- **WHEN** 工作区定义 DropReward Record 并被 Table 字段引用
- **THEN** `types.fbs` 生成一次 `table DropReward`，所有使用处引用该 table，绝不生成同名 native struct 或复制定义

#### Scenario: Vector of primitives generated
- **WHEN** 字段类型为 `vector<int32>`
- **THEN** FBS 字段类型为 `[int32]`

#### Scenario: Vector of record generated
- **WHEN** 字段类型为 `vector<DropReward>`
- **THEN** FBS 字段类型为 `[DropReward]`，Record 定义只生成一次

#### Scenario: i18n variant generation
- **WHEN** Item 含 i18n string 字段
- **THEN** 生成仅含主键和 i18n 字段的确定性变体结构

#### Scenario: server_only field excluded from fbs
- **WHEN** 字段标记 `server_only`
- **THEN** 该字段不出现在客户端 FBS 与 Binary 中

#### Scenario: container.fbs generated
- **WHEN** Workspace Apply 或 export 生成 FBS
- **THEN** 同时生成与全部 Table 产物一致的 Bundle 容器定义

#### Scenario: Shared type dependencies are ordered deterministically
- **WHEN** DropReward Record 引用 ItemRarity Enum，且 Item 与 Quest 都引用 DropReward
- **THEN** `types.fbs` 按确定性顺序定义依赖且两个 Table schema 均引用同一符号，重复执行产生逐字节相同的 schema 文件

#### Scenario: Shared symbol collision blocks generation
- **WHEN** 两个资源会生成相同 FlatBuffers 符号或共享类型依赖形成非法 include/定义关系
- **THEN** Candidate 校验在发布前失败并列出所有来源，不输出部分 `.fbs`

## ADDED Requirements

### Requirement: Serialize Record and vector Record consistently
Binary writer SHALL 按同一 canonical model 序列化单个 Record 与 `vector<Record>`，JSON、FBS、Binary 和生成 Accessor 对空元素、顺序和字段默认值 SHALL 具有一致语义。

#### Scenario: Serialize a partially filled expanded vector
- **WHEN** Excel 解析得到两个 DropReward 元素
- **THEN** JSON 含两个对象，FlatBuffers vector 长度为 2，C#/Lua Accessor 读取到相同顺序与值

### Requirement: Preserve wire type across Excel layout changes
仅修改 `excel_columns` 或 separator SHALL NOT 改变 FlatBuffers 字段类型；Change Plan SHALL 将其归类为 Excel 输入布局变化而非 Binary wire type 变化。

#### Scenario: Expand writable record groups
- **WHEN** `excel_columns` 从 3 增加到 5 且 Type Expression 不变
- **THEN** 生成的 FBS 字段声明不变，Binary/Accessor 兼容性检查通过
