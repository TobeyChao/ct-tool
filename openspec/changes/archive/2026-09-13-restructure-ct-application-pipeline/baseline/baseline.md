# 基线记录（task 1.1）

本文件是 `restructure-ct-application-pipeline` 实施前的产物对照基线。后续每个阶段的
改动都必须与这里的字节和元信息一致（除非该阶段明确声明要改变行为）。

## 1. 基线提交与工作树

| 项 | 值 |
|---|---|
| 基线提交 | `95f04ad` — 增量导出：内容寻址生成缓存 + 传递闭包 schema_hash |
| 提交前序 | `66f0123` fix silent CLI filters, i18n output and the primary-key/integer domain |
| Python | 3.14.7（项目 venv） |
| 采集时工作树 | 已在基线上完成 §1 门禁修复与 contracts 提炼（见下），无其他改动 |

> 修订说明：本 change 早期版本把基线记作「HEAD `66f0123` + 未提交的增量代码」。
> 该描述已过期——增量实现随 `95f04ad` 落地，修订时工作树无本地改动。

采集时工作树中已含 task 1.2/1.3 的改动（架构门禁修复、`ct/contracts.py` 提炼、
`CSHARP_SCALAR_TYPES` 下移、以及两处 `CanonicalValidationError` 的 `Issue` 修正）。
这些改动均不改变任何生成字节，其证据是下方 `forced` 与 `normal` 的产物完全一致，
且冷启动产物在修改前后逐字节相同。

## 2. 基线工作区

`gd/` 在基线上**无法导出**（见 §6 缺陷 A/B），因此基线工作区是 gd 的临时副本，
只做一处删减：

```
/tmp/ct-baseline-ws   ← 由 gd/ 复制，排除 ComplexShowcase
```

排除 `ComplexShowcase` 需要同时移除它的 6 个文件：schema、Excel、layout manifest、
i18n source 与 en/ja 译文。其余 4 张表（Item / ItemType / Quest / UIConfig）、
全部 9 个具名类型、i18n 与跨表 ref 均保留。

**gd 本体未被修改**：`git status --short gd/` 为空。

## 3. 采集方式

`baseline/capture.py`：每个模式都把源工作区复制到临时目录，删掉派生目录
（`output/`、`cache/`、`excel/layout_manifests/`）保证冷启动，再以
`--root <副本>` 运行 `ct export`，并在**每次运行后**记录
`output/` 与 `excel/layout_manifests/` 下每个文件的 sha256 / size / mtime_ns。

```bash
python capture.py --ct <venv>/bin/ct --src /tmp/ct-baseline-ws --out .
```

## 4. 采集结果

| 模式 | 命令 | 退出码 | 文件数 |
|---|---|---|---|
| `normal` | `ct export --verbose` ×2（冷启动→warm） | `[0, 0]` | 35 |
| `filtered` | `ct export --table ItemType` | `[0]` | 14 |
| `filtered_ref_blocked` | `ct export --table Item` | `[1]` | 0 |
| `forced` | `ct export --all` | `[0]` | 35 |

### 冷启动产物清单（35 个）

```
excel/layout_manifests/   Item.json ItemType.json Quest.json UIConfig.json
output/binary/            data_zh.bin data_en.bin data_ja.bin
output/fbs/               types.fbs container.fbs Item.fbs ItemType.fbs Quest.fbs UIConfig.fbs
output/generated/csharp/  Enums.cs ItemAccessor.cs ItemTypeAccessor.cs QuestAccessor.cs UIConfigAccessor.cs
output/generated/lua/     Enums.lua ItemAccessor.lua ItemTypeAccessor.lua QuestAccessor.lua UIConfigAccessor.lua
output/json/              {Item,ItemType,Quest,UIConfig}_{zh,en,ja}.json   （12 个）
```

### 关键不变量

1. **warm 幂等**：冷启动后第二次默认导出，35 个文件的 **sha256 与 mtime_ns 全部不变**。
2. **强制与增量字节等价**：`--all` 与默认导出的 35 个文件内容**零差异**。
3. **过滤范围不扩大**：`--table ItemType` 产出 14 个文件，不含任何未选中表的
   JSON/FBS/Accessor/manifest；共享的 `types.fbs`、`container.fbs`、`Enums.cs/lua`
   仍参与导出；Bundle 只含 ItemType。
