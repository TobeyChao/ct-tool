# ct 运行时读取性能 —— 对标 参考实现 原生配表系统

> 结论先行：**加载持平，稳态字符串访问 ct 快 3.2×，热路径标量/向量读取 ct 慢 3.5×–9.6×（⚠️ 这是 OPT-7/OPT-8 之前的基线，见文首时效块）；
> 但慢的部分主要由两个实现层问题主导，而非 FlatBuffers 格式本身。**

---

## ⛔ 已作废 / 被取代（2026-09-12 追加）

本文是 **2026-09-10 的基线报告**，其结论已被后续优化取代：**当前口径以 `OPTIMIZATION-STRATEGY.md`（及其附录 C/D 实测）为准**。
正文的**测量数据保持原样不改写**，但下列前提已不成立，读到相应段落请按此折算：

| 正文表述 | 2026-09-12 实情 |
|---|---|
| 「热路径标量/向量读取 ct 慢 3.5×–9.6×」（L3 / §4 结论） | **OPT-1~OPT-9 之前的数字**。OPT-7（主键哈希）/ OPT-8（per-field 字符串缓存）落地后端到端行访问已反超 参考实现（`OPTIMIZATION-STRATEGY.md` 附录 C/D.5） |
| 「`ByID` 二分查找 50.4 ns」（§3.1 表格） | **二分实现下的测量**。当前主键查询走 `idHash` 开放寻址哈希，**读路径已无二分**（无 `IndexSearch` / `lower_bound` / `gd_index_bsearch`），该行只作历史对照 |
| 「该函数位于每一次字段读、**二分比较**、向量长度读取的最内层」（§3.1） | 同理：现在最内层是哈希探测与字段读，**不再有二分比较** |
| 「生成器没有接线 reader 已实现的『偏移预取』快路径」（§3.2） | **已接线**：填充率 ≥ 0.75 的定宽（uniform）表由生成器直接发射**字面量偏移**（`ROW_MODE_LITERAL`），字段读不再每次重走 vtable |

> 数字口径：`ct` 全量测试当前 **403 passed**；导出级逐字段校验 **127 个字段值 / 0 处不一致**（`test-proj/ExportAccessorVerify/`）。

---

## 1. 对标方法（为什么这次是真对标，不是模型复刻）

参考实现 的配表运行时是**原生 C++**，通过 `DllImport("xlua")` 暴露给 C#
（`client/Assets/Scripts/Frameworks/Configs/Runtime/Config/NativeAPI/Config.NativeAPI.cs`）。
Android/iOS 插件之外，仓库里**存在 Windows x64 构建**：

```
client/Assets/Plugins/x86_64/xlua.dll   1,204,224 bytes
```

实测 `LoadLibrary` + `GetProcAddress` 全部 18 个配置符号均可解析：

```
TableInit  TableShutdown  GetTableIndex  GetConfigDataPointer  ConfigByID
ConfigByStringID  GetConfigCount  ConfigByIndex  ConfigByGroupKey  GetTableVersion
GetI18N  SetLang  GetLang  LoadVTable  VTableFind
SetProcessLoadedBytesCallback  SetUseDecryptProcess  OpenConfigToolNative
```

于是**在同一个 .NET 进程里同时跑 参考实现 原生运行时和 ct reader**，同一台机器、同一 JIT/GC 配置、
逐场景交替计时。**没有做任何“读取模型复刻”** —— 参考实现 侧读的是它自己的真实二进制数据。

### 数据与规模

| | 参考实现（真实数据） | ct（基准复刻） |
|---|---|---|
| 数据源 | `client/Assets/Data/ConfigData/` | `fixtures/*.bin`（生成脚本合成） |
| 表数 | 2012 | 2000 |
| 行数 | **691,518** | **692,110**（差 0.09%） |
| 体积 | Main.bytes 68.4 MB + 9 语言包 = **146.7 MB** | **105.8 MB**（单语言） |
| 行/字节 | 222 B/row | 160 B/row |

单表场景用两张真实表对齐形状：

