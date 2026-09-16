# fabulous-game ↔ ct-tool 对齐清单

> 📁 `ct/docs/archive/`（2026-09-17 自 `ct/docs/TODO/` 移入：清单内 ct-tool 侧条目 C0–C7 均已完成，
> 未结事项在 fabulous-game 侧跟踪）· 2026-09-12 整理归档（本文此前未入库）。
> **时效提醒**：本文主体核实于 **2026-09-09/10**。此后 ct-tool 与 fabulous-game 两侧都大幅推进，
> 最关键的是 **§七 的「ByID 仍走二分」已不成立** —— 2026-09-12 两侧都已落哈希（原生 `gd_index_hash`），
> **二分查找已从读路径彻底移除**。**现状以 fabulous-game 侧《开工方案.md》为准**（其 §〇.1 为已完成清单）。
> 二级索引：**CodeName 半边已接线**（2026-09-12 完成）；**Group 半边已砍掉**（同日决定，见下）。
>
> ⚠️ 本文正文里凡出现 `ByCode` / `ByGroupKey` / `codeIndex` / `groupIndex` / `groupHash` 的段落，
> 都是 **2026-09-09/10 的历史快照**，不代表当前状态。当前状态：
> - 主键 `ByID` 与 CodeName 索引**都走哈希**，读路径无二分；
> - **定宽布局已改为 schema 显式声明 `uniform`**（缺省 `true`，2026-09-13，ct-tool 提交 7109e0f）：
>   §〇/C5 里「按填充率自动决策（阈值 0.75）」的描述已被取代 —— `UNIFORM_FILL_THRESHOLD` 已删除，
>   填充率只是导出日志里的诊断数字（动机：数据派生会让改 Excel 静默翻转二进制布局）；
> - **Schema 保存模型已演进**：§二 的「Draft→ChangePlan→Apply 事务模型」已被
>   **Draft → 服务端候选/净差异 → YAML-only 保存** 取代（2026-09-14，plan/apply 已删除）；
> - 2026-09-13 流水线重构后 `_merge_i18n` 与索引消费的落点已从 `canonical_export.py`
>   移至 `app/exporting/build.py` / `export/canonical_binary.py`（canonical_export 仅为兼容层，
>   §〇/§一 的行号引用按此理解）；
> - C7 所指的 `gd/output/fbs/*_i18n.fbs` 陈旧文件**已不存在**；
> - fabulous-game 侧两份文档已移位：《定宽布局落地方案》→ `Docs/TODO/方案/`、
>   《ByID查询性能实测-二分vs哈希》→ `Docs/TODO/实测/`；
> - §七 横幅「IndexSearch 均已删除」指 **fabulous-game 侧运行时**；本仓
>   `test-proj/ConfigAccessorBench` 基准工程仍保留 `IndexSearch` 作为 `_hashMask==0`
>   时的回退（基准工件，非生产读路径）；
> - **Group 索引整个删除**——它从未被任何表声明、Lua 侧始终是占位 stub，且导出器会静默丢掉
>   「group 列留空」的行（它们读出来是默认值 `0`，却不在 key `0` 的组里）。容器 slot 4/5 随之空出。
>   重新引入的计划记在 fabulous-game 侧 `Docs/TODO/开工方案.md`。

> 日期：2026-09-09（现状核实）
> 来源：fabulous-game `Docs/TODO/` 的分析与设计 + ct-tool 当前仓库核实
> 用途：记录**两边架构演进后的真实差异与剩余待办**，供 ct-tool 工作区继续工作。本文档自包含。

---

## 〇、🔴 最新状态（2026-09-10）：ct-tool 侧已产出**真·参考实现 原生对标**并实施九项优化

> ⚠️ **本节是全文最新的一节，其结论优先于下面各节。** 下面的 §一~§八 记录的是 2026-09-09/10 早期核实的结果，
> 部分已被本节的 patch 取代（会逐条标注）。

ct-tool 侧出现一份 patch（`~/Downloads/config-runtime-perf.patch`，34 文件 / 26 新增）——**✅ 已于 2026-09-11 合入本仓库**（`git apply` 干净），
新增 `test-proj/RefConfigBench/` 基准工程，做了两件此前没人做到的事：

1. **真对标**：`LoadLibrary` 参考实现 仓库内的 Windows x64 原生插件 `client/Assets/Plugins/x86_64/xlua.dll`，
   `GetProcAddress` 解析全部 18 个配置符号，**在同一 .NET 进程内**同时跑 参考实现 原生运行时
   （2012 表 / 691,518 行 / 146.7 MB 真实产物）与 ct reader，两侧交替计时。**不是读取模型复刻。**
2. **九项优化已实现并实测**（OPT-1 ~ OPT-9）：偏移表、非对齐加载、表句柄缓存、NArray 去分支、
   index 基址预解析、字符串冷路径、**主键哈希索引**、**per-field 字符串缓存**、**单缓冲视图**。

**最终成绩（ns，除加载行；`OPTIMIZATION-STRATEGY.md` 附录 D.5）：11 项里 5 项反超 参考实现**

