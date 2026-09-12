## Purpose

把配表 schema 与数据导出为 FlatBuffers 相关产物（`.fbs` 定义、按语言的二进制 Bundle）以及与之配套的 canonical C#/Lua 读取 Accessor，供客户端零拷贝读取配置。

## Requirements

### Requirement: Generate .fbs files from schema
工具 SHALL 从 `schemas/*.yaml` 自动生成对应的 `.fbs` 文件，输出至 `output/fbs/`。每张有 i18n 字段的表额外生成 I18n 变体结构。同时生成 `container.fbs` 定义 Bundle 容器。

#### Scenario: Basic table fbs generation
- **WHEN** schema 定义 Item 表含 Id(int32)、Name(string)、Price(float) 字段
- **THEN** 生成 `Item.fbs`，包含 `table Item` 和 `table ItemTable { items: [Item]; }` 定义

#### Scenario: Enum field fbs generation
- **WHEN** schema 含 `Rarity: ItemRarity` 枚举字段（`config/types/ItemRarity.yaml`，values `[common, rare, epic]`）
- **THEN** `types.fbs` 包含 `enum ItemRarity : byte { common = 0, rare = 1, epic = 2 }`，`Item.fbs` include 它并在 Item 表中把该字段声明为 `ItemRarity`

#### Scenario: Nested record generated as FlatBuffers table
- **WHEN** schema 含 `DropRange: ItemDropRange` 记录字段（`config/types/ItemDropRange.yaml`，字段 `Min` / `Max` 均为 int32）
- **THEN** `types.fbs` 包含 `table ItemDropRange { Min: int32; Max: int32; }`，Item 中字段类型为 `ItemDropRange`（使用 FlatBuffers table，而非 struct）

#### Scenario: Vector of primitives generated as vector
- **WHEN** schema 含 `Tags: vector<int32>` 字段
- **THEN** Item 中该字段生成为 `Tags: [int32]`

#### Scenario: Vector of enum generated as vector of enum
- **WHEN** schema 含 `vector<ItemRarity>` 字段
- **THEN** 生成对应 enum 类型，字段为 `[ItemRarity]` vector

#### Scenario: i18n variant generation
- **WHEN** Item schema 中 `Name` 字段标记 `i18n: true`
- **THEN** `Item_i18n.fbs` 包含 `table ItemI18nEntry { Id: int32; Name: string; }` 和 `table ItemI18nTable { entries: [ItemI18nEntry]; }`

#### Scenario: server_only field excluded from fbs
- **WHEN** 字段标记 `server_only: true`
- **THEN** 该字段不出现在生成的 .fbs 中

#### Scenario: container.fbs generated
- **WHEN** 工具初始化或 schema 更新后
- **THEN** 生成 `output/fbs/container.fbs`，包含 `BundledTable` 和 `DataBundle` 定义

### Requirement: Generate canonical C# Accessor with query API and typed fields
工具 SHALL 为每张表生成 C# Accessor，与 canonical 指针式 reader（`WireReader`）对齐 参考实现 的接口与性能：行句柄持 `IntPtr`；每表提供 `Count/ByID/ByIndex` 查询；字段类型化暴露（enum 返回 `(EnumType)`，跨表 `ref` 提供类型化访问）；vector 字段暴露为**单一可索引/可枚举容器**（`NArray<T>`/`NStructArray<T>`）并在构造时捕获向量基址（`VecBase`）实现 O(1) 直读。i18n 字段按当前语言表读取。

#### Scenario: C# Accessor exposes per-table query API
- **WHEN** 生成 `ItemAccessor.cs`
- **THEN** 包含 `public static int Count`、`public static Item? ByID(int id)`、`public static Item? ByIndex(int i)`（越界返回 null）；若配置了 CodeName 索引，还包含 `ByCodeName`（固定指向名为 `CodeName` 的 string 字段）

#### Scenario: C# row is a pointer handle
- **WHEN** 通过 `ItemAccessor.ByID(id)` 取到一行
- **THEN** `Item` 持有行对象指针，字段读取用 `WireReader.I32(_row, slot)`（`slot = 4 + 2*字段序`）

#### Scenario: C# enum field typed
- **WHEN** Item 表有 `Rarity: ItemRarity` 枚举字段
- **THEN** 生成 `public ItemRarity Rarity => (ItemRarity)WireReader.I8(_row, slot);`（返回类型化枚举，而非裸 int）

