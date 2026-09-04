# ConfigAccessorBench — bytes 读取/加载中间件安全审查报告

> 审查对象：`test-proj/ConfigAccessorBench/` 的 reader 运行时（`WireReader.cs` / `Runtime.cs` / `ConfigReader.cs` / `Program.cs`）及生成的 `*.g.cs` accessor。
> 方法：静态分析 + `CONFIG_DEBUG` 实证运行。审查时间基于 commit `40ae09e`。

## 摘要

中间件的性能设计思路（`VecBase` 一次捕获向量基址 + 容器 `[i]` 直读）正确，基准成立（合成大表约 6× 提速）。但**内存安全与生命周期管理存在 3 个 P0 级问题**，且共同根因是：**版本守卫 + 越界检查整体被 `CONFIG_DEBUG` 条件编译掉，Release 构建里这套中间件没有任何内存安全兜底**。

---

## 🔴 P0 —— 高危（实锤 / UAF / 数据错乱）

### 1. 全局版本计数，多表加载必然误判 stale（已实证崩溃）

- 位置：`Runtime.cs:15-17`（`TableVersion._version` 全局单计数）；`ConfigReader.cs:27`（每次 `new ConfigTable` 都 `Bump()`）
- 问题：版本是**全局单一计数器**。真实多表场景（先拿 A 表句柄，再加载 B/C/D 表）下，A 未重载但全局版本已前进，`Check()` 把 A 误判为 stale。
- 实证（`-p:DefineConstants=CONFIG_DEBUG` 运行 `Item`）：

  ```
  [Config] stale reader (version 1 != 4), table was reloaded or language switched
      at NArray`1.get_Item ... Runtime.cs:56
      at Program.RunCorrectness ... Program.cs:90
  ```

  Demo 在 Debug 守卫下连自身正确性路径都跑不过；Release 只是把检查编译掉了才"看起来正常"。
- 修复方向：版本语义改为 **per-table**（重载该表才 bump）或 **per-bundle-epoch**。

### 2. NStringCache 在 Release 永不清除 + 按地址缓存 → 返回陈旧字符串

- 位置：`Runtime.cs:125-145`；`NStringCache.OnVersion` 被 `[Conditional("CONFIG_DEBUG")]` 编译掉（`Runtime.cs:128-132`）
- 问题：缓存 key 是字符串**指针地址** `(nint)ptr`；清缓存逻辑在 Release 下是空操作。表重载/切语言后，GC 很可能把新 buffer 分配到与旧 buffer 相同地址（同尺寸数组地址复用常见）→ 命中旧地址缓存 → **返回旧语言的旧字符串**，无任何异常。
- 根因：设计文档明确"守卫必须 Conditional 否则吃掉性能"，但后果是选性能后 Release 连**数据正确性**都丢了。
- 修复方向：缓存键带版本/纪元（`(pVersion, addr)`），或驻留表随表版本变化整体重建。

### 3. `Dispose()` 不 bump 版本 → 悬空指针完全无守卫（UAF）

- 位置：`ConfigReader.cs:45-48`
- 问题：`Dispose()` 只 `_pin.Free()` 解除钉住，**不递增任何版本**。钉住解除后 GC 可搬移/回收该 `byte[]`，此前捕获的行/字段/向量指针全部悬空，版本守卫（即使 Debug）也不会触发（版本没变）→ Release 下静默 UAF。
- 修复方向：`Dispose()` 内提升版本/纪元；生命周期由中间件统一管理，禁止外部随意 `Free`。

### 4. 越界读在 Release 下无任何检查（野指针读取）

- `WireReader.RowAt`（`WireReader.cs:45-49`）：`itemsBase + idx*4` 直接解引用，**无 idx 范围校验**；`ByIndex(i)` 对 `i >= Count` 越界 → 读到 pin 缓冲边界外或相邻字段。
- `NArray<T>.this[index]`（`Runtime.cs:51-61`）越界检查被 `#if CONFIG_DEBUG` 包住，**Release 下 `arr[i]` 越界 = 野指针直读**。
- 缺省 vector 的 `NArray` 其 `_base == null`，直接 `arr[0]` → 解引用 null（Release 下 NRE）。
- 修复方向：索引/边界校验至少保留一条无条件路径（或 Debug Assert + Release 防错数据的最小开销方案）。