| 场景 | 参考实现 | ct | 比值 |
|---|---:|---:|---|
| 加载（读盘 + 解析） | 62.5–65.1 ms | **26.7 ms** | **0.43×（快 2.3×）** |
| 字符串热读 | 32.25 | **1.22** | **0.038×（快 26×）** |
| `ByID` | 11.21 | **6.02** | **0.54×（快 1.9×）** |
| 行访问端到端（`ByID`+3 字段） | 12.41 | **9.19** | **0.74×（快 1.35×）** |
| 全表顺序扫描 | 4.76 | **3.77** | **0.79×（快 1.27×）** |
| 字符串冷扫 | 43.96 | 63.87 | 1.45× |
| 字符串解码（绕缓存） | 32.51 | 44.23 | 1.36×（托管固有） |
| `vector<int32>` | 1.19 | 1.97（字面量 **1.48**） | 1.66×（1.24×） |
| bool / float32 | 0.62 / 0.73 | 0.90 / 1.30 | 1.45× / 1.78× |
| **int32 字段读** | 0.16 | 0.46（字面量 **0.22**） | **2.87×（1.38×）** |

**对本清单各节的影响**：

| 本节 | 影响 |
|---|---|
| §二「哈希索引 → 部分/未落地」 | ✅ **已解决**：patch 已合入（OPT-7），主键哈希已落地（容器 slot 2 `idHash`），不再是「测试期工具」 |
| §七「运行期查询走二分」 | ✅ **已解决**：`ByID` 已改为哈希（6.02 ns），**二分查找已从读路径彻底移除**（无 `IndexSearch` / `lower_bound` / `gd_index_bsearch`） |
| **C4（O(1) 哈希索引）** | ✅ **已全部落地**：主键哈希 + **CodeName 二级索引**（2026-09-12 接线，API `ByCodeName`）；**Group 索引已整体删除**（容器 slot 4/5 空出） |
| §六「record 用 table 的影响」 | ✅ 结论不变（table 只值 1.4–1.5× 常数因子）；但**「查询索引差一个数量级」那一行已被 patch 修掉** |
| §四 C0（恢复 i18n 稀疏表） | ✅ **已解决（2026-09-11）**：C0 已落地，当前就是「main + i18n 稀疏表」；当年「最高优先」的论据（patch 实测 4.4× 膨胀）见下 |
| §五「改动 8 不在 WireReader 重建之列」 | ⚠️ **部分失效**：patch 把 reader 重建与索引实现一并做了，落点是 OPT-1/3/5/9 |

**patch 暴露的两个 i18n 论据**（直接支持「保留 i18n 稀疏表」决策）：
- `check_bundle_duplication.py`：canonical「每语言整包」在 3 语言时已膨胀 **3.29×**；
  且 `ComplexShowcase` / `UIConfig` 三语言**逐字节相同**（纯浪费）。
- 换算到 参考实现 规模（1 主包 + 9 语言包 ≈ 153 MB）：canonical 式 10 份全量 ≈ **680 MB ≈ 4.4×**。

**patch 新发现的两个待办**（本清单此前没有）：
- ~~`canonical_export.py:211` **硬编码 `indexes=()`** → 二级索引（Code/Group）能力写好了、出口没接~~ ✅ **已解决（2026-09-12）**：`canonical_export.py` 现在从 schema 的 `TableResource.indexes` 取真实索引（原硬编码那行已移位，不再写死 `()`）；CodeName 索引已端到端接线。
- ~~**枚举只 cast 不产出声明**~~ ✅ **已解决（C6，2026-09-11）**：生成物仍有 `(ItemRarity)WireReader.I8(_row, 10)` 的 cast，**且现在会产出枚举声明** —— `Enums.cs` / `Enums.lua` 已发出，业务侧不必再手写 `enum X : byte`。原文如下（历史快照）：生成物是 `(ItemRarity)WireReader.I8(_row, 10)`，但 `output/generated/csharp/`
  **没有产出 `enum` 声明** → 业务侧仍要手写 `enum X : byte` 才能编译，盲 cast 错位风险照旧。

**patch 顺带发现的隐患**：`gd/output/fbs/` 里留有 2026/8/14 的陈旧 `*_i18n.fbs`，
而全仓已无代码生成它们、`ct export` 也不清理 `output/` → 消费方会误以为 i18n 侧表还在，
**正好与「保留 i18n 稀疏表」的决策撞车**。建议 `ct export` 写出前清理 `output/fbs` 与 `output/generated`。

> **定宽布局决策已拍板为「逐表按填充率开」，且发现并验证了 patch 的一个枚举字段 bug**——
> 见 fabulous-game `Docs/TODO/定宽布局落地方案.md`。
> **完整汇总见 fabulous-game 侧新建的《参考实现原生对标实测-2026-09-10.md》**，
> 含 OPT-1~OPT-9 逐项实测、P8 前提被证伪的细节、定宽布局决策（填充率代价表）、
> 等价性校验抓到的 4 个真实 bug、3 个测量陷阱。

---

## 一、背景：架构已双向演进，早期设计部分失效