| 场景 | 参考实现 真实表 | ct 复刻表 | 行数 |
|---|---|---|---|
| 标量/字符串 | `Item`（36 字段、3 个 i18n 串、1 个 `vector<string>`） | `ItemBench` | 6685 = 6685 |
| 整数向量 | `Skill`（10 个 `NArray<int>`） | `ArrayBench` | 6048 = 6048 |

ct 侧 accessor 由**真实生成器** `ct.export.canonical_accessor.render_csharp_accessor` 产出
（`ItemBenchAccessor.g.cs` / `ArrayBenchAccessor.g.cs`），不是手写镜像。

### 测量纪律

- 预热 1 轮 + 取 5 轮最优，全部场景两侧交替。
- 所有按下标访问走 64K 预计算索引表（`i & 65535`）—— `i % 6685` 的整数除法本身
  就是几十个 cycle，会污染每一轮计时。**第一版基准踩过这个坑，数值被整体抬高。**
- 冷读场景每轮用「世代前进」让 ct 的字符串驻留缓存整体失效（`TableVersion.Bump()` →
  新 `ConfigTable` 捕获新世代 → 首次 `NString` 读取触发 `NStringCache` 清空），保证是真冷启动。

### 复现

```powershell
cd test-proj\RefConfigBench
dotnet run -c Release -- bench 1000000 2000000 5   # 微基准
dotnet run -c Release -- load 3                    # 加载耗基准
dotnet run -c Release -- dump                      # 校验 参考实现 行布局/字符串解码
```

---

## 2. 结果

### 2.1 加载阶段（启动期一次性成本）

| | 参考实现 `TableInit` | ct `LoadBundle` | 比值 |
|---|---|---|---|
| 首次加载（冷页缓存） | 216.2 ms | — | — |
| 热解析（best of 3） | **62.6 ms** | **63.2 ms** | **1.01×** |
| 托管读盘（`File.ReadAllBytes`） | 计入上行 | 22.0 ms | — |
| 端到端 | **62.6 ms** | **87.2 ms** | **1.39×** |
| ns/row | 91 | 126 | 1.39× |
| MB/s | 2342 | 1213 | 1.93× |

**解析步骤与原生完全持平**（63.2 vs 62.6 ms）；唯一的加载期损失是 ct 多一次托管侧
整包读入（105.8 MB / 22 ms ≈ 4.8 GB/s，本身不慢，但它是纯额外的拷贝）。
注意 参考实现 的 `TableInit` 自带原生读盘，而 ct 的 `LoadBundle` 不含读盘，上表已拆开对齐。

> `WireReader.ReadBundle` 目前对每张表做一次 `byte[]` 拷贝（2000 次分配）。
> 若改为「整包一份 pinned buffer + 每表 (offset,len) 视图」，读盘+解析可合并为一次，
> 且省掉 2000 个托管数组。

### 2.2 微基准（ns/op，best of 5）

| 场景 | 参考实现 | ct 现状 | ct/参考实现 | ct 优化后* |
|---|---:|---:|---:|---:|
| `ByID` 整数主键查找 | 11.5 | 60.2 | **5.24×** | 21.3（1.9×） |
| int32 字段读 | 0.17 | 1.58 | **9.56×** | 0.32（1.9×） |
| float32 字段读 | 0.79 | 3.65 | 4.60× | — |
| bool 字段读 | 0.64 | 2.30 | 3.56× | — |
| 字符串解码（ct 绕开缓存） | 33.6 | 52.3 | 1.56× | — |
| 字符串重复访问 | 32.5 | **10.1** | **0.31×**（ct 快 3.2×） | — |
| 字符串冷扫（6685 个不同串） | 38.7 | 246.7 | **6.37×** | — |
| `vector<int32>` 构造+求和（12 元素） | 3.23 | 18.07 | 5.59× | 9.53（3.0×） |
| 全表按下标顺序扫描 | 7.58 | 8.80 | 1.16× | — |
| `ByID` + 3 字段读（端到端） | 21.2 | 71.0 | 3.35× | — |