4. **ref 范围保持**：`--table Item` 仍以
   `引用表 ItemType 的数据未加载，无法校验`（4 条行级 issue）失败，不发布产物。
   这是 design 决策 6 明确要求保留的行为，**不是**缺陷。
5. **成功账本**：`cache/state.json` 格式 `canonical-cache/1`，含
   `bundles`（zh/en/ja 三个 bundle_fingerprint）与 `excel_hashes`。

## 5. 复验方式（task 6.2）

在 `/tmp/ct-baseline-ws` 上重跑 `capture.py`，与本次 JSON 逐文件比较
`sha256`。任何差异都必须能归因到某个明确的阶段决策；无法归因即为回归。

## 6. 采集期间发现的既有缺陷（均早于本 change，未纳入修复范围）

**A. `gd/` 主键类型违规 —— 阻断导出**
`gd/config/schemas/ComplexShowcase.yaml` 的 `Id` 为 `int64`，而 `66f0123` 起主键
必须是 `int32`。`ct validate --root gd` 直接失败，`ct export` 同样失败。gd 是仓库
demo 工作区与 CLI `--root` 默认值，因此「用 gd 直接做基线」不成立。

**B. `ComplexShowcase` 的 uniform 布局生成缺陷（已定位根因）**
把它的问题 A 修掉后，该表仍然导出失败：填充率 0.974 触发定宽布局，但 4 行数据
生成 **2 种 vtable**，触发 `_assert_single_vtable` 的硬断言（要求恰好 1 种）。

逐表探测显示只有这张向量/嵌套 Record 密集的表受影响：

| 表 | 行数 | client 字段 | 填充率 | uniform | uniform 下 vtable |
|---|---|---|---|---|---|
| ComplexShowcase | 4 | 19 | 0.974 | 是 | **2 ❌** |
| Item | 4 | 7 | 0.929 | 是 | 1 |
| ItemType | 3 | 3 | 1.000 | 是 | 1 |
| Quest | 3 | 6 | 1.000 | 是 | 1 |
| UIConfig | 7 | 5 | 0.600 | 否 | — |

**根因（实测，非推测）**：`uniform=True` 的承诺是「所有行共享同一 vtable」，
从而把字段偏移变成表级常量、由生成器发射字面量偏移。但 FlatBuffers 的**对齐
垫片按绝对缓冲区位置计算**：`double` 需要 8 字节对齐，而「排在它上面的字段要不
要补 4 字节」取决于构建该表对象时缓冲区已写到哪。**每行的变长负载（string /
vector / 嵌套 record）长度不同 ⇒ 垫片不同 ⇒ 表对象大小不同 ⇒ vtable 不同。**

隔离实验：

| 变体 | vtable 数 |
|---|---|
| 原表（`double` + 变长 vector） | **2** |
| 去掉 `double` 字段 `PreciseValue` | **1** |
| 保留 `double`，但强制各行变长负载等长 | **1** |

决定性证据：生成器用「单行空白行」推导的字面量偏移对 row 2 是错的，且**只有
`double` 上面**的字段错位 4 字节：

```
字段              probe   row0 row1 row2 row3
Id                  84     84   84   80   84   ❌ 错位 4
Code                80     80   80   76   80   ❌ 错位 4
Weight              76     76   76   72   76   ❌ 错位 4
PreciseValue        64     64   64   64   64   OK   ← double 本身正确
（其余 15 个字段全部 OK）
```

row 2 的 `IntValues`/`LongValues`/`RewardTiers` 都是空 vector，前面少写数据，
`PreciseValue` 的 8 字节对齐少补 4 字节。

只有 ComplexShowcase 含 8 字节对齐标量（`PreciseValue: double`；`SecretSeed: int64`
是 `server_only`，不进二进制），其余 4 张表客户端字段全为 4 字节或更小 ⇒ 垫片恒定
⇒ 1 种 vtable。

