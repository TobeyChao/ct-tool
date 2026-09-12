## MODIFIED Requirements

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