#### Scenario: C# cross-table ref typed accessor
- **WHEN** Item 表有 `ItemTypeId: int32` 且 `ref: ItemType.Id`
- **THEN** 保留裸 id 快路径 `public int ItemTypeId => WireReader.I32(_row, slot)`，并生成类型化访问 `public ItemType ItemType => ItemTypeAccessor.ByID(ItemTypeId);`（底层用 id→行缓存，避免每字段 P/Invoke）

#### Scenario: C# vector field as single container
- **WHEN** Item 表有 `Tags: vector<int32>`
- **THEN** 生成 `public NArray<int> Tags => new NArray<int>(WireReader.VecBase(_row, slot), count);`，支持 `Tags.Length`、`Tags[i]`、`foreach`；`vector<Record>` 生成 `NStructArray<T>`；`vector<string>` 生成 `NStructArray<NString>`

### Requirement: Generated C# files live in a dedicated namespace and name row types after the table
生成的 C# 产物 SHALL 包在固定命名空间 `GameFramework.ConfigGen` 中，
SHALL NOT 把类型撒在全局命名空间里。

行类型 SHALL 以**表名本身**命名（`Item`），SHALL NOT 带 `Row` 后缀（`ItemRow`）——
带后缀的唯一作用是在全局命名空间里避开与业务类撞名，而表名（`Player`/`Shop`/`Order` …）
早晚会撞上，届时被迫改名的是业务代码；加命名空间后这个后缀就没有存在理由了。
同一规则适用于嵌套 record 类型（`ItemDropRange`）与容器实参（`NStructArray<Chest.DropReward>`）。

#### Scenario: C# output is namespaced
- **WHEN** 生成 `ItemAccessor.cs`
- **THEN** 文件含 `namespace GameFramework.ConfigGen`
- **AND** 其中的类与结构体 SHALL NOT 出现 `*Row` 类型名

#### Scenario: consumers need an explicit using
- **WHEN** 业务代码引用生成物
- **THEN** 需要 `using GameFramework.ConfigGen;`（不再靠全局命名空间隐式可见）

### Requirement: Generate canonical Lua Accessor with query API and typed fields
工具 SHALL 为每张表生成 Lua Accessor，与 canonical reader（`GD`）对齐 参考实现 的接口与性能：提供 `M.Count/M.ByID/M.ByIndex` 查询，enum 返回类型化值，跨表 `ref` 提供类型化访问，vector 返回惰性表（数组值）经基址捕获读取。i18n 字段按当前语言表读取。

#### Scenario: Lua Accessor exposes per-table query API
- **WHEN** 生成 `ItemAccessor.lua`
- **THEN** 包含 `M.Count`、`M.ByID(id)`、`M.ByIndex(i)`；若配置 CodeName 索引还包含 `M.ByCodeName`

#### Scenario: Lua enum field typed
- **WHEN** Item 表有 `Rarity: ItemRarity` 枚举字段
- **THEN** 生成返回类型化值（数字或字符串映射，按 Lua 消费约定）的 `Rarity` 访问器，而非裸数字

#### Scenario: Lua cross-table ref typed accessor
- **WHEN** Item 表有 `ref: ItemType.Id`
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
工具 SHALL 为跨表 `ref` 生成类型化访问，其底层用**一次建立的 id→行缓存**，避免每个字段访问都触发原生 P/Invoke（对齐 参考实现 的 `{RefType}.ByID(id)`，但不牺牲性能）。

#### Scenario: ref typed lookup uses cached id→row
- **WHEN** 首次调用 `Item.ItemType` 访问目标表
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
- **WHEN** 导出 zh（主语言），Item 和 ItemType 两张表
- **THEN** `data_zh.bin` 包含两个 BundledTable，name 分别为 "Item" 和 "ItemType"

### Requirement: Write secondary language i18n-only Binary Bundle
工具 SHALL 为次语言只构建包含 i18n 变体表的 Bundle，输出 `output/binary/data_{lang}.bin`，只包含有 i18n 字段的表的 I18n 变体。

#### Scenario: i18n-only bundle written
- **WHEN** 导出 en（次语言），Item 有 i18n 字段，ItemType 无 i18n 字段
- **THEN** `data_en.bin` 只包含 BundledTable name="Item_i18n"，不含 ItemType

#### Scenario: No i18n tables
- **WHEN** 所有表均无 i18n 字段，请求导出次语言
- **THEN** 不生成次语言 .bin 文件，记录 info 日志