fabulous-game 侧在 2026-08 做了一轮配置系统性能优化设计（8 个改动 + 实测报告）。ct-tool 在 2026-09 独立演进并实施了其中**大部分目标，但方式不同**。

**✅ 已拍板（2026-09-10）：保留「main + i18n 稀疏表」架构**

| | 架构 | 说明 |
|---|---|---|
| **目标架构（已定）** | **「main(zh 全量) + i18n 稀疏表」** | `data_zh.bin` = 主表全量字段；`data_{lang}.bin` = 独立 `_i18n` 稀疏表（`ItemType_i18n / Item_i18n / Quest_i18n`，只含主键 + i18n 字段） |
| **当前资产产物** | 同目标架构 | `fabulous-game/Client/Assets/Content/Config/` 即此形态（Aug 23-24 产物） |
| **ct-tool 新版代码（现状）** | ✅ **已解决（2026-09-11，C0）** —— **当前就是「main + i18n 稀疏表」** | 下表是 2026-09-09 的历史快照：~~❌ **不符**：已改为「每语言一份完整 bundle」~~ `ct/src/ct/app/canonical_export.py:194-202` 的 `_merge_i18n` 把翻译合并进全量行数据 → `data_{lang}.bin` 是该语言完整表，**不产 `_i18n` 表**。**当前实情**：稀疏 `{Table}_i18n` 表**确实产出**（行序与主表 1:1，读端按行下标读）；主语言 `data_zh.bin` 为主表全量，其余语言为 i18n-only 包。旧路径 `app/export.py` / `export/binary_writer.py` **已删除**，CLI 只走 `run_canonical_export` |

**→ 由此产生 ct-tool 侧的**最高优先待办 C0：恢复 i18n 稀疏表的产出**（见第四节）。✅ **C0 已于 2026-09-11 完成**（见下）。

**影响**：fabulous-game 侧的改动 1（i18n 与主表同序）/ 5（切语言只换 i18n）/ 7（Lua 按下标读 i18n）**全部有效**，按原设计实施（前置是 C0 完成）。

> 教训记录：不能只看代码就断定架构变化——**资产产物与新版代码可能不一致**，需以实际重导后的产物为准。

---

## 二、ct-tool 已实施（对照早期设计）

| 早期设计（fabulous-game 方案） | ct-tool 实际 | 差异 |
|---|---|---|
| web 端结构化 schema 编辑器（不暴露 YAML） | ✅ `schema_workspace`（Draft→ChangePlan→Apply 事务模型）+ Tables/Records/Enums 三类资源 + Enum 按序 item 编辑器 + ordinal 风险提示 + Quick Open + 响应式布局 | **实施且远超设计**；规格 `openspec/specs/schema-editor/{workbench,workspace-draft,type-system}` |
| 类型名 `array` → `vector` | ✅ `type_expression.py`：`vector<T>` 文本表达式；`RESERVED_TYPE_NAMES` 含 vector | 且引入 `record`/`enum` 具名资源（类型从「字段内联」变「具名引用」） |
| 定长数组展开（早期命名 `fixed_length`） | ✅ 字段名 **`excel_columns`**（展开组数，仅 `vector<T>`）；`separator` 已移除 | **命名不同**，语义更准 |
| `array<struct>`（真数组可遍历） | ✅ `vector<Record>`，必须配 `excel_columns` | 与设计一致（定长才允许） |
| 字符串零分配（早期：按行 `string[]` 缓存） | ✅ **`NStringCache` 字符串驻留**（`openspec/specs/flatbuffers-export/spec.md:116` 独立 Requirement「Reader runs standalone and String fields are interned」） | **方案不同**：内容驻留（全局去重）vs 按行缓存；更通用 |
| 哈希索引（早期：idHash/nameHash/groupHash） | ⚠️ **本地仓库：部分/未落地**（2026-09-10 核实修正，详见 §七）；**patch 已修主键部分**（OPT-7，见 §〇）：<br>• **ByID = 二分查找**，非哈希——`ConfigReader.ByID` → `WireReader.IndexSearch`（stride 8 的 `(id, 原行下标)` 有序数组）；二进制只带这一个 `index` 向量（`canonical_binary.py:218-227`）<br>• **ByCode / ByGroupKey = stub**——`Runtime.cs:195-196` `ByCode→-1`、`GroupKey→Array.Empty<int>()`；`canonical_binary.py` **完全不导出** code/group 索引数据<br>• `export/index_query.py`（FNV-1a 64-bit）**只被 `ct/tests/export/test_query_indexes.py` 使用**，**未接入导出流水线、未进入二进制、运行期无人调用** | ❌ **不是「已实施」**：哈希只是**测试期工具**；运行期主键走 O(log N) 二分（5万行实测 41.9–77.6ns vs 哈希 0.79–1.51ns，**43–66× 差距 = 一个数量级**）；Code/Group 运行期**未实现** |
| 数组遍历 API | ✅ `NArray<T>`（`Tags.Length`/`Tags[i]`/`foreach`）、`vector<Record>`→`NStructArray<T>`、`vector<string>`→`NStructArray<NString>`（`spec.md:63`） | 已实现，O(1) 直读（构造时捕获 `VecBase`） |
| 类型化枚举 / 跨表 ref | ✅ `spec.md:55/59`：enum 返回 `(EnumType)`；跨表 ref 类型化访问（id→行缓存，避免每字段 P/Invoke） | 已实现 |
| 嵌套边界（不做 flatbuffers 不支持的结构） | ✅ `vector<vector<T>>` 明确拒绝（`type_expression.py:104-109`「首版不支持；请使用具名 Record 包装结构」） | 与设计一致 |
| 字符串池去重（`CreateSharedString`） | ✅ 保留（`canonical_binary.py` 3 处 `CreateSharedString`） | 已实施 |
| **struct 改真 struct（内联定长）** | ❌ **明确否决**：spec 规定「使用 FlatBuffers **table**，而非 struct」（`spec.md:18-20`），`canonical_binary.py` 仍用 `StartObject` | ⚠️ **与早期建议相反** |

