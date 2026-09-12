# schema-editor/query-indexes Specification

## Purpose
定义 Table 的 **CodeName** 查询索引、数据约束和跨语言生成 API，保证索引查询在 hash 碰撞下仍返回正确原值，并以桶内比较而非全表扫描控制额外开销。

> ⚠️ 本规格曾同时描述一个非唯一的 **Group** lookup。该索引**已删除**（它从未被任何真实表声明、
> Lua 侧始终是占位 stub，且导出器会静默丢掉「group 列留空」的行 —— 那些行读出来是默认值 `0`，
> 却不在 key `0` 的组里）。重新引入的做法记在游戏仓 `Docs/TODO/开工方案.md` §十 W1。

## Requirements

### Requirement: Table-level query index model
Table SHALL 通过表级 `indexes` 声明查询契约；当前 SHALL 只支持**一个 `codename` 索引**，且该索引
**不携带字段名**（`indexes: - kind: codename`）—— 它固定指向名为 `CodeName` 的 `string` 字段。
索引的存在性、字段与唯一性 SHALL NOT 作为字段类型或零散布尔开关表达。CodeName lookup SHALL 是整数
primary 之外的辅助查询，不替代 Table identity 或跨表 ref 语义。`kind: code`（改名前的旧名）与
`kind: group`（已删除）SHALL 被拒绝，不提供兼容别名；`indexes` 条目只接受 `kind` 一个键。

#### Scenario: Configure the CodeName lookup
- **WHEN** 用户为一张表勾选 codename 索引（表里存在非 i18n 的 `CodeName` string 字段）
- **THEN** Candidate 保存表级索引定义并显示将生成的 `ByCodeName(string)` API

#### Scenario: 未声明字段名
- **WHEN** 用户在 `indexes` 条目里写 `field: DisplayName`
- **THEN** 解析直接报错（codename 固定指向 `CodeName`，字段名不是配置项）

#### Scenario: Reject an index on Record
- **WHEN** 用户打开 Record 或 Enum 资源
- **THEN** 工作台不提供 Table 查询索引配置，后端也拒绝为非 Table 资源提交索引

#### Scenario: 表里没有合格的 CodeName 字段
- **WHEN** 表没有 `CodeName` 字段、或它不是 string、或带 `i18n`/`server_only`、或是 vector
- **THEN** 校验在**加载期/候选期**就报错，说明缺哪一种条件

### Requirement: Index data preflight
`CodeName` SHALL 为非 i18n string、**非空**且按精确原字符串在表内**唯一**。**两道闸门都 SHALL 拦截**：

- **Change Plan 预检**（应用前）：扫描现有 Excel 数据，返回具体重复、空值、i18n 角色或非法类型位置；
- **导出/`ct validate`**（产出前）：违反时导出 SHALL 失败且**不落任何产物**，issue 带表名、Excel 行号、
  列与原始值（重复值还 SHALL 指出首次出现的行号），错误码 `duplicate_codename`（空值报 `type`）。

> 第二道闸门是必需的，而不只是「编辑器里拦一下」：导出器建桶表时对空串跳过、也**不判重**，所以
> 没有这道校验时，两行写同一个 `CodeName` 会**静默**导出成功，而运行期 `ByCodeName()` 只命中
> 探测序更靠前的那个 —— 另一行永远查不到且毫无提示。

#### Scenario: Duplicate CodeName blocks apply
- **WHEN** 两行数据具有相同的 CodeName
- **THEN** Change Plan 阻止应用并列出两行的 Excel 行号和原始值

#### Scenario: Duplicate CodeName blocks export
- **WHEN** 直接对工作区跑 `ct export`（绕过编辑器），而表内存在重复 CodeName
- **THEN** 导出失败并给出 `duplicate_codename` issue，`output/` 不产生新产物

#### Scenario: Blank CodeName blocks export
- **WHEN** 声明了 codename 索引的表里某行 CodeName 为空（或该字段整个缺失）
- **THEN** 导出失败（该行永远查不到）

#### Scenario: 未声明索引的表不受约束
- **WHEN** 表没有声明 codename 索引，即使 CodeName 列有重复或空值
- **THEN** 校验与导出都不报错（此时它只是一个普通字段）

#### Scenario: Reject an i18n index field
- **WHEN** `CodeName` 带 `i18n: true`
- **THEN** 校验拒绝并说明查询索引不能随导出语言改变

### Requirement: Generated C# and Lua query APIs
生成器 SHALL 为 codename lookup 生成返回单条记录的 C#/Lua API —— `ByCodeName(codeName)` —— 两种语言
SHALL 使用一致的缺失语义（未命中返回 `null`/`nil`）与精确字符串规则；**表未声明该索引时 SHALL NOT
生成**，运行期对没有该索引的表调用 SHALL 硬报错而不是返回「未找到」。

#### Scenario: Query a missing code
- **WHEN** C# `ByCodeName` 或 Lua 对称 API 查询不存在的原字符串
- **THEN** 返回约定的未找到结果，不返回同 hash 的其他记录

#### Scenario: Query against a table without the index
- **WHEN** 对没有声明 codename 索引的表调用 `ByCodeName`
- **THEN** Lua/原生侧抛明确错误（提示该表没有 `codeNameIndex`），SHALL NOT 返回 nil

### Requirement: Hash collision correctness
hash SHALL 只用于快速定位候选桶；CodeName SHALL 对 Excel reader 解析后的 string 原值计算 hash，并在命中后 MUST 对候选执行区分大小写的 ordinal 完整相等比较，不能仅依据 hash 判定命中。索引层 SHALL NOT trim、case-fold、执行 NFC/NFKC 或其他 Unicode 归一化；生产 hash 算法（FNV-1a 64）及其 UTF-8 输入和整数溢出语义 SHALL 固定且不得使用进程随机化的运行时 string hash。

#### Scenario: Two different strings share a hash
- **WHEN** 测试注入两个 hash 相同但原字符串不同的 CodeName 值
- **THEN** 查询每个字符串只返回其精确记录，查询第三个同 hash 字符串返回未找到

#### Scenario: Visually related strings remain distinct
- **WHEN** 表同时包含 `Code`、`code` 和全角变体且三者 hash 不论是否碰撞
- **THEN** 三个键均可独立预检和查询，系统不修改任一字符串来制造重复或命中

### Requirement: Collision comparison performance boundary
原字符串确认 SHALL 只遍历对应 hash 桶中的候选项，不得退化为每次全表扫描；性能测试 SHALL 覆盖普通桶和人为高碰撞桶。

#### Scenario: Query a normal bucket in a large table
- **WHEN** 表含大量记录且目标 hash 桶仅有一个候选
- **THEN** 查询执行一次候选原值比较并返回，不扫描其他 hash 桶

#### Scenario: Query an adversarial collision bucket
- **WHEN** 测试构造一个包含多个碰撞候选的桶
- **THEN** 查询最多比较该桶候选数并保持结果正确，基准报告桶大小对延迟的影响