> 与 #2 同根：**整个安全体系（版本守卫 + 越界）在 Release 构建里全部消失**，只剩性能。

---

## 🟠 P1 —— 内存泄漏 / 资源泄漏

### 5. `Runtime.Register` 重载泄漏 GCHandle

- 位置：`Runtime.cs:155`（`_tables[table.Name] = table` 直接覆盖）
- 问题：旧 `ConfigTable` 的**钉住句柄不释放**。切语言/热更重载表 = 每表泄漏一个 pinned 句柄，旧 buffer 被钉住无法回收。
- 修复方向：`Register` 覆盖前 `Dispose` 旧表；提供 `Unregister` 幂等入口。

### 6. Demo 自身的 `.bin` 路径泄漏

- 位置：`Program.cs:26-29` 与 `Program.cs:42`
- 问题：`item_large.bin` 路径新建的 `ConfigTable` 不在 `all` 列表，最后 `foreach (var t in all) t.Dispose()` 不含它 → 该表 GCHandle 从不释放。该"加载即持有、不统一登记"模式会传导到真实集成代码。
- 修复方向：统一注册表生命周期（`Runtime` 登记即可由 `Runtime.Clear/DisposeAll` 统一释放）。

### 7. NStringCache 无上限常驻

- 位置：`Runtime.cs:125`
- 问题：每个读过字符串的地址永久驻留（仅 Debug 版本变化清一次），长会话只增不减，弱泄漏/内存驻留。

---

## 🟡 P2 —— 健壮性 / 防御性缺口

| # | 位置 | 问题 |
|---|---|---|
| 8 | `WireReader.cs:20-26` | `FieldOffset` 对 slot 0–3（vtable 元数据区）无防护，传错 slot 读垃圾偏移 |
| 9 | `WireReader.cs` 全文 | 无 buffer 长度/边界校验，`vtLen`/`GetI32` 直接解引用；损坏 bundle → 任意地址读（信任数据假设，需文档化） |
| 10 | `Runtime.cs:59` | `NArray<T>` `((T*)_base)[index]` 非对齐直读；对 `T` 对齐要求 >4（`vector<double>`、8 对齐 struct）依赖 FlatBuffers 保证对齐，容器自身不验证，错位 SIGBUS |
| 11 | accessor ref 字段 | 未注册表时 `Runtime._tables[tableName]` 抛 `KeyNotFoundException`；跨表 ref 无优雅降级 |
| 12 | `ConfigReader.cs:22-31` | `Alloc` 之后、字段赋值完成前抛异常 → GCHandle 不释放 |
| 13 | `Runtime.cs` 全文 | `TableVersion` / `NStringCache` / `Runtime` 静态状态全部无锁，多线程加载+读取有竞态 |

---

## 设计耦合（脆弱性，非 bug）

- `VectorBase` / `Count` / `IndexSearch`（`WireReader.cs:36-77`）硬编码 root table 的 **slot 4（items）/ slot 6（index）** 布局，与 ct 导出器强耦合 —— root 表结构一旦加字段即静默错读或崩溃。建议生成器把槽位作为参数/常量注入，而非 reader 内写死。

---

## 修复优先级建议

| 优先级 | 问题 | 影响 |
|---|---|---|
| **P0** | 全局版本计数误判（#1）+ Release 全无守卫（#2/#4） | 多表场景 Debug 直接崩、Release 静默错数据 |
| **P0** | NStringCache Release 地址复用返回陈旧字符串（#2） | 切语言/热更后读到旧数据 |
| **P0** | Dispose 不 bump 版本（#3） | 悬空指针无守卫 UAF |
| **P1** | Runtime 重载泄漏 GCHandle（#5）+ Demo .bin 路径泄漏（#6） | 热更/重载内存只增不减 |

**核心教训**：性能优化可以，但正确性路径（至少 NStringCache 驻留、索引/版本语义）**不应是条件编译**的产物。