---

## 三、早期设计在「保留 i18n 稀疏表」下的有效性

| 早期设计 | 状态 |
|---|---|
| **i18n 与主表同序** | ✅ **有效**（ct-tool 侧改动：`_i18n` 表导出时保持与主表 items 同序） |
| **bin 产物目标：main(zh) + i18n 稀疏表** | ✅ **有效**（已拍板）；**ct-tool 新版导出需恢复该形态**（待办 C0） |
| **切语言只换 i18n（main 不动）** | ✅ **有效**（切语言只替换 `data_{lang}.bin` 稀疏外挂） |
| **Lua 按下标读 i18n（`GD_UD` + idx + `I18nMeta`）** | ✅ **有效**；⚠️ 需按 ct-tool 新 Lua Accessor 形态（基址捕获 + 惰性表，`spec.md:83-84` Requirement「Generate canonical Lua Accessor with query API and typed fields」）对齐 |
| **字符串缓存的两类失效边界（i18n / 普通）** | ✅ **有效**（i18n 字符串随稀疏表切换失效，普通字符串不失效） |
| **`InvalidateI18n`（只清多语言缓存）** | ✅ **有效** |
| **按行 `string[]` 缓存数组** | ⚠️ **建议不做**：与 `NStringCache` 驻留功能重复，应统一到 `NStringCache`（避免两套机制并存） |

---

## 四、ct-tool 侧剩余待办

