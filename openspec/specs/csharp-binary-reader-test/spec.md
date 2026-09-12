## Purpose

用独立 .NET 控制台工程读取 ct 导出的 FlatBuffers 二进制，经**生成的 accessor** 逐行逐字段与 `output/json` 真值比对，验证产物在客户端的可读性。当前 harness 是 `test-proj/ExportAccessorVerify/`。

## Requirements

### Requirement: 用真实导出产物驱动端到端逐字段校验

`test-proj/ExportAccessorVerify/` SHALL 是一个不依赖 Unity/游戏的控制台工程（`Program.cs`）：加载 `fixtures/data_zh.bin` 的 Bundle 并 `Runtime.Register` 各表，用**导出器生成的** accessor 读取每一行、每一个字段，与 `fixtures/{Table}_zh.json` 真值逐项比对；不一致 SHALL 逐条打印表名、行号、字段名与实际/期望值。

fixture SHALL 由 `prepare.py` 生成，而不是手写：它把 `ct/tests/fixtures/repository_cutover/workspace` 复制到临时目录、跑一次真实的 `run_canonical_export`，再取出生成的 C# accessor（`generated/`）、`data_{lang}.bin` 与 `{Table}_{lang}.json`（`fixtures/`）、以及 `fnv_vectors.tsv` 与 `manifests.json`。

fixture 工作区 SHALL **同时覆盖两条访问器形态**：缺省（`uniform` 为真）的表走字面量偏移，且至少有一张表显式声明 `uniform: false` 走槽位读 —— 该表当前是 `UIConfig.yaml`。这样逃生门（非定宽路径）不会因为默认全定宽而失去测试覆盖。

#### Scenario: 定宽表逐字段比对

- **WHEN** 校验缺省（定宽）表 Item、ItemType、Quest
- **THEN** 用 `ByIndex` / `ByID` 取行后逐字段比对 `Id`、`Name`、`Price`、`Rarity`（按 enum 声明序）、`ItemTypeId`、`DropRange.Min` / `DropRange.Max`、`Tags[i]`，以及 ItemType 的 `Id` / `Name` / `CodeName`、Quest 的 `Id` / `Title` / `Description` / `RewardItemId` / `RequiredLevel`

#### Scenario: 变长表作为基线

- **WHEN** 校验显式声明 `uniform: false` 的 UIConfig
- **THEN** 同样逐字段比对 `Id`、`Layer`（按 enum 声明序）、`ResourceKey`、`BlocksRaycast`、`Stack`
- **AND** 其生成的访问器走 vtable 槽位读，`manifests.json` 里该表的 `slot_offsets` 为空

### Requirement: 校验 CodeName 索引的逐行命中与负例
程序 SHALL 对声明了 codename 索引的表逐行取出 `CodeName` 真值并调用 `ByCodeName(CodeName)`，确认命中行的主键与真值一致；并 SHALL 校验负例：查询不存在的 codeName 返回 `null`、且不发生死循环。

#### Scenario: 每一行都能按 CodeName 命中
- **WHEN** 遍历 ItemType 真值的每一行 `CodeName`
- **THEN** `ItemTypeAccessor.ByCodeName(codeName)` 非 null，且命中行的 `Id` 与真值一致

#### Scenario: 不存在的 codeName 返回 null
- **WHEN** 调用 `ItemTypeAccessor.ByCodeName("__no_such_code__")`
- **THEN** 返回 null；返回非 null 记为一次不一致

### Requirement: 校验运行期 FNV-1a 与 Python 导出器逐位一致
程序 SHALL 用 `fixtures/fnv_vectors.tsv` 逐条比对 C# 侧 `WireReader.Fnv1a64` 与 Python `ct.export.index_query.fnv1a_64` 的结果——CodeName 索引的桶下标依赖该哈希，两侧算法必须逐位相同。对照表不存在时 SHALL 跳过该项并打印说明。

#### Scenario: 逐条比对哈希
- **WHEN** 读取对照表里的每个样本字符串
- **THEN** C# 计算结果与 Python 结果相同；不等时打印 `FNV('<s>'): got=... want=...` 并计为不一致

### Requirement: 校验稀疏 i18n 的回退与语言切换
程序 SHALL 校验稀疏 i18n 的两条路径：只加载主语言包（无 `{Table}_i18n`）时回退读主表原文；用 `Runtime.RegisterI18n` 加载次语言 i18n 表后，**同一行的句柄**读回该语言译文，且主表不重载、行句柄保持有效。

#### Scenario: 缺 i18n 表时回退原文
- **WHEN** 只加载 `data_zh.bin`（其中不含 `Item_i18n`），读取每行 `ItemAccessor.ByID(Id).Value.Name`
- **THEN** 返回值等于 zh 真值里的 `Name`

#### Scenario: 切换语言后读回译文
- **WHEN** 依次注册 en / ja 的 `Item_i18n` 等 i18n 表后，再次读取 Item 第 0 行的 `Name`
- **THEN** 分别得到 `Potion` / `ポーション`，且未重载主表

### Requirement: 校验 12 种标量往返
程序 SHALL 用 `gen_scalars_bench.py` 生成的 `fixtures/scalars.bin` + `fixtures/scalars.json` 校验 12 种标量：该表以 `Id: int32` 代表 int32，其余 11 种各有一个 `V{scalar}` 字段，值取该类型的**非默认边界值**（默认值会被省略槽位，属另一条规则）。

#### Scenario: 12 种标量往返
- **WHEN** 读取 `ScalarsAccessor.ByIndex(0)`
- **THEN** `Id`、`Vint8`、`Vuint8`、`Vint16`、`Vuint16`、`Vuint32`、`Vint64`、`Vuint64`、`Vfloat`、`Vdouble`、`Vbool`、`Vstring` 与 JSON 真值一致（浮点按 `1e-6` 容差）

### Requirement: 汇总与退出码
程序 SHALL 在所有校验执行完后打印汇总行 `共校验 {N} 个字段值，不一致 {M}`；全部一致时以退出码 0 退出，否则以退出码 1 退出。当前基线结果是 `共校验 127 个字段值，不一致 0`。

#### Scenario: 全部通过
- **WHEN** 所有校验均一致
- **THEN** 打印 `共校验 127 个字段值，不一致 0`，退出码 0

#### Scenario: 存在不一致
- **WHEN** 至少一个字段值不一致
- **THEN** 打印 `共校验 {N} 个字段值，不一致 {M}`（`M > 0`），退出码 1