\* 「优化后」= 仅把**已实测的两处实现问题**换掉后的实测值，见 §3.1 / §3.2。

### 2.3 结构性差异（为什么会有这些差距）

| | 参考实现 | ct |
|---|---|---|
| 行表示 | 定长 `[StructLayout(Sequential)]` int32 槽数组（`Item` = 36 槽 = 144 B，行距恒 144） | FlatBuffers table（vtable + 可变长） |
| 字段读 | `p->field` —— **编译期常量偏移，1 次加载** | `FieldOffset(row, slot)` —— vtable 走 3 次依赖加载 + 边界分支，再加载值 |
| 表寻址 | `int tableIndex`（原生直接下标） | `Dictionary<string, ConfigTable>`（**每次调用哈希字符串**） |
| 字符串 | `ushort` 长度前缀 + UTF-8，**i18n 路径 `Config.GetI18N` 完全不缓存** | `int32` 长度前缀 + UTF-8，**全程走 `NStringCache` 驻留** |
| 非 i18n 串 | `NStringCache`，LRU 容量 **17** | `ConcurrentDictionary`，整套世代边界清空，无上限 |
| 版本守卫 | `[Conditional("LH_DEBUG")]` | `[Conditional("CONFIG_DEBUG")]`（同款设计，Release 均零成本） |
| schema 演进 | 不支持（改字段必须重导，行布局即 ABI） | 支持（vtable） |

---

## 3. 根因（全部为实测 A/B，非推断）

### 3.1 `WireReader.GetI32/GetU16` 逐字节拼装整数 —— 影响面最大

```csharp
public static int GetI32(byte* p) => p[0] | (p[1] << 8) | (p[2] << 16) | (p[3] << 24);
```

在 little-endian 的 x86-64 / ARM64 上，这是 **4 次字节加载 + 3 次移位 + 3 次或**，
而单条非对齐 32 位加载只要 1 次。该函数位于**每一次**字段读、向量长度读取的最内层
（⏱ 2026-09-12：原文此处还列了「二分比较」——当前读路径已无二分，主键走 `idHash` 哈希探测）。

实测（只改这一处，其余不变）：

| 路径 | 现状（逐字节） | 改为 `*(int*)` | 改善 |
|---|---:|---:|---:|
| 6×int32（预取偏移） | 0.81 ns/字段 | **0.32 ns/字段** | 2.5× |
| `ByID` 二分查找（⏱ 已作废：现走 `idHash` 哈希） | 50.4 ns | **21.3 ns** | 2.4× |

修复建议：`Unsafe.ReadUnaligned<int>(p)` 或 `*(int*)p`。注意 `GetF32/GetF64` 目前是
`BitConverter.Int32BitsToSingle(GetI32(p))`，它们会自动跟着一起受益；但 `GetI8/Bool`
维持单字节读即可。若担心大端平台，用 `BitConverter.IsLittleEndian` 做一次性分发。

### 3.2 ~~生成器没有接线 reader 已实现的「偏移预取」快路径~~ —— ⏱ **2026-09-12：已接线**（定宽表直接发射字面量偏移），本节保留为历史诊断

`WireReader` 里已经写好了 `BuildFieldOffsets` / `I32At` / `F32At` / `StrAt` / `IndirectAt`，
注释也写明「一次解析 vtable，之后 obj+offset 直读」。但
`ct/export/canonical_accessor.py` 生成的 accessor **一律走槽位版**：

```csharp
public int Type => WireReader.I32(_row, 8);      // 每次访问都重走 vtable
```

实测把槽位版换成预取偏移版：**1.58 → 0.81 ns/字段（1.95×）**。
同一张表所有行共享同一 vtable 布局，偏移只需按表解析一次（可缓存到 `ConfigTable` 上）。

这是**纯生成器改动，运行时零风险**，且是 ct 自身设计的既定路径 —— 属于「写了没接线」。

### 3.3 `NArray<T>` 索引器的无条件空值分支阻断 JIT 向量化

