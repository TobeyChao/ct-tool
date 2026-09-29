# 真实形状基准夹具（`--sizes r` / `--sizes r-full`）

这两档夹具的形状来自真实配表工作区的实测分布，而不是等宽常量。目的是让**表级 / 语言级
固定开销**变成可测量的量：现有 S/M/L 夹具每张表同构（固定 20 列、每表相同行数、3 种语言），
按 S/M/L 冷全量插值出的成本模型外推到真实形状只给出 26.9s，而回归档实测冷全量是 **422.8s**
（低估 15.7×）。

实测对照（同一台机器，Windows / 28 逻辑核）：

| 口径 | L 档 | 回归档 `r` | 倍率 |
|---|---|---|---|
| 冷全量（中位） | 101.3s | 422.8s | 4.2× |
| 热（输入无变化） | 54.5s | 153.2s | 2.8× |
| 产物文件数 | 607 | 10,646 | 17.5× |
| 数据单元格 | 18.48M | 3.71M | 0.20× |
| 冷全量进程树峰值 RSS | 7,014 MiB | 5,549 MiB | 0.79× |

读法：真实形状用 **20% 的单元格**换来 **4.2 倍**的冷全量耗时；其中 153.2s（36%）在**输入完全
没有变化**时也要付出，这部分由 818 张表 × 10 语言 = 8,180 个「表×语言」单元驱动，而按单元格
线性外推完全看不到它。

> 这两个档位只用于**性能与形状**测量，**不用于产物正确性对照**（不是 golden 来源）。
> 产物正确性由 `native/tests/compat/` 的逐字节对照负责。

## 1. 两档构成

| | `bench-r`（常规回归） | `bench-r-full`（手动专项，不进 CI） |
|---|---|---|
| 表 | **818**（164 Config + 654 Enum） | **2,027**（1,373 Config + 654 Enum） |
| 行 | 249,569 | 691,518 |
| 槽位（行 × 字段） | 3,709,512 | 6,953,587 |
| i18n 字段 | 127 | 816 |
| 译文条目（口径 A，每语言） | 117,146 | 301,656 |
| 向量字段 | 168 | 1,378 |
| 引用边 | 590 | 2,583 |
| 内联 record 类型 | 205 | 1,286（清单内） |
| 最大表头行数 | 14 | 14 |
| 语言 | `zh`（源）+ `en ko tw th ja es pt de fr`（9 译文）= 10 | 同左 |
| Excel 工作簿 | 818（一表一工作簿） | 2,027 |

回归档的 Config 表由「按槽位排序强制纳入的 12 张巨型表」+「按（行数桶 × 字段桶）分层抽样的
152 张表」组成；Enum 表全量。强制纳入的 12 张是 `Res`(134,198 行)、`Skill`、`Buff`、
`VirtualPlayerCN`、`Item`、`Talent`、`FansCheer`、`Task`、`VirtualPlayerAU/JPN/KOR/LAC`。

薄表（≤10 行）占比：回归档 40.8% vs 全量 43.3%（自检阈值：不低于全量的 80%）。

## 2. 形状来源与口径差异

清单 `shape-r.json` 由一次性 provenance 步骤冻结，输入是两份外部留档：

| 留档 | 出处 | 提供什么 |
|---|---|---|
| `ref_table_shapes.json` | 参考实现的运行时 dump（`dev_trunk_ref`，本机已不在位） | **每表行数** |
| `ExcelRecord.json` | 导出期类清单（`design-data`） | **字段语法、i18n 标记、引用边、嵌套结构** |

两份留档的口径并不一致，清单取上表的分工，差异记在清单 `provenance.source_counts` / `notes` 里：

- **字段数**：dump 11,217 vs 类清单 11,314（1,310/1,362 张表完全一致，余下有 ±1 与个别 −26 的差异，
  来自嵌套 struct 的计法）。
- **i18n 字段数**：dump 1,630 vs 类清单 815（同表常为 2 倍关系）。若沿用 dump 口径，口径 A 的译文
  条目会被放大到真实的约 3.3 倍；改用类清单的 `[I18N]` 标记后是真实已翻译条目（每语言约 185,265）
  的 **约 1.6 倍**，与实测自洽。
- **类数**：2,027（1,373 Config + 654 Enum）比 dump 多 15 个类（dump 只有 2,012 张表有运行行数），
  这 15 个类按 0 行处理。

冻结命令（需要上述两份留档在场，之后不再需要）：

```powershell
cd native
cargo run --release -p ct-xtask -- bench-shape-freeze `
  --shapes ../test-proj/RefConfigBench/ref_table_shapes.json `
  --records D:/dev_trunk_harmony/design-data/ExcelRecord.json
cargo run --release -p ct-xtask -- bench-shape-check      # 只读自检
```

## 3. 抽样规则（可复算）

1. **强制巨型表**：Config 表按 `行数 × 字段数` 降序取前 12（同分按表名）。
2. **分层抽样**：其余 Config 表按（行数桶 × 字段桶）分层，每层至少 1 张，按层规模比例分配；
   层内先选**引用了强制 hub 的表**，再按 `splitmix64(seed ^ fnv1a(表名))` 升序、表名升序取。
   规则里没有 RNG 状态，任何语言/版本都能复算出同一份表集合（现有 S/M/L 的 Python 生成器依赖
   `random.Random` 序列，这是新档位不沿用它的原因之一）。