**这不是误报，而是拦住了一次静默错误发布**：若放宽断言，会导出 C# 用偏移 84 读
`Id`、而 row 2 的 `Id` 实际在偏移 80 的二进制，读到的是 `Code` 的值，无异常无日志。

**结论与处置**：表本身合法（`double` 字段 + 变长 vector 是正常需求），手动改表
只能「绕开」（删掉 `double` 字段），属于用改数据掩盖生成器缺陷。**按用户决定，
本次不修**，作为独立缺陷报告。可选修法（均只影响当前根本导不出的 ComplexShowcase，
不改变其他表字节）：
1. 保护式：`use_uniform` 增加「表存在 8 字节对齐客户端标量则不启用定宽」；
2. 对齐修复：构建表对象前把缓冲区钳到固定对齐，使垫片与本行之前的变长负载无关。

均需补 `double + 变长 vector` 的回归测试——该类输入目前**无任何测试覆盖**，
这正是它长期未被发现的原因。

**C. 校验错误路径崩溃（已修，2 处）**
`canonical_export.py` 的 uniform 断言与 i18n「同序等长」断言以**裸 `str`** 构造
`CanonicalValidationError`，而消费方调用 `issue.render()`，于是用户看到
`AttributeError: 'str' object has no attribute 'render'` 而不是诊断信息。
已改为 `Issue(table, IssueCode.TYPE, message)`；不改变任何生成字节。

**A 与 B 属于生成器/演示数据范围，本 change 的兼容矩阵承诺「FBS/Binary/Accessor
字节与 API 不变」，Non-goals 明确「不重写生成器」，因此**不在本次修复范围**，
作为独立缺陷报告。

### 采集后的外部并发改动（缺陷 B 已被他人修复）

实施期间工作树出现**非本 change 作者**的改动：`ct/src/ct/export/canonical_binary.py`
新增 `ObjectLayout` / `plan_object_layout` / `_Builder._build_uniform_object`，
做法是**按 schema 推导表体布局**、在 `StartObject` 前对齐缓冲区尾部（使外部垫片
不进入 vtable 的对象大小）、并对每个对象（含嵌套 record）逐字节校验实际布局；
`probe_row_layout` 改为直接从 schema 推导，不再用空白行探测。

**效果（实测）**：缺陷 B 已解决 —— `ComplexShowcase` 的 uniform vtable 数从 **2 → 1**。

**对基线的影响**：uniform 表的字面量偏移因此改变，基线中以下文件不再逐字节一致
（其余文件仍然一致，非 uniform 的 UIConfig 不受影响）：

```
excel/layout_manifests/{Item,ItemType,Quest}.json
output/generated/{csharp,lua}/{Item,ItemType,Quest}Accessor.*
output/binary/data_{zh,en,ja}.bin
```

这正是基线工具**按设计发挥作用**：它把一次未声明的产物变化暴露了出来。基线保留为
「外部改动之前」的参照，**未据此重新采集**——重新采集会把别人的改动当成自己的基线。

**该外部改动同时引入了 2 个测试失败**（详见 tasks.md 6.1）：

1. `tests/cutover/test_canonical_export_smoke.py::test_uniform_assertion_fires_when_slot_is_omitted`
   —— 新代码用裸 `ValueError("Uniform FlatBuffers object does not match schema layout")
   兜住了同一缺陷（仍然 fail-safe，CLI 也会渲染成 `[export error]`），但不再是
   `CanonicalValidationError`，测试断言的是后者；
2. `tests/cutover/test_canonical_export_smoke.py::test_sparse_i18n_is_much_smaller_than_full_copy`
   —— 按 schema 补齐垫片使稀疏 i18n 包变大（`en=892`，阈值要求 `< zh/2 = 886`，
   由 50.0% 变为 50.3%）。

两者都属于**生成器行为变化**的后果，不在本 change 的修复范围。

## 7. 测试基线

```
448 passed, 21 deselected（-m "not browser"）
17 passed  （tests/architecture/test_architecture.py）
```

A/B 两条路径均无测试覆盖，这正是它们长期未被发现的原因。