| # | 待办 | 说明 |
|---|---|---|
| **C0** | ✅ **已完成（2026-09-11）** ~~恢复 i18n 稀疏表的产出~~ | **spec 本就要求 i18n 稀疏表**：`openspec/specs/flatbuffers-export/spec.md:30-32`「item.fbs 额外包含 `table ItemI18nEntry { id: int32; name: string; }` 和 `table ItemI18nTable { entries: [ItemI18nEntry]; }`」。但当时（2026-09-09）**实现里完全没有 `I18nTable`/`I18nEntry`**（`canonical_binary.py` / `canonical_fbs.py` 均无），而是 `canonical_export.py:194-202` 改为「每语言完整 bundle」。**这是实现偏离 spec，不是架构回退**。需：① 按 spec 构建 `_i18n` 表（主键 + i18n 字段，**与主表同序**）；② bundle 分离为 `data_{zh}.bin`(主表全量) + `data_{lang}.bin`(稀疏 i18n)；③ 导出/JSON/accessor/校验全链路适配。**这是 fabulous-game 侧改动 1/5/7 的前置**。 |
| C1 | ✅ **已完成（2026-09-11）** ~~补标量类型~~（12 种标量；Lua 侧绑定待原生补，见 N9） | `type_expression.py` 的 `ScalarName` 仍只有 `int32/int64/float/double/bool/string`。flatbuffers 原生支持这些标量，补齐对齐。影响：`type_expression.py`、`canonical_binary.py`（slot/vector writers）、`canonical_accessor*.py`（C#/Lua 类型映射）、reader 侧（跨到 fabulous-game） |
| ~~C2~~ | ~~确认 `index_query.py` / `indexes.py` 是否已完整覆盖「主键 / Code / Group 三类查询」~~ | ✅ **已核实完毕（2026-09-10）→ 结论：未覆盖！** 见 **§七**。运行期 ByID 走二分、ByCode/ByGroupKey 是 stub、`index_query.py` 只在测试里。**实际待办已升格为 C4** |
| C3 | ✅ **已完成（2026-09-11）** ~~明确 i18n 稀疏表架构下的语言切换与缓存语义~~ | spec 新增 3 条 Requirement（同序等长 / 切语言只换 i18n 包 / 按下标读+原文回退）；运行时落地独立 i18n 世代（`TableVersion.I18nCurrent`）——切语言只失效 i18n 表缓存，主表行句柄保持有效 |
| **C4** | ✅ **已完成（2026-09-11；Group 部分已于 2026-09-12 砍掉）** | 主键哈希（patch OPT-7）+ **CodeName 二级索引**落地（Group 已砍，见文首时效提醒）：`QueryIndex` 移入 resources 使索引可持久化（原先在 `stage_candidate_yaml` 被丢弃）→ `TableResource.indexes` → `canonical_export` 用真实索引。⚠️ **下面这半句是 2026-09-11 的实现快照，命名与槽位均已被后续重构取代**：~~二进制容器 slot 3(Code 桶表)/slot 4(Group 扁平对) → `ConfigTable.CodeSearch/GroupKey` + `Runtime.ByCode/GroupKey` 实测可用（3 次命中 + 1 次未命中 + 4 个分组全对）~~。**当前实情**：容器 slot 3 是 `codeNameIndex`（存 `rowIndex + 1`，key = FNV-1a 64），**slot 4/5 随 Group 索引删除而空出**；运行时符号是 `CodeNameSearch` / `Runtime.ByCodeName`（生成 API 为 `ByCodeName(codeName)`）；**`CodeSearch` / `GroupKey` / `ByCode` / `ByGroupKey` / `groupHash` 均已不存在**（`groupIndex` 一名仍在 Excel 列布局 manifest 里表示「列分组序号」，与查询索引无关） |
| **C5** | ✅ **已完成（2026-09-11）** ~~逐表按填充率开（决策 B）~~：枚举 bug 已修 + A1~A5 接线全部落地（填充率统计 / 逐表决策 / probe 落盘 / 生成器二选一 / 导出期单 vtable 硬断言） | **决策（2026-09-10）**：`fill_rate >= 0.75` 的表开 `uniform=True` + 字面量访问器，否则保持变长 + 偏移表。**⚠️ 前置 bug（本地实测，2026-09-11）**：patch 的 uniform **只给标量加了无条件写槽位，枚举分支没加**（仍是 `PrependInt8Slot(..., 0)`，值为第 0 项时省略槽位）⇒ ① 含枚举的表定宽后**仍是 2 种 vtable**（`Item`/`UIConfig` 实测）；② `probe_row_layout` 给枚举槽位推出 **offset=0** ⇒ 字面量访问器读 `row+0`（vtable soffset）⇒ **静默读错**（`Item` 定宽字段 6/16 处不一致，连 `Id`/`Price` 都错——缺槽位错位整行）。**patch 的基准表一个枚举字段都没有**（`build_item_bench` 的 `enums={}`），所以它的等价性校验漏掉了。**修法已验证并已落地（2026-09-11）**：`canonical_binary.py` 新增 `_prepend_enum()`（uniform 走 `PrependInt8` + `Slot(index)`），`_build_row`/`_build_record` 两处改用；新增 **6 个回归测试**（已验证「回退修复则 4 红」）；**patch 已合入本仓库**（`git apply` 干净），全量 **337 passed**（**2026-09-11 快照**；**当前为 403 passed**），真实代码复验 G1/G2/G3 全过。**填充率实测**（fixture，与本项目表结构相同）：`Item` 92.9%（1.08×）、`ItemType` 100%、`Quest` 100% → ✅ 开；`UIConfig` **63.3%（1.58×）→ ❌ 不开**（被 `BlocksRaycast` 16.7% / `Stack` 33.3% / `Layer` 66.7% 拉低）。**完整方案见 fabulous-game `Docs/TODO/定宽布局落地方案.md`**；**分批见 `Docs/TODO/开工方案.md` 批次 A**。**✅ 批次 A 已全部落地（2026-09-11）**：`written_slot_ratio`/`count_vtables`（从真实字节统计）+ `UNIFORM_FILL_THRESHOLD=0.75` 逐表决策 + manifest 落 `uniform`/`fill_rate`/`slot_offsets` + 生成器 `ROW_MODE_{SLOT,OFFSETS,LITERAL}` 三态（定宽行句柄不带 `_off[]`）+ **导出期单 vtable 硬断言**。验收（**2026-09-11 快照**）：**352 passed**；导出级逐字段比对 **93 个字段值 0 处不一致**。**当前值：403 passed / `test-proj/ExportAccessorVerify/` 127 个字段值 0 处不一致** |
| **C6** | ✅ **已完成（2026-09-11）** ~~产出枚举类型声明~~ | 生成物已有 `(ItemRarity)WireReader.I8(_row, 10)` 的 cast，但 `output/generated/csharp/` **不产出 `enum X : byte { ... }` 声明** → 业务侧仍要手写才能编译，**盲 cast 错位风险照旧**。信息在 `config/types/*.yaml` 的 `values` 里是完备的，成本低（Lua 同理） |
| **C7** | ✅ **已完成（2026-09-11）** ~~清理 `output/` 陈旧产物~~ | `gd/output/fbs/` 里 `Item_i18n.fbs` / `ItemType_i18n.fbs` / `Quest_i18n.fbs`（mtime **2026/8/14**）与其余（2026/9/10）并存，而**全仓已无代码生成 `*_i18n.fbs`**。风险：消费方扫 `output/` 会拿到**描述已废弃 i18n 侧表格式**的 schema，**正好与「保留 i18n 稀疏表」决策撞车**。建议 `ct export` 写出前清理，或校验目录内无未知文件 |
| — | **（已确认不做）** 字符串冷扫 / 解码（1.45× / 1.36×） | 托管 `Encoding.UTF8.GetString` 相对原生 `memcpy` 的**固有开销**，OPT-8 后成本已回到解码本身（冷扫 66.7 vs 绕缓存解码 46.6），**接近地板，不改** |

