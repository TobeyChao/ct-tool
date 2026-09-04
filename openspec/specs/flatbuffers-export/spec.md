## Purpose

把配表 schema 与数据导出为 FlatBuffers 相关产物（`.fbs` 定义、按语言的二进制 Bundle）以及与之配套的 canonical C#/Lua 读取 Accessor，供客户端零拷贝读取配置。

## Requirements

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

### Requirement: Generate canonical C# Accessor with query API and typed fields
工具 SHALL 为每张表生成 C# Accessor，与 canonical 指针式 reader（`WireReader`）对齐 harmony 的接口与性能：行句柄持 `IntPtr`；每表提供 `Count/ByID/ByIndex` 查询；字段类型化暴露（enum 返回 `(EnumType)`，跨表 `ref` 提供类型化访问）；vector 字段暴露为**单一可索引/可枚举容器**（`NArray<T>`/`NStructArray<T>`）并在构造时捕获向量基址（`VecBase`）实现 O(1) 直读。i18n 字段按当前语言表读取。

#### Scenario: C# Accessor exposes per-table query API
- **WHEN** 生成 `ItemAccessor.cs`
- **THEN** 包含 `public static int Count`、`public static ItemRow? ByID(int id)`、`public static ItemRow? ByIndex(int i)`（越界返回 null）；若配置了 Code/Group 索引，还包含 `ByCode`/`ByGroupKey`

#### Scenario: C# row is a pointer handle
- **WHEN** 通过 `ItemAccessor.ByID(id)` 取到一行
- **THEN** `ItemRow` 持有行对象指针，字段读取用 `WireReader.I32(_row, slot)`（`slot = 4 + 2*字段序`）

#### Scenario: C# enum field typed
- **WHEN** item 表有 `Rarity: ItemRarity` 枚举字段
- **THEN** 生成 `public ItemRarity Rarity => (ItemRarity)WireReader.I8(_row, slot);`（返回类型化枚举，而非裸 int）

#### Scenario: C# cross-table ref typed accessor
- **WHEN** item 表有 `ItemTypeId: int32` 且 `ref: ItemType.Id`
- **THEN** 保留裸 id 快路径 `public int ItemTypeId => WireReader.I32(_row, slot)`，并生成类型化访问 `public ItemTypeRow ItemType => ItemTypeAccessor.ByID(ItemTypeId);`（底层用 id→行缓存，避免每字段 P/Invoke）

#### Scenario: C# vector field as single container
- **WHEN** item 表有 `Tags: vector<int32>`
- **THEN** 生成 `public NArray<int> Tags => new NArray<int>(WireReader.VecBase(_row, slot), count);`，支持 `Tags.Length`、`Tags[i]`、`foreach`；`vector<Record>` 生成 `NStructArray<T>`；`vector<string>` 生成 `NStructArray<NString>`

### Requirement: Generate canonical Lua Accessor with query API and typed fields
工具 SHALL 为每张表生成 Lua Accessor，与 canonical reader（`GD`）对齐 harmony 的接口与性能：提供 `M.Count/M.ByID/M.ByIndex` 查询，enum 返回类型化值，跨表 `ref` 提供类型化访问，vector 返回惰性表（数组值）经基址捕获读取。i18n 字段按当前语言表读取。

#### Scenario: Lua Accessor exposes per-table query API
- **WHEN** 生成 `ItemAccessor.lua`
- **THEN** 包含 `M.Count`、`M.ByID(id)`、`M.ByIndex(i)`；若配置索引还包含 `M.ByCode`/`M.ByGroupKey`

#### Scenario: Lua enum field typed
- **WHEN** item 表有 `Rarity: ItemRarity` 枚举字段
- **THEN** 生成返回类型化值（数字或字符串映射，按 Lua 消费约定）的 `Rarity` 访问器，而非裸数字

#### Scenario: Lua cross-table ref typed accessor
- **WHEN** item 表有 `ref: ItemType.Id`
- **THEN** 生成 `M.ItemType()` 类型化访问，底层用 id→行缓存；保留裸 id 快路径

### Requirement: Vector container captures the vector base once
工具 SHALL 让 vector 容器在构造时一次性捕获向量基址（读端 `VecBase(obj, slot)`），使 `[i]` 读取为 O(1) 直读，而非每元素重复解析 FlatBuffers vtable/offset。

#### Scenario: vector access does not re-resolve per element
- **WHEN** 访问 `row.Tags[i]`
- **THEN** 容器持有基址，`[i]` 直接按 `base + i*stride` 读取；不逐元素调用 `WireReader.Indirect`

#### Scenario: container construction resolves base once
- **WHEN** 创建 `NArray<int>`/`NStructArray<T>`
- **THEN** 构造器调用一次 `VecBase(obj, slot)` 获取基址与 `len`，后续索引不再解析 vtable

### Requirement: Cross-table ref typed accessor is backed by cache
工具 SHALL 为跨表 `ref` 生成类型化访问，其底层用**一次建立的 id→行缓存**，避免每个字段访问都触发原生 P/Invoke（对齐 harmony 的 `{RefType}.ByID(id)`，但不牺牲性能）。

#### Scenario: ref typed lookup uses cached id→row
- **WHEN** 首次调用 `item.ItemType` 访问目标表
- **THEN** 通过目标表 `ByID` 的 id→行缓存返回目标行；后续命中缓存，不重复 P/Invoke

### Requirement: Reader runs standalone and String fields are interned
reader SHALL 作为独立运行时（纯 C# + unsafe 读 FlatBuffers），不依赖 Unity/游戏；并 SHALL 提供字符串驻留（`NStringCache` 等价物），使相同字符串只分配一次。

#### Scenario: reader can be exercised without the game
- **WHEN** 在 `test-proj/ConfigAccessorBench`（无 Unity/游戏依赖）加载 `gd/output/binary/data_zh.bin`
- **THEN** 能通过 reader 的引导层取表、按 id/行读取字段与向量，正确性校验通过

#### Scenario: repeated string read reuses allocation
- **WHEN** 多次读取同一行的 `Name` 字段
- **THEN** 返回驻留后的同一字符串引用，降低 GC 分配；驻留随表版本/语言切换失效

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
