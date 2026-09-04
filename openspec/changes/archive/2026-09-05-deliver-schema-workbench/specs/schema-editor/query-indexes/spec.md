## Purpose

定义 Table 的 Code 与 Group 查询索引、数据约束和跨语言生成 API，保证索引查询在 hash 碰撞下仍返回正确原值，并以桶内比较而非全表扫描控制额外开销。

## ADDED Requirements

### Requirement: Table-level query index model
Table SHALL 通过 `indexes` 定义查询契约；首版 SHALL 支持一个唯一 Code lookup 和一个非唯一 Group lookup，索引字段、唯一性和生成 API 不得作为字段类型或零散布尔开关表达。Code lookup SHALL 是整数 primary 之外的辅助查询，不替代 Table identity 或跨表 ref 语义。

#### Scenario: Configure Code lookup
- **WHEN** 用户为 Item 选择 CodeName 作为 Code lookup 字段
- **THEN** Candidate 保存表级索引定义并显示将生成的 `ByCode(string)` API

#### Scenario: Reject an index on Record
- **WHEN** 用户打开 Record 或 Enum 资源
- **THEN** 工作台不提供 Table 查询索引配置，后端也拒绝为非 Table 资源提交索引

### Requirement: Index data preflight
Code 字段 SHALL 为非 i18n string、非空且按精确原字符串在表内唯一；Group 字段 SHALL 为非 i18n 的受支持 scalar 或 Enum，允许多个记录共享同一值。Change Plan SHALL 扫描现有 Excel 数据并返回具体重复、空值、i18n 角色或非法类型位置。

#### Scenario: Duplicate CodeName blocks apply
- **WHEN** 两行数据具有相同的 CodeName
- **THEN** Change Plan 阻止应用并列出两行的 Excel 行号和原始值

#### Scenario: Group values repeat
- **WHEN** 多行具有同一 Category group 值
- **THEN** 预检通过并报告分组数量和最大组大小

#### Scenario: Reject an i18n index field
- **WHEN** 用户选择带 `i18n: true` 的 DisplayName 作为 Code 或 Group 字段
- **THEN** Candidate 校验拒绝并说明查询索引不能随导出语言改变

### Requirement: Generated C# and Lua query APIs
生成器 SHALL 为 Code lookup 生成返回单条记录的 C#/Lua API，为 Group lookup 生成返回零到多条记录的 API；两种语言 SHALL 使用一致的缺失语义与精确字符串规则。

#### Scenario: Query a missing code
- **WHEN** C# `ByCode` 或 Lua 对称 API 查询不存在的原字符串
- **THEN** 返回约定的未找到结果，不返回同 hash 的其他记录

#### Scenario: Query a group
- **WHEN** 查询存在三条记录的 Group 值
- **THEN** C# 与 Lua 均返回且只返回这三条记录，顺序遵循表数据的确定性顺序

### Requirement: Hash collision correctness
hash SHALL 只用于快速定位候选桶；Code 和 string Group SHALL 对 Excel reader 解析后的 string 原值计算 hash，并在命中后 MUST 对候选执行区分大小写的 ordinal 完整相等比较，不能仅依据 hash 判定命中。索引层 SHALL NOT trim、case-fold、执行 NFC/NFKC 或其他 Unicode 归一化；生产 hash 算法及其 UTF-8 输入和整数溢出语义 SHALL 固定且不得使用进程随机化的运行时 string hash。

#### Scenario: Two different strings share a hash
- **WHEN** 测试注入两个 hash 相同但原字符串不同的 Code 值
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
