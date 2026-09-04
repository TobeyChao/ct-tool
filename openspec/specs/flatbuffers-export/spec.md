## Requirements

### Requirement: Generate .fbs files from schema
工具 SHALL 从 `schemas/*.yaml` 自动生成对应的 `.fbs` 文件，输出至 `output/fbs/`。每张有 i18n 字段的表额外生成 I18n 变体结构。同时生成 `container.fbs` 定义 Bundle 容器。

#### Scenario: Basic table fbs generation
- **WHEN** schema 定义 item 表含 id(int32)、name(string)、price(float) 字段
- **THEN** 生成 `item.fbs`，包含 `table Item` 和 `table ItemTable { items: [Item]; }` 定义

#### Scenario: Enum field fbs generation
- **WHEN** schema 含 `type: enum, values: [common, rare, epic]` 的 rarity 字段
- **THEN** `item.fbs` 包含 `enum Rarity: byte { common = 0, rare = 1, epic = 2 }`，Item 表中字段类型为 `Rarity`

#### Scenario: Nested struct generated as FlatBuffers table
- **WHEN** schema 含 `type: struct, fields: [{name: min, type: int32}, {name: max, type: int32}]` 的 drop_range 字段
- **THEN** `item.fbs` 包含 `table DropRange { min: int32; max: int32; }`，Item 中字段类型为 `DropRange`（使用 FlatBuffers table，而非 struct）

#### Scenario: Array of primitives generated as vector
- **WHEN** schema 含 `type: array, element: int32` 的 tags 字段
- **THEN** Item 中该字段生成为 `tags: [int32]`

#### Scenario: Array of enum generated as vector of enum
- **WHEN** schema 含 `type: array, element: enum, values: [common, rare]` 的字段
- **THEN** 生成对应 enum 类型，字段为 `[EnumType]` vector

#### Scenario: i18n variant generation
- **WHEN** item schema 中 name 字段标记 `i18n: true`
- **THEN** `item.fbs` 额外包含 `table ItemI18nEntry { id: int32; name: string; }` 和 `table ItemI18nTable { entries: [ItemI18nEntry]; }`

#### Scenario: server_only field excluded from fbs
- **WHEN** 字段标记 `server_only: true`
- **THEN** 该字段不出现在生成的 .fbs 中

#### Scenario: container.fbs generated
- **WHEN** 工具初始化或 schema 更新后
- **THEN** 生成 `output/fbs/container.fbs`，包含 `BundledTable` 和 `DataBundle` 定义

### Requirement: Compile .fbs via flatc for C++, C#, and Lua
工具 SHALL 调用 `flatc` 分别为三种语言编译生成的 .fbs 文件：C++ 头文件输出至 `output/generated/cpp/`，C# 文件输出至 `output/generated/csharp/`，Lua 文件输出至 `output/generated/lua/`。

#### Scenario: flatc not found
- **WHEN** `config/global.yaml` 中配置的 `flatc_path` 指向的文件不存在
- **THEN** 报错并输出安装指引（提示将 flatc 放入项目目录如 `tools/flatc`），跳过编译步骤（不影响 JSON 导出）

#### Scenario: C++ header generated
- **WHEN** flatc 可用，item.fbs 合法
- **THEN** 生成 `output/generated/cpp/item_generated.h`

#### Scenario: C# file generated
- **WHEN** flatc 可用，item.fbs 合法
- **THEN** 生成 `output/generated/csharp/ItemGenerated.cs`（包含 `ItemTable`、`Item`、`ItemI18nEntry`、`ItemI18nTable` 类）

#### Scenario: Lua file generated
- **WHEN** flatc 可用，item.fbs 合法
- **THEN** 生成 `output/generated/lua/item_generated.lua`

### Requirement: Generate C# Accessor with i18n logic
工具 SHALL 为每张表生成 C# Accessor 类，封装主包 + i18n 包双查找逻辑，上层业务代码访问 i18n 字段时无需感知双包结构。C# Accessor 调用手写的 `GDNative` P/Invoke 接口获取原始 FlatBuffers 字节，使用 `ByteBuffer` 零拷贝读取。Accessor 提供 `Preload()` 静态方法：构建 `Dictionary<int, int>`（id → 行索引）+ 将所有 string 字段 eager materialize 到 `string[]` 数组；标量字段仍从 ByteBuffer 读取（天然零 GC）。`Preload()` 后所有字段访问零 GC。

#### Scenario: C# Accessor generated
- **WHEN** item 表有 i18n 字段 name
- **THEN** 生成 `output/generated/csharp/ItemAccessor.cs`，包含 `ItemAccessor` 类；调用 `GetName(id)` 时优先返回 i18n 包中的译文，缺失时回退主包原文

#### Scenario: C# Accessor for non-i18n table
- **WHEN** item_type 表无 i18n 字段
- **THEN** 生成 `output/generated/csharp/ItemTypeAccessor.cs`，所有字段直接透传主包，无 i18n 查找逻辑

#### Scenario: C# non-i18n field passthrough
- **WHEN** 访问 `price`（非 i18n 字段）
- **THEN** 直接返回主包中的值，不查询 i18n 包