### Requirement: Sparse i18n tables mirror the main table row order
工具 SHALL 让 `{Table}_i18n` 表的行顺序与主表**完全一致**（同一行下标指向同一逻辑行），且行数相等；
否则多语言字段只能按主键二分查找，无法按下标定位。

#### Scenario: i18n row order matches main table
- **WHEN** 导出次语言，且 Item 有 i18n 字段
- **THEN** `Item_i18n` 的第 i 行对应主表 `Item` 的第 i 行，两表行数相等
- **AND** 若行数不等，导出 SHALL 失败并报错（不得静默产出错位数据）

#### Scenario: tables without i18n fields produce no i18n table
- **WHEN** 某表没有任何 `i18n: true` 字段
- **THEN** 不生成该表的 `{Table}_i18n` 变体

### Requirement: Language switch replaces only the i18n bundle
切换语言 SHALL 只替换 i18n 表（`data_{lang}.bin`）；SHALL NOT 重新加载或失效主表，也 SHALL NOT 使主表行句柄失效。
原生 SHALL 提供独立的 i18n 装载入口（`GD_SetI18nBytes`），它 SHALL NOT 推进主表世代，
且 SHALL 只重注册属于 i18n 包的容器表。

#### Scenario: main row handle survives a language switch
- **WHEN** 调用方持有主表某行的句柄，随后切换到另一语言
- **THEN** 该句柄仍然有效：读取其标量/枚举/向量/嵌套 record 字段的结果不变（向量与 record 视图亦然）
- **AND** 该句柄随后读取 i18n 字段时返回**新语言**的文本

#### Scenario: i18n bundle rows invalidate on language switch
- **WHEN** 调用方持有的是 i18n 包（`{Table}_i18n`）里的行句柄，随后切换语言
- **THEN** 该句柄 SHALL 失效并明确报错（其数据来自被替换的那份 i18n 缓冲）
- **AND** 主表行句柄 SHALL NOT 因此失效

#### Scenario: i18n caches invalidate on language switch only
- **WHEN** 切换语言
- **THEN** 主表访问器里 i18n 表句柄缓存与译文驻留缓存失效
- **AND** 该失效 SHALL 与「整套 bin 换代」的世代**分开**，以免连带失效主表行句柄与主表原文缓存

### Requirement: i18n is limited to top-level scalar string fields
标记 `i18n` 的字段 SHALL 只允许出现在 **Table 顶层**，且类型 SHALL 是**标量 `string`**。
`record` 字段（含嵌套 record 与 `vector<Record>` 的元素字段）SHALL NOT 允许 `i18n`；
`vector<string>` SHALL NOT 允许 `i18n`。违反者 SHALL 在 **schema 校验期**报错并带上字段路径。

这条约束 SHALL 由 schema 层独占负责：下游两层**不会**报错，只会**静默忽略**——
`_i18n_table()` 只遍历顶层字段，`build_accessor_model` 的 `i18n_fields` 也只从顶层字段里取。
实测（绕过 schema 校验直接构造模型）：record 里的 `i18n: true` 不进 `i18n_fields`、
稀疏 i18n 表不含该字段、生成物按普通 string 读，且**零告警**。
⇒ 若要支持 record 多语言，只放开这条校验是不够的，必须同时改导出与生成两层。

#### Scenario: record field with i18n is rejected with a path
- **WHEN** 某个 `record` 的字段标了 `i18n: true`
- **THEN** schema 校验 SHALL 抛错，错误信息含 `record:{name}/{field}` 与 `i18n`

#### Scenario: vector of string with i18n is rejected
- **WHEN** 顶层字段是 `vector<string>` 且标了 `i18n: true`
- **THEN** schema 校验 SHALL 抛错（不是「跟 string 沾边就放行」）

#### Scenario: downstream layers do not re-check
- **WHEN** 有字段绕过了 schema 校验进入导出/生成
- **THEN** 下游 SHALL NOT 报错；`i18n_fields` 与稀疏 i18n 表 SHALL 只含顶层字段

### Requirement: i18n field reads go through the sparse table by row index
生成的多语言字段访问器 SHALL 用**行下标**读取当前语言的 `{Table}_i18n` 表。
该表未加载（未加载对应语言包）时 SHALL 回退读主表内的原文，SHALL NOT 抛错。
行句柄 SHALL NOT 缓存 i18n 表指针（切语言会替换整张表，缓存下来即为悬垂指针）。

#### Scenario: i18n table missing falls back to source text
- **WHEN** 只加载了主语言包（无 `{Table}_i18n`），读取某行的 i18n 字段
- **THEN** 返回主表内的原文，不抛异常