3. **Enum 全量**：654 张。
4. 种子固定为 `20260918`。

## 4. 命名规范化

真实工作区用 camelCase，内核要求 WYSIWYG PascalCase，且有三条硬约束：

- 字段名首字符必须大写 → `id`/`codeName`/`designName` → `Id`/`CodeName`/`DesignName`；
- 字段名不得与任何生成类型名同名（真实工作区大量违反，例如 `Item` 表里有 `Item` 字段）
  → 撞名字段改名为 `<原名>Value[序号]`；
- Excel 工作表名上限 31 字符（真实有 16 张表名更长）→ 截断为 `前24字符_6位哈希`。

被改名的表在清单里保留 `source_class` 供追溯。

## 5. 偏差登记（自检不对这些维度作覆盖断言）

| # | 偏差 | 真实工作区 | 本夹具 | 方向 |
|---|---|---|---|---|
| 1 | `multi-area-columns` 分区域列 | 同一字段按区域展开成多列（CHN/PHI/HMT） | 不建模（`native/` 全仓库无该语义） | 少算列 |
| 2 | `multi-table-workbooks` 多表工作簿 | 最多 22 张表共享一个工作簿 | 一表一工作簿（内核硬约束） | 多算文件数 |
| 3 | `animevent-curves` 动画事件曲线 | 6,763 个 json / 3.17 GB | 完全排除（独立管线） | 少算 |
| 4 | `track-binaries` 轨道二进制 | 3,259 个 `.bytes` / 13.7 MB | 完全排除（独立管线） | 少算 |
| 5 | `translation-fill-rate` 译文填充率 | 每语言约 185,265 条已翻译条目 | 口径 A：每个 i18n 单元格一条 = 每语言 301,656 条（约 1.6 倍） | 多算 |
| 6 | `i18n-per-language-aggregation` i18n 文件布局 | 每种语言一个聚合文件（9 个文件） | 内核格式：每表每语言一个文件（回归档 69 张带 i18n 的表 × 10 = 690 个文件） | 多算小文件 |
| 7 | `vector-expansion-widths` 向量展开列宽 | 逐字段实测宽度 | 标量向量按 {2,3,4} 确定性取值、40% 保持单格（记录数组的组数来自留档 `TYPE[N]`） | 近似 |
| 8 | `long-table-names` 超长表名 | 16 张表名 > 31 字符 | 截断加哈希后缀 | 改名 |
| 9 | `regression-tier-tail-bias` 回归档尾部高配 | 76/1,373 张 Config 表 > 1,000 行 | 强制纳入 top-12 巨型表 → 12/164 张 > 1,000 行 | 体量偏大 |

补充说明（不改变偏差方向，但读数字时需要知道）：

- **Enum 类建成了表**：真实工作区里 Enum 类是独立实体，各产出**逐枚举的客户端 accessor**，
  但没有服务端 JSON、也没有 Excel（值来自 C# 声明）。夹具把它们建为三列表
  （`Id`/`CodeName`/`DesignName`，行数 = 取值个数），因此每语言会多出 JSON 产物——这是为了保留
  「每表固定开销」这一被测维度，而不是声称产物集合与真实一致。
- **指向 Enum 的字段**在夹具里是 `int32 + ref`（真实语义也是存 id），因此夹具不使用内核的
  `kind: enum` 类型机制。
- **未知类型标记**：留档里只有 `Value` 一种无法归类，按 `string` 处理。
- **i18n 文件体积**：内核写出的是 pretty JSON（约 157 B/条目），真实工具是紧凑格式（约 76 B/条目），
  因此夹具的 i18n 目录体积约为真实工作区的 1.6 倍 × 2 ≈ 3 倍。

## 6. 生成、判定与回归

```powershell
cd native
cargo run --release -p ct-xtask -- bench-fixtures --sizes r            # 只写 target/
cargo run --release -p ct-xtask -- bench --size r --runs 5 `
  --python native/target/no-python-reference                          # 无 Python 参照 → 回归判定
cargo run --release -p ct-xtask -- bench-recheck `
  --report ../native/docs/baseline/bench-r-windows.json               # 用当前常量重算 verdict
```

- 夹具生成只依赖仓库内资源与原生库入口，**不依赖 `ct/` 在位**，不会回退到 Python 参照；
  生成前会清空 `output/cache/.ct`，保证两个引擎都从零缓存冷启动。
- 生成是确定性的：重复生成得到同一份输入摘要（`FIXTURE.json` 的 `inputDigest`，忽略 xlsx 里随时间
  变化的文档属性）。真实工作区与 `gd/` 不会被读写。
- 判定路径复用 `native-core-runtime` 已有语义：参照不在位时记
  `verdict=regression-pass|regression-fail` + `baselineMode=archived-run`，**不声称配对测量**。
  全量档可以手动跑配对测量，但不进 CI。
