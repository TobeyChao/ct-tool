## Purpose

定义基准夹具的「真实形状」契约：夹具 SHALL 按真实配表工作区的实测分布构造（而不是等宽常量），提供回归档与全量档两个尺寸，由仓库内冻结的形状清单生成，使表级/语言级固定开销这类在等宽夹具中被淹没的成本能被测量到。

## ADDED Requirements

### Requirement: Two-tier real-shape fixture family

夹具族 SHALL 提供两个真实形状尺寸：回归档 `r` 与全量档 `r-full`。

回归档 SHALL 由三部分组成：全部 Enum 表、按（行数分桶 × 字段数分桶）分层抽样的 Config 表、以及按槽位（行数 × 字段数）排序强制纳入的巨型 Config 表；其配额 SHALL 为 654 张 Enum 表、12 张强制巨型表与 152 张抽样表，合计 818 张表、249,569 行、3,709,512 槽位、127 个 i18n 字段（每语言 117,146 条译文条目）、10 种语言（1 源语言 + 9 译文语言）。

全量档 SHALL 覆盖冻结清单里的全部类：2,027 张表（1,373 Config + 654 Enum）、691,518 行、6,953,587 槽位、816 个 i18n 字段（每语言 301,656 条）、10 种语言。

回归档 SHALL 进入常规回归；全量档 SHALL NOT 进入常规回归，只在显式请求时执行。

#### Scenario: Regression tier composition

- **WHEN** 生成回归档夹具
- **THEN** 产物含 818 张表（654 Enum + 164 Config：12 张强制巨型表 + 152 张分层抽样表）、249,569 行、10 种语言的译文骨架（每语言 117,146 条）

#### Scenario: Full tier is opt-in

- **WHEN** 运行常规回归（不显式指定尺寸）
- **THEN** 不生成也不测量全量档；只有显式请求全量档时才执行

#### Scenario: Verdict without a reference implementation

- **WHEN** 在 `ct/` 不在位的机器上测量回归档
- **THEN** 判定记为 `regression-pass`/`regression-fail` 且 `baselineMode=archived-run`，不声称是配对测量

### Requirement: Shape fidelity from measured distributions

夹具形状 SHALL 由真实工作区的实测分布确定，SHALL NOT 使用等宽常量（同一字段数、同一行数、同一工作表结构）替代下列维度：

- 每表字段数按实测分布（中位 4–6、长尾至 151）
- 每表行数按实测分布（中位 8、长尾至 134,198，薄表占比与真实同量级）
- Enum 表占表数的比例（真实约 32%）
- 每表嵌套深度按实测分布（决定表头行数），而非全部使用扁平结构
- 向量/结构字段横向展开为多列
- 跨表 `ref` 画像含高被引 hub 表
- i18n 字段只出现在真实拥有它们的表上

#### Scenario: Stratified sampling preserves the distribution

- **WHEN** 对抽样结果做（行数分桶 × 字段数分桶）统计
- **THEN** 每个非空分层至少包含 1 张表，且 ≤10 行的薄表占比不低于实测比例的 80%

#### Scenario: Variable header depth

- **WHEN** 检查夹具中不同表的工作簿
- **THEN** 表头行数随各表嵌套深度不同，不全为同一固定值

#### Scenario: Fixed-cost share is observable

- **WHEN** 在同一档位内比较「输入无变化的热场景」与「冷全量」两次测量
- **THEN** 两者都可测且固定开销可量化（回归档实测 153.2s / 422.8s = 36%，L 档 54.5s / 101.3s = 54%），并且不得用按单元格的跨档位插值系数把 L 档结论外推到真实形状（该做法实测低估 15.7×）

### Requirement: Frozen shape manifest and provenance

夹具 SHALL 由仓库内冻结的形状清单（源数据：真实工作区的运行时表形状留档与导表期表清单/类型语法留档，按表名合并）生成。

生成期 SHALL NOT 读取 `design-data`、`dev_trunk_ref` 或任何真实工作区，也 SHALL NOT 要求它们存在。清单 SHALL 记录其来源与推导方式，使形状可追溯。

夹具生成 SHALL 只写入夹具输出根目录，SHALL NOT 写入真实工作区或 `gd/`。

#### Scenario: Regeneration without the real workspace

- **WHEN** 在一台没有真实工作区 checkout 的机器上重新生成夹具
- **THEN** 生成成功，且输入树与有该 checkout 的机器一致

#### Scenario: Real workspace untouched

- **WHEN** 生成并测量两个档位
- **THEN** 真实工作区与 `gd/` 的文件内容与修改时间不变

### Requirement: Deterministic regeneration

夹具生成 SHALL 固定随机种子并只消费冻结清单，使重复生成产出逐字节相同的输入；生成过程 SHALL 清空缓存与产物目录，保证两个引擎都从零缓存冷启动测量。

#### Scenario: Identical inputs across runs

- **WHEN** 用同一种子连续生成两次回归档
- **THEN** 两次的输入树摘要一致（可与记录值比对）

### Requirement: Documented deviations

夹具 SHALL 随附偏差登记，逐条列出未建模或刻意偏离真实形状的维度、偏离方向与理由；登记项 SHALL NOT 以近似建模的方式假装覆盖。

登记 SHALL 至少包含：译文条目口径（口径 A：每个 i18n 单元格一条，条目数为真实已翻译条目的约 1.6 倍）、i18n 文件布局（per-table 而非真实工具的 per-language 聚合）、单表工作簿约束（真实工作区最多 22 张表共享一个工作簿，当前内核要求一表一工作簿）、分区域多列（当前内核无该能力故不建模）、非配表产物（动画事件曲线与轨道二进制属独立管线，排除）、向量展开列宽（确定性合成值）、以及回归档行数尾部相对真实的高配。

#### Scenario: Every unmodelled dimension is registered

- **WHEN** 审阅夹具的偏差登记与形状自检
- **THEN** 每个已知未建模维度都在登记中出现，且夹具自检不对该维度做覆盖断言

### Requirement: Fixture generation independent of the Python reference implementation

夹具生成 SHALL 只依赖原生入口与仓库内资源，SHALL NOT 依赖 `ct/` 在位；缺少必要前置时 SHALL 明确失败并给出原因，SHALL NOT 静默降级或回退到 Python 参照。

#### Scenario: Generation without the optional Python reference

- **WHEN** `ct/` 不在位且执行回归档夹具生成
- **THEN** 生成成功；若所需前置缺失则显式报错，不回退到 Python 参照

#### Scenario: Measurement does not require an interpreter

- **WHEN** 已生成的夹具执行测量与判定
- **THEN** 全过程不启动 Python 解释器