#### Scenario: i18n table loaded returns the current language text
- **WHEN** 加载了 en 的 i18n 表，读取主表第 i 行的 i18n 字段
- **THEN** 返回 `{Table}_i18n` 第 i 行的对应文本

#### Scenario: i18n pointer is resolved per read
- **WHEN** 切换语言后再次读取同一行句柄的 i18n 字段
- **THEN** 返回新语言的文本（证明行句柄没有缓存 i18n 表指针）

#### Scenario: i18n read does not depend on main row order matching primary-key order
- **WHEN** 主表行序不等于主键升序（导出器 SHALL NOT 对 items 排序，行序即 Excel 序）
- **THEN** i18n 字段仍返回正确译文
- **AND** 读取 SHALL NOT 在 i18n 表的 items 向量上按主键二分——items 按主表行序排列，
  在其上二分会**静默**查不到任何译文并回退成原文

### Requirement: The sparse i18n read path is inlined in the main accessor
生成器 SHALL NOT 为 `{Table}_i18n` 单独产出一份访问器（文件、类、行类型都不产出）。
该表的句柄解析、译文驻留缓存与逐字段读取 SHALL 内联在主表访问器里——
它对外没有独立用途，唯一消费者就是主表的 i18n 字段读取。

主表访问器里的 i18n 句柄 SHALL 从 **i18n 包**解析（C# 侧 `FindTableI18n` / Lua 侧
`GD.FindTableI18n`），SHALL NOT 从主包解析；主语言包下解析结果为「表不存在」，
读取 SHALL 回退主表原文，SHALL NOT 抛错。

#### Scenario: no standalone i18n accessor is generated
- **WHEN** 导出带 i18n 字段的表
- **THEN** 产物中 SHALL NOT 出现 `{Table}_i18nAccessor.cs` / `{Table}_i18nAccessor.lua`
- **AND** SHALL NOT 出现 `{Table}_i18n` 行类型
- **AND** 主表访问器 SHALL 含 i18n 表句柄与逐字段译文读取

#### Scenario: i18n handle resolves from the i18n bundle
- **WHEN** 加载了 en 的 i18n 包，读取主表第 i 行的 i18n 字段
- **THEN** 返回 `{Table}_i18n` 第 i 行的对应文本

### Requirement: The i18n handle and translation caches re-resolve per i18n generation
i18n 句柄与译文缓存 SHALL 按 **i18n 世代**失效（与「整套 bin 换代」的世代分开），
以免切语言连带失效主表行句柄与主表原文缓存。

该句柄守卫 SHALL 在「表**缺席**」时同样生效：SHALL NOT 采用 `t != null && 世代相符`
这种写法——表缺席时 `t` 恒为空，守卫永不成立，于是**每读一次 i18n 字段都重走一遍**
表解析（字典查找 + 字符串哈希）。缺席结果 SHALL 与世代一起被记住。

#### Scenario: handle re-resolves after switching back to the primary language
- **WHEN** 先加载 en（`{Table}_i18n` 可解析），再切回主语言 zh（包内无 `{Table}_i18n`）
- **THEN** i18n 字段读取回退到主表原文，SHALL NOT 抛错
- **AND** 再次切到 en 时能重新解析到句柄并返回英文文本

#### Scenario: absent i18n table is not re-resolved on every read
- **WHEN** 主语言包下反复读取同一行的 i18n 字段
- **THEN** 表解析 SHALL 只发生一次（世代不变期间）
- **AND** 该失效 SHALL NOT 推进主表世代（旧行句柄保持有效）

### Requirement: An empty translation falls back to the source text
i18n 行存在但该字段**没有译文**时，读取 SHALL 回退主表原文。
C# 与 Lua 两个目标语言的语义 SHALL 一致——SHALL NOT 出现「行在就无条件返回该值
（哪怕为空）」这种与另一侧 `空即回退` 不同的写法。

#### Scenario: row present but field empty
- **WHEN** `{Table}_i18n` 第 i 行存在，但该 i18n 字段槽位缺失
- **THEN** 返回主表第 i 行的原文，而不是空值

### Requirement: Sparse i18n table mirrors main rows one-to-one, including rows without translations
稀疏 i18n 表 SHALL 对**每一个**主表行产出一行（主键 + i18n 字段），SHALL NOT 只产出「有译文」的行；
行序 SHALL 与主表一致。没有译文的行以「该字段槽位缺失」表示，读取侧据此回退主表原文。