---

## 五、fabulous-game 侧需要配合 ct-tool spec 的工作

ct-tool 的 `openspec/specs/flatbuffers-export/spec.md` 已把 **C#/Lua accessor 契约**写成规格，但 fabulous-game 侧的 `WireReader.cs` **仍是 2026-08-25 的旧版**，尚未按新 spec 落地：

| spec 要求 | fabulous-game 侧现状 |
|---|---|
| `NArray<T>` / `NStructArray<T>`（vector 单一可索引/可枚举容器，构造时捕获 `VecBase`，O(1) 直读） | ❌ `WireReader.cs` 无 `NArray`/`VecBase` |
| `NStringCache`（字符串驻留，相同字符串只分配一次） | ❌ 无 |
| 类型化枚举（enum 返回 `(EnumType)`，非裸 int） | ❌ 无（生成 accessor 返回裸 `byte`） |
| 跨表 ref 类型化访问（`ItemTypeRow ItemType => ItemTypeAccessor.ByID(ItemTypeId)`，id→行缓存） | ❌ 无 |
| reader standalone（纯 C# + unsafe，不依赖 Unity/游戏） | ⚠️ 当前 `WireReader.cs` 在 Unity 工程内 |
| `Count/ByID/ByIndex` 查询 | ✅ 已有（`ByID` 用二分，非哈希） |
| `Unsafe.ReadUnaligned`（早期改动 3，`spec` 未强制但性能相关） | ❌ 仍是字节拼装 |

**建议**：fabulous-game 侧按 ct-tool 的 `flatbuffers-export` spec 重构 `WireReader.cs` + 生成 accessor，这**替代**了早期设计的改动 2/7 的 C# 侧部分。
- ⚠️ **改动 8（哈希索引）（2026-09-10 更新）**：**主键部分 patch 已实现**（OPT-7，实测 6.02 ns，反超 参考实现 11.21 ns）；**Code/Group 二级索引仍未接**（C4 余项）。
- ⚠️ **重建 `WireReader.cs` 时不要照 spec 字面做，要按 patch 的 OPT-1/3/5/9 做**：OPT-1（行句柄携带**按 vtable 身份记忆化**的偏移表）、OPT-3（表句柄缓存 + **世代守卫**）、OPT-5（index 基址预解析）、OPT-9（**单缓冲视图**：整包 pin 一次、每表 `(offset,length)` 切片，加载 0.43×）。**spec 只定了接口契约，没定这些实现选择**。

---

## 六、record 用 FlatBuffers table 对性能对齐的影响（2026-09-10 分析）

**问题**：ct-tool 的 record 是 FlatBuffers **table**（非 struct），会影响「对标 参考实现」的性能目标吗？

**事实**：
- record 构建用 `builder.StartObject`/`EndObject`（table，vtable + offset）——`canonical_binary.py:80-93`
- `vector<Record>` 是 **offset vector**（元素存 table offset，遍历需解引用）——`canonical_binary.py:_build_vector`
- spec 明确规定「使用 FlatBuffers **table**，而非 struct」（`spec.md:18-20`）

**逐项对比 参考实现**：

| 维度 | ct-tool（table） | 参考实现（定宽 struct） | 差距 |
|---|---|---|---|
| 主键查询（ByID） | **O(log N) 二分**（`IndexSearch`）；⚠️ **patch OPT-7 已修为 O(1) 哈希**（6.02 ns） | O(1) 哈希 | ❌ 差一个数量级 → **patch 已修（见 §〇/§七）** |
| Code/Group 查询 | **stub，二进制无索引数据**（patch 也没做） | O(1) 哈希 | ❌ **仍未实现**（见 §七） |
| ByIndex 下标查询 | O(1)（`RowAt`） | O(1) | 持平 ✅ |
| 字符串读取 | `NStringCache` 驻留（零分配） | 字符串池 + 偏移 | **持平** ✅ |
| 数组遍历 | `NArray<T>`/`NStructArray<T>`（`VecBase` O(1) 直读） | 类似 | **持平** ✅ |
| 字段定位 | vtable 遍历 4 步 | 固定偏移 1 步 | **1.4-1.5×（约 1.5ns）** ⚠️ |
| `vector<Record>` 逐元素 | 解引用 offset | 内联，直接算偏移 | 每元素多 1 步 ⚠️ |

（字段定位差距依据：fabulous-game `Config重构性能实测报告-综合.md` §六·十一 实测）