```csharp
public T this[int index] {
    get {
        if (_base == null) return default;   // ← 每个元素都判一次
        return ((T*)_base)[index];
    }
}
```

参考实现 的 `NArray<T>.this[]` 没有任何无条件分支（它的越界/版本检查都在 `LH_DEBUG` 下编译掉），
所以 `for (...) sum += basep[k]` 能被 JIT **自动向量化**；ct 的版本不能。

实测（`ArrayBench.Areas`，12 元素求和）：

| | ns/row |
|---|---:|
| 参考实现 `NArray<int>` 裸指针循环 | 3.23 |
| ct `NArray<int>` + `arr[k]` 索引器 | 18.07 |
| ct 绕开索引器、直接拿基址求和 | **9.53** |

即 **8.5 ns/row（约一半差距）来自那个空值分支**（分支本身 + 阻断向量化）。
修复方向：把空值兜底移到**构造时**（缺失字段 → `_len = 0`，循环体自然不执行），
索引器内只留 `((T*)_base)[index]`。缺失字段的语义不会变，因为长度为 0 时调用方本来就不该访问。

### 3.4 `Runtime.ByID(string tableName, ...)` 每次调用都查字符串字典

```csharp
public static IntPtr ByID(string tableName, int id) => _tables[tableName].ByID(id);   // 字符串哈希
public static int Version(string tableName) => _tables[tableName].Version;            // 再一次
```

生成代码是 `Runtime.ByID(TableName, id)`（`TableName` 为 `const string`），
且 `ItemBenchAccessor.ByID` 还要再调一次 `Runtime.Version(TableName)` —— **每次行查找 2 次字符串哈希查表**。
参考实现 用 `int tableIndex`，无此成本。

实测拆解：

| | ns/lookup |
|---|---:|
| 参考实现 `ConfigByID(idx, id)` | 11.5 |
| ct 全路径（含字典） | 60.2 |
| ct 仅去掉字典（持有 `ConfigTable` 引用） | 50.4 |

字典占 **~10 ns/次**，接近 参考实现 整个查找预算（11.5 ns）的 87%。
修复方向：生成器在 accessor 里缓存 `ConfigTable` 静态句柄（`Runtime.Table(TableName)` 只在首次解析），
字典只在加载/schema 变更时用。

### 3.5 `NStringCache` 冷路径用 `ConcurrentDictionary` —— 冷扫比 参考实现 慢 6.4×

ct 的驻留缓存在**稳态下是净胜**：10.1 vs 32.5 ns（ct 快 3.2×），
因为 参考实现 的 i18n 路径（`Config.GetI18N`）**每次访问都重新 UTF-8 解码，完全没有缓存**。

但**冷启动/一次性全扫**下 ct 反而慢 6.4×（246.7 vs 38.7 ns/row）：
每个不同串都要走 `ConcurrentDictionary.TryGetValue` + `GetOrAdd`（含锁/桶分配），
而 参考实现 只是 `Encoding.UTF8.GetString`。

修复方向：
- 加载后的首次批量访问是**单线程**的，把 `ConcurrentDictionary` 换成 `Dictionary`
  （或 `TryAdd` 快速路径）即可拿到大部分收益；
- 或对「只读一遍」的调用点提供绕过缓存的入口（`WireReader.StrAt` 已经是绕过版，实测 52.3 ns）。

### 3.6 稳态字符串访问是 ct 的真实优势

| | ns/read |
|---|---:|
| 参考实现 i18n 串（无缓存，每次解码） | 32.5 |
| ct `NString`（驻留命中） | **10.1** |

游戏里同一配置串被反复读取（UI 每帧刷新、技能描述、道具名）是常态，
ct 在这一维度**结构性领先 3.2×**，且这是 参考实现 的 `NStringCache`(LRU-17) 覆盖不到 i18n 路径造成的
—— 17 个槽位对 6685 个道具名而言等于没有缓存。

---

## 4. 结论