#### Scenario: C# Preload materializes strings
- **WHEN** 调用 `ItemAccessor.Preload()`
- **THEN** 遍历主包所有行，构建 `Dictionary<int, int>`（id → 行索引）；所有 string 字段（如 name）被 eager materialize 到 `string[]` 数组（每个字符串只分配一次）；标量字段（如 price）不预取，仍从 ByteBuffer 按需读取；若 i18n 包存在，同样 materialize i18n string 字段到独立 `string[]`

#### Scenario: Zero GC after Preload
- **WHEN** `Preload()` 完成后调用 `GetName(id)` 或 `GetPrice(id)`
- **THEN** `GetName(id)` 返回已存入 `string[]` 的对象引用，零 GC；`GetPrice(id)` 从 ByteBuffer 读取标量，零 GC；整个字段访问路径无托管堆分配

#### Scenario: Access before Preload throws
- **WHEN** 未调用 `Preload()` 直接调用 `GetName(id)` 等字段访问方法
- **THEN** 抛出 `InvalidOperationException("ItemAccessor.Preload() must be called before accessing fields")`，不做 lazy init

### Requirement: Generate Lua Accessor with i18n logic
工具 SHALL 为每张表生成 Lua Accessor 模块，封装主包 + i18n 包双查找逻辑，通过 xLua 注册的 C++ 函数获取原始字节。Lua Accessor 与 C# Accessor 逻辑对称，独立运行，不依赖 C# 层。`M.preload()` 构建 id→行索引的 Lua table，并将 string 字段缓存为 Lua string（驻留复用），后续访问 O(1) 且不再触发 xLua bridge 调用。

#### Scenario: Lua Accessor generated
- **WHEN** item 表有 i18n 字段 name
- **THEN** 生成 `output/generated/lua/item_accessor.lua`，`M.get_name(id)` 优先返回 i18n 译文，缺失时回退主包

#### Scenario: Lua Accessor for non-i18n table
- **WHEN** item_type 表无 i18n 字段
- **THEN** 生成 `output/generated/lua/item_type_accessor.lua`，所有字段直接透传主包

#### Scenario: Lua preload materializes strings and builds index
- **WHEN** 调用 `M.preload()`
- **THEN** 遍历主包所有行，构建 `_main_index`（id → 行索引）；string 字段缓存为 Lua string 存入 `_main_strings`（二维 table，`[row][field]`）；若 i18n 包存在同样构建 `_i18n_index` 和 `_i18n_strings`；后续 `M.get_name(id)` 直接查 Lua table，不再调用 xLua bridge

### Requirement: Write primary language Binary Bundle
工具 SHALL 为主语言构建包含所有表完整数据的 FlatBuffers Bundle，输出 `output/binary/data_{primary}.bin`。Bundle 结构为 `DataBundle { tables: [BundledTable] }`，每个 BundledTable 的 `data` 为对应表的原始 FlatBuffers bytes。

#### Scenario: Full bundle written
- **WHEN** 导出 zh（主语言），item 和 item_type 两张表
- **THEN** `data_zh.bin` 包含两个 BundledTable，name 分别为 "item" 和 "item_type"

### Requirement: Write secondary language i18n-only Binary Bundle
工具 SHALL 为次语言只构建包含 i18n 变体表的 Bundle，输出 `output/binary/data_{lang}.bin`，只包含有 i18n 字段的表的 I18n 变体。

#### Scenario: i18n-only bundle written
- **WHEN** 导出 en（次语言），item 有 i18n 字段，item_type 无 i18n 字段
- **THEN** `data_en.bin` 只包含 BundledTable name="item_i18n"，不含 item_type

#### Scenario: No i18n tables
- **WHEN** 所有表均无 i18n 字段，请求导出次语言
- **THEN** 不生成次语言 .bin 文件，记录 info 日志

### Non-Requirement: C++ runtime code is hand-written
工具 SHALL NOT 生成任何 C++ 运行时代码。以下均为手写代码，由游戏工程维护，不随配表变更而变动：
- `GD_Load` / `GD_GetMainBytes` / `GD_GetI18nBytes` / `GD_Unload` C API（集成进 xLua DLL）
- xLua 注册代码：`lua["GD"]["Load"]` / `lua["GD"]["GetMainBytes"]` 等

工具仅生成：
- `.fbs` → `flatc --cpp` 生成的类型头文件（`output/generated/cpp/`）
- C# Accessor（`output/generated/csharp/{Table}Accessor.cs`）
- Lua Accessor（`output/generated/lua/{table}_accessor.lua`）

#### Scenario: No C++ accessor generated
- **WHEN** 工具完成所有导出步骤
- **THEN** `output/generated/cpp/` 目录仅包含 `flatc --cpp` 生成的头文件，无工具自行生成的 C++ 源文件

#### Scenario: Lua preload access before preload throws
- **WHEN** 未调用 `M.preload()` 直接调用 `M.get_name(id)`
- **THEN** 抛出错误 `"item_accessor.preload() must be called before accessing fields"`