**结论**：
1. **table 本身不影响数量级对齐**——但注意：**查询索引另有一处数量级缺口**（ByID 走二分、Code/Group 未实现，见 §七），那是**索引问题，不是 record 用 table 造成的**。就 table 而言，字符串零分配（`NStringCache`）、容器 O(1) 直读（`NArray<T>`/`NStructArray<T>` + `VecBase`）ct-tool **已覆盖**。
2. **table 只影响「字段定位的常数因子」（1.5ns / 1.4-1.5×）**——对应 fabulous-game 方案里**已推迟的 P8（字段偏移表）**，是纳秒级、非数量级。**别把它和 §七 的查询缺口混为一谈**：字段定位是 1.5×，查询索引是 43–66×。
3. **table 是有意识的取舍**：record（table）可含 **string / vector**；真 struct **只能含标量/struct**（flatbuffers 官方限制）。**强制改 struct 会让 record 失去「含 string 字段」的能力**。
4. **不建议改**：数量级已对齐；若将来要那 1.5×，可做 P8（缓存 vtable 解析结果，需注意 vtable 可能因字段缺省而不一致），收益有限。
5. **可留意的优化点**：`vector<Record>` 的 offset vector 在**大批量逐元素遍历**时每元素多一次解引用；当前配表场景元素少，影响小。

### 附：一处 spec 措辞需澄清（2026-09-10 核实，实现 `WireReader.cs` 前必读）

`spec.md:101-103` 写（Requirement「Vector container captures the vector base once」的 scenario）：
> - **WHEN** 访问 `row.Tags[i]`
> - **THEN** 容器持有基址，`[i]` 直接按 `base + i*stride` 读取；**不逐元素调用 `WireReader.Indirect`**

这句**只对标量向量字面成立**：
- `vector<int32>`：元素内联，stride = 4，`base + i*4` 直达 ✅
- `vector<Record>` / `vector<string>`：元素是 **uoffset**，`base + i*4` 拿到的是**偏移槽**，仍须跟一次偏移才能到 table/string ❗

ct-tool 自己的 reader 实现正是如此——`test-proj/ConfigAccessorBench/WireReader.cs` 的 `RowAt`：
```csharp
public static IntPtr RowAt(IntPtr itemsBase, int idx)
{
    byte* pos = (byte*)itemsBase + (long)idx * 4;
    return (IntPtr)(pos + GetI32(pos));   // ← 每元素一次 uoffset 解引用（不可省）
}
```
注释也自述「按行下标解析行对象指针（**items 向量 uoffset 元素**）」。

**所以要澄清的是**：`不逐元素调用 Indirect` 的**本意是「不在索引时重复解析 vtable / 不重复 `FieldOffset`」**（容器构造时已捕获基址，索引沿 stride 走），**不是「零解引用」**。`vector<Record>` 每元素一次 uoffset 解引用是 FlatBuffers 偏移式布局的**固有成本**，无法通过 reader 设计消除——只有把 record 改成真 struct（内联）才能消除，而 spec 已明确否决（`spec.md:18-20`）。**建议把 spec `Vector container captures the vector base once` 的该 scenario（`spec.md:101-103`）改为按元素类型分别陈述**，避免实现者误以为可以零解引用。


## 七、⚠️ 重大修正：运行期查询路径实际是「二分」，哈希索引未落地（2026-09-10 核实）

> ## ✅ **2026-09-12：本节已全部过时（ByID 部分）**
> 主键哈希已在**两侧**落地：C# `ConfigTable.HashSearch` + 原生 `gd_index_hash`；
> `gd_index_bsearch` / `ConfigTable.IndexSearch` / `WireReader.IndexSearch` **均已删除**，
> 且 **Group 索引改为容器 slot 5 的区间哈希**（不再二分）。
> **仍成立**的是 §7.2（Code/Group 未接线 —— 现在叫 fabulous-game 侧 **W1**）。

> ## ✅ **2026-09-10 晚些时候：本节的「缺口」已被 ct-tool patch 的 OPT-7 修掉**
> **对本地仓库，本节全部内容仍然成立**（本地仍是二分、`ByCode/GroupKey` 仍是 stub、`index_query.py` 仍在测试里）。
> 但 patch 已实现主键哈希索引（**6.02 ns vs 参考实现 11.21 ns，反超**），**合入后 §7.1 与 §7.5 的 ByID 行即失效**。
> §7.2（Code/Group stub）与 §7.3（`index_query.py` 只在测试里）**仍未解决**——patch 只做了 int 主键，
> 字符串 Code/Group 索引依旧没接线。详见上节 §〇 与 fabulous-game 侧《参考实现原生对标实测-2026-09-10.md》。

**背景**：早期把「`index_query.py` 存在 FNV-1a 哈希」直接判为「改动 8（哈希索引）已实施/已被覆盖」。**逐层追调用链后，这个判断是错的。**

### 7.1 运行期 `ByID` 走的是二分查找

调用链：
```
ItemAccessor.ByID(id)                        canonical_accessor.py:185-187
  → Runtime.ByID(TableName, id)              Runtime.cs:190
    → ConfigTable.ByID(id)                   ConfigReader.cs:41-45
      → WireReader.IndexSearch(Table, id)    WireReader.cs:60-77   ← 二分
      → WireReader.RowAt(ItemsBase, idx)
```

`WireReader.IndexSearch` 是标准二分（`WireReader.cs:60-77`）：
```csharp
byte* entries = lenp + 4;
int lo = 0, hi = GetI32(lenp) - 1;
while (lo <= hi)
{
    int mid = (lo + hi) / 2;
    byte* e = entries + (long)mid * 8;
    int midId = GetI32(e);              // 元素 = (id, 原行下标)，stride 8
    if (midId == id) return GetI32(e + 4);
    if (midId < id) lo = mid + 1;
    else hi = mid - 1;
}
return -1;
```