1. **加载阶段不用改**：解析与原生持平（1.01×），端到端 1.39×，可通过合并「读盘 + bundle 解析」
   再拿回大部分差距。
2. **热路径当前慢 3.5×–9.6×，但 ~80% 是两处实现细节**（§3.1 逐字节整数拼装、§3.2 生成器未接线偏移预取）。
   ⏱ **2026-09-12：本条已作废** —— §3.2 的偏移预取已接线，且 OPT-7 主键哈希 / OPT-8 字符串缓存落地后，
   端到端行访问已反超 参考实现；见 `OPTIMIZATION-STRATEGY.md` 附录 C/D。
   实测把这两处换掉后，字段读与查找的差距收敛到 **~1.9×**。
3. **剩下的 ~1.9× 是 FlatBuffers vtable 的固有代价**（每字段 2–3 次额外依赖加载），
   换来的是 参考实现 完全没有的 schema 演进能力（参考实现 行布局即 ABI，加字段必须全量重导）。
   这个取舍本身是合理的，需要的是把它的成本压到设计下限。
4. **两个维度 ct 已经/可以结构性领先**：稳态字符串访问（3.2×，靠驻留缓存）、体积（160 vs 222 B/row）。
5. **优先级建议**：
   | 优先级 | 动作 | 预期 |
   |---|---|---|
   | P0 | `GetI32/GetU16` 改单条非对齐加载 | 字段读 2.5×、查找 2.4× |
   | P0 | 生成器接线 `BuildFieldOffsets` 偏移预取 | 字段读 1.95× |
   | P1 | `NArray` 空值兜底移到构造期 | 向量循环 ~1.9× |
   | P1 | accessor 缓存 `ConfigTable` 句柄 | 查找 ~1.2× |
   | P2 | 字符串缓存改 `Dictionary` + 世代失效 / 提供免缓存入口 | 冷扫 可达 ~6× |

---

## 5. 本次改动文件

| 文件 | 说明 |
|---|---|
| `RefConfigBench.csproj` | 基准工程（net10.0，链接 `ConfigAccessorBench` 的 reader 运行时） |
| `RefNative.cs` | 参考实现 原生 API 的 P/Invoke 声明 + `RefConfig` 托管镜像 |
| `RefRows.cs` | 逐字复刻 `Runtime/Generate/Item.cs` 的 `_Data` 行布局 |
| `Bench.cs` | 微基准（含 4 个 ct-only 根因诊断场景） |
| `LoadBench.cs` | 加载耗时对标 |
| `Program.cs` | `probe` / `dump` / `dump-tables` / `bench` / `load` 模式 |
| `gen_ct_bench_tables.py` | 生成 ct 侧基准表 `.bin` + 真实生成器产出的 `.g.cs` |
| `gen_scale_corpus.py` | 生成同规模 ct bundle（2000 表 / 692k 行 / 105.8 MB） |
| `pick_tables.py` | 扫描 参考实现 生成代码挑选基准表 |
| `ref_tables.json` / `ref_table_shapes.json` | 参考实现 表清单与形状统计 |
| `PERF-REPORT.md` | 本报告 |

## 6. 局限（读结论前请一并考虑）

- ct 侧数据是**按行数与字段形状对齐的合成数据**，不是与 参考实现 逐值相同的同一份逻辑数据。
  逐操作成本可对齐，但缓存/分支预测行为不会完全一致。
- 参考实现 侧以 `SetUseDecryptProcess(false)` 明文加载、`lang = 0`（走 `GetI18N` 的 ZH 内联分支），
  未覆盖解密路径与切语言的 `GetI18N(hash, id)` 原生查表分支。
- 测量环境为 **CoreCLR / .NET 10 x64**；Unity 客户端是 IL2CPP + Boehm GC，
  绝对数值不可直接搬运，但两侧差距的方向与成因（依赖加载链、分支、向量化）是一致的。
- 参考实现 侧 `ConfigByID` 每次调用含一次 P/Invoke 边界（~数 ns，已计入其 11.5 ns 内）；
  这正是它在 Unity 里的真实形态。
