## MODIFIED Requirements

### Requirement: Generate .fbs files from schema
工具 SHALL 从 `schemas/*.yaml` 自动生成对应的 `.fbs` 文件，输出至 `output/fbs/`。每张有 i18n 字段的表额外生成 I18n 变体结构。同时生成 `container.fbs` 定义 Bundle 容器。

#### Scenario: Basic table fbs generation
- **WHEN** schema 定义 item 表含 id(int32)、name(string)、price(float) 字段
- **THEN** 生成 `item.fbs`，包含 `table Item` 和 `table ItemTable { items: [Item]; }` 定义

#### Scenario: Enum field fbs generation
- **WHEN** schema 含 `Rarity: ItemRarity` 枚举字段（`config/types/ItemRarity.yaml`，values `[common, rare, epic]`）
- **THEN** `item.fbs` 包含 `enum ItemRarity: byte { common = 0, rare = 1, epic = 2 }`，Item 表中字段类型为 `ItemRarity`

#### Scenario: Nested record generated as FlatBuffers table
- **WHEN** schema 含 `DropRange: ItemDropRange` 记录字段（`config/types/ItemDropRange.yaml`，字段 `min/max` 均为 int32）
- **THEN** `item.fbs` 包含 `table ItemDropRange { min: int32; max: int32; }`，Item 中字段类型为 `ItemDropRange`（使用 FlatBuffers table，而非 struct）

#### Scenario: Vector of primitives generated as vector
- **WHEN** schema 含 `Tags: vector<int32>` 字段
- **THEN** Item 中该字段生成为 `tags: [int32]`

#### Scenario: Vector of enum generated as vector of enum
- **WHEN** schema 含 `vector<ItemRarity>` 字段
- **THEN** 生成对应 enum 类型，字段为 `[ItemRarity]` vector

#### Scenario: i18n variant generation
- **WHEN** item schema 中 name 字段标记 `i18n: true`
- **THEN** `item.fbs` 额外包含 `table ItemI18nEntry { id: int32; name: string; }` 和 `table ItemI18nTable { entries: [ItemI18nEntry]; }`

#### Scenario: server_only field excluded from fbs
- **WHEN** 字段标记 `server_only: true`
- **THEN** 该字段不出现在生成的 .fbs 中

#### Scenario: container.fbs generated
- **WHEN** 工具初始化或 schema 更新后
- **THEN** 生成 `output/fbs/container.fbs`，包含 `BundledTable` 和 `DataBundle` 定义

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