对应导出侧（`canonical_binary.py:218-227`）只产出**一个** `index` 向量：
```python
ordered = sorted(enumerate(rows), key=lambda item: int(item[1].get(primary, 0) or 0))
builder.StartVector(8, len(ordered), 4)
for original_index, row in reversed(ordered):
    builder.PrependInt32(original_index)
    builder.PrependInt32(int(row.get(primary, 0) or 0))
index_vec = builder.EndVector()
```

→ **运行期主键查询 = O(log N) 二分**，与 参考实现 的 O(1) 哈希**不在同一数量级**。

### 7.2 `ByCode` / `ByGroupKey` 运行期是 stub

`test-proj/ConfigAccessorBench/Runtime.cs:194-196`：
```csharp
// 可选 Code/Group 索引（生成器仅在配置索引时调用）
public static int ByCode(string tableName, int slot, string code) => -1;
public static int[] GroupKey(string tableName, int slot, int value) => Array.Empty<int>();
```

且 `canonical_binary.py` **搜不到任何 code/group 索引的导出逻辑**（`grep -n "code\|group" canonical_binary.py` 无命中）。
→ 生成器会**生成** `ByCode`/`ByGroupKey` API（`canonical_accessor.py:212-238`，按 `model.indexes` 是否配置），但**底层无数据、无实现**——端到端**未落地**。

### 7.3 `index_query.py` 的 FNV-1a 哈希只在测试里

```
$ grep -rn "index_query\|StringIndex\|production_hash" --include=*.py ct/ | grep -v "export/index_query.py"
ct/tests/architecture/test_architecture.py:118   # 仅「期望存在的模块」清单
ct/tests/export/test_query_indexes.py:7,77,86,102,103,117   # 单测
```
**导出流水线（`app/canonical_export.py`、`export/canonical_binary.py`）零引用。**

### 7.4 实测差距（来自 fabulous-game 侧基准，见其 `ByID查询性能实测-二分vs哈希.md`）

5 万行、200 万次查询：

| 实现 | C# (RyuJIT) | C++ (clang) |
|---|---|---|
| 二分查找 | 41.9–77.6 ns | 26.1–51.3 ns |
| 开放寻址哈希 | **0.79–1.51 ns** | **2.12–2.29 ns** |
| **倍数** | **43–66×** | **12–24×** |

→ **这正是「至少和 参考实现 同一数量级」目标下唯一尚未闭合的数量级缺口。**

### 7.5 结论与影响

| 查询 | ct-tool 现状 | 参考实现 | 是否对齐 |
|---|---|---|---|
| `ByIndex` | O(1)（`RowAt`） | O(1) | ✅ 对齐 |
| `ByID` | **O(log N) 二分** | O(1) 哈希 | ❌ **差一个数量级** |
| `ByCode` | **stub，无数据** | O(1) 哈希 | ❌ **未实现** |
| `ByGroupKey` | **stub，无数据** | O(1) 哈希 | ❌ **未实现** |

**对 §六 对比表的更正**：§六 表中「主键查询 / Code / Group 查询 → 持平 ✅」**基于错误前提**，现更正为：ByIndex 持平；ByID/ByCode/ByGroupKey 未对齐（见本节）。

**这是 ct-tool 侧最高优先的性能待办**（与 C0 并列，建议编号 **C4**）：把 `index_query.py` 的 FNV-1a 哈希桶**接入导出流水线**（按 `indexes.py` 声明的 Code/Group 索引 + 主键哈希），写入二进制，并在 reader 实现 O(1) 查询，替代当前二分。

---

## 八、参考（fabulous-game 侧文档）

- `fabulous-game/Docs/TODO/方案/配表Schema演进.md` —— schema 演进方向 + 实施状态对照
- `fabulous-game/Docs/TODO/参考/flatbuffers类型体系与嵌套约束.md` —— vector/array/table 机制与嵌套约束
- `fabulous-game/Docs/TODO/方案/Config性能优化-最终修改方案.md` —— 8 个性能改动 + 实测（注意：其 ct-tool 部分需按本文对齐）
- **`fabulous-game/Docs/TODO/实测/参考实现原生对标实测-2026-09-10.md`** —— ⭐ **最新最权威**：本 patch 的完整汇总
  （真·参考实现 原生对标方法、OPT-1~OPT-9 逐项实测、P8 前提被证伪、定宽布局决策与填充率代价表、
  等价性校验抓到的 4 个真实 bug、3 个测量陷阱、跨仓库发现）
- `fabulous-game/Docs/TODO/实测/Config重构性能实测报告-综合.md` —— 性能实测证据库
**入口（先看这个）**：`fabulous-game/Docs/TODO/开工方案.md` —— 唯一权威状态板；`fabulous-game/Docs/TODO/README.md` —— 全部文档的索引与时效标注
- ct-tool 侧规格：`openspec/specs/flatbuffers-export/spec.md`、`openspec/specs/schema-editor/*/spec.md`、`openspec/specs/schema-management/spec.md`