#### Scenario: a row without translation still occupies its slot
- **WHEN** 某主表行的 i18n 字段在所有语言里都没有确认译文
- **THEN** 该行在 `{Table}_i18n` 里**仍然存在**（占据同一行下标），只是该字段缺失
- **AND** `{Table}_i18n` 的行数等于主表行数（按下标定位因此始终成立）

### Requirement: Primary and secondary lookups are all O(1) — no binary search at read time
生成的容器 SHALL 让**每一条查询路径**在运行期都是哈希定位，SHALL NOT 依赖二分查找：

- **主键（ByID）**：容器 slot 2 = `idHash`，开放寻址桶存「`index` 向量位置 + 1」，`0` = 空。
  哈希用 `key * 2654435761` 取低位，线性探测，命中后按 `index` 向量里的 key 确认。
  导出器对**每张表**都 SHALL 产出该向量（`TableResource.primary` 是必填项）。
  ⇒ 读端 SHALL NOT 再保留「无哈希时回退二分」的兜底：缺 `idHash` 属于 bundle 来历不对，
  SHALL 在**加载/建表期硬报错**（C#）或**首次查询时报错**（Lua/原生），SHALL NOT 静默返回空。
- **CodeName**：容器 slot 3 = `codeNameIndex`，开放寻址桶存 `rowIndex + 1`，key 用 FNV-1a 64 取低位；
  **固定**指向名为 `CodeName` 的 string 字段（schema 只写 `kind: codename`，不写 `field`）。
  桶表本身不判重，所以写入前 SHALL 由数据校验兜住「非空 + 唯一」——声明了该索引的表里每行
  `CodeName` 必须非空且唯一，否则导出「解析校验」阶段与 `ct validate` 以 `IssueCode.DUPLICATE_CODENAME`
  失败（空值报 `type`），详见 `schema-editor/query-indexes`。
容器 slot 4 / 5 曾用于 Group 索引（`groupIndex` + `groupHash`）。该索引**已砍**：没有任何表
声明过它，Lua 侧始终是占位 stub，且导出器会静默丢掉「group 列留空」的行（它们读出来是默认值 0，
却不在 key 0 的组里）。两个槽位因此空出，等待未来重新设计；重新引入时 SHALL 一并解决上面这条
默认值语义。

#### Scenario: missing primary hash fails loudly
- **WHEN** bundle 的某张表缺容器 slot 2（例如不是当前导出器产出的）
- **THEN** C# 侧 SHALL 在建 `ConfigTable` 时抛错
- **AND** Lua/原生侧 SHALL 在首次 `ByID` 时抛 Lua 错误
- **AND** SHALL NOT 静默返回「未找到」

### Requirement: Generated accessors read uniform tables by literal offset

表是否定宽 SHALL **由表 schema 的 `uniform` 键声明**（缺省 `true`），SHALL NOT 由数据、填充率或任何导出期探测结果决定。导出器 SHALL NOT 存在「先探测再决定布局」的阈值判定。

定宽表的行内字段偏移是**表级常量**，生成器 SHALL 据此发射**字面量偏移**读 ——
C# 侧 `WireReader.I32At(row, 28)`，Lua 侧 `GD.I32Off(s, 28)` —— 而不是每次读重走 vtable。
显式 `uniform: false` 的表 SHALL 继续走槽位（偏移不是常量，字面量化会读错），且 SHALL NOT 出现字面量偏移。

填充率 SHALL 仍被计算，但仅用于导出输出中的诊断报告，SHALL NOT 参与布局决策。

#### Scenario: uniform table emits literal offsets

- **WHEN** 表未声明 `uniform`（缺省为真）或显式声明为 `true`
- **THEN** 其 C# / Lua 访问器的标量、字符串、容器取指针均按**导出期算出的常量偏移**读
- **AND** 嵌套 record **内部**字段仍走槽位（record 不是定宽表）

#### Scenario: non-uniform table keeps slot reads

- **WHEN** 表显式声明 `uniform: false`
- **THEN** 访问器走 vtable 槽位读，SHALL NOT 出现字面量偏移

#### Scenario: 改数据不再改变布局

- **WHEN** 某定宽表的某行把字段填成类型默认值（或清空该单元格），使填充率下降
- **THEN** 该表的定宽声明、`slot_offsets`、二进制行布局与生成的访问器 SHALL 均不变化
- **AND** 只有导出输出里的填充率诊断数字变化

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
