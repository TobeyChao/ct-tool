## Context

参见 proposal.md — Why。生成的 C#/Lua accessor（`ct/src/ct/export/canonical_accessor.py`）读取 ct 导出的 FlatBuffers 二进制，但接口与性能都未对齐 harmony 配置读取器。核心差异是：harmony 用**编译期已知偏移的顺序 `_Data` 结构体**（`p->x` 一次解引用）与**持基址的容器**（`NArray<T>` 直读 `p[i]`），而我们每次读字段/元素都要**重走 FlatBuffers vtable/offset**。

`fabulous-game` 的 `WireReader` 仅作**参考**，不成为约束。**reader 运行时由我们自己设计**（指针式 FlatBuffers 读取 + 容器 + 查询），并且**整套工具 + reader + 基准独立于游戏可运行**；游戏工程后续消费时再集成该 reader（或其导出的 accessor）。已用仓库内可复现基准 `test-proj/ConfigAccessorBench` 实测（读到 `gd/output/binary/data_zh.bin`）：

| 维度 | before | after-a（容器外观，仍重解析） | after-b（捕获基址直读） | harmony |
|---|---|---|---|---|
| vector\<int\> 大表(2000×50) | 422 ms | 696 ms | 99 ms | 直读 |
| 标量 int32 (200k 行读) | 2.2 ms | — | 1.9 ms（偏移缓存） | `p->x` |

结论：**巨大的性能杠杆是“向量基址捕获”**（≈4.3×）；**标量/枚举字段偏移缓存可忽略**。

## Goals / Non-Goals

**Goals**
- 让生成的 accessor **接口形状对齐 harmony**：每表 `Count/ByID/ByIndex`、向量为单一可索引/可枚举容器、enum 类型化、跨表 ref 类型化。
- 让向量读取**性能对齐 harmony**：构造容器时一次捕获基址，`[i]` 直读。
- 建立**独立运行**的 reader 运行时与可复现基准（`test-proj/ConfigAccessorBench`）验证收益。

**Non-Goals**
- 不做 `NValue`/`NValueObject` 动态对象（需要 schema+Excel+FBS+binary 四层扩展）。
- 不做 i18n 单表多语言列重构（属另一架构决策）。
- 不做标量字段偏移缓存（实测收益≈10%，被 L1 抵消）。

## Decisions

### D1：性能靠“向量基址捕获（VecBase）”，不靠“容器外观”
B-2a（只包 `NArray` 外观，`[i]` 仍重复解析）实测反而更慢（1.33–1.65×），因为它每元素仍重走 vtable/offset 还多一层索引器。B-2b（构造时一次 `VecBase` 拿基址，`[i]` 直读）实测大表 ≈4.3× 快。
- 备选：只改接口不改 reader → 无性能收益，**弃用**。

### D2：向量暴露为单一容器 `NArray<T>` / `NStructArray<T>`
harmony 的向量是“一个可索引/可枚举的值”（`row.Tags[i]`、`foreach`），我们目前是 `Count + At(i)` 两个访问点。改为单容器，接口与 harmony 一致。`NArray<T>` 持 `(base, len)`：构造 `new NArray<int>(WireReader.VecBase(_row, slot), len)`。
- 备选：保留 `Count+At` → 接口不一致，**弃用**。

### D3：每表补齐查询 API `Count/ByID/ByIndex/ByGroupKey`
harmony 的每个 `IConfigType` 都有 `Count/ByIndex/ByID/ByGroupKey`，统一走 `Config` 中央调度。我们 C# 侧缺失，需补齐；Lua 已有 `ByID`，补其余。
- 这些由 reader 的引导层（load bundle → 取表 → `VectorBase`/`Count`/`RowAt`）提供，生成器只负责按表调用。

### D4：跨表 ref —— 保留裸 id 快路径 + 类型化访问，避免每字段 P/Invoke
harmony 的 `{RefType}.ByID(id)` 每次都是一次原生 P/Invoke（`ConfigByID`），边界调用很贵；直接照搬会变慢。因此：
- 保留裸 id 快路径 `public int ItemTypeId => WireReader.I32(_row, slot)`。
- 增加类型化访问 `public ItemTypeRow ItemType => ...`，其底层用一次建立的 id→行缓存，避免每字段 P/Invoke。
- 备选：每字段直接 `ByID` → 性能回退，**弃用**。

### D5：enum 返回类型化值；字符串驻留
- enum：`public ItemRarity Rarity => (ItemRarity)WireReader.I8(_row, slot)`。
- string：读端提供 `NStringCache` 等价物驻留，避免每次 `Encoding.UTF8.GetString` 分配。

### D6：不做标量字段偏移缓存
实测标量/enum 在“每次 vtable 解析”与“缓存偏移表”间 ratio 0.89–1.06，基本持平（vtable 是同一张热表，L1 命中）。因此不为标量做 offset 缓存，避免无谓复杂度。

### D7：reader 是独立运行的指针式运行时，生成的行句柄持 `IntPtr`
读取契约由我们定义（不照搬游戏现有 `WireReader` 的 API）：生成的 `{Table}Row` 持有**行对象指针 `IntPtr _row`**，字段读取用指针式 reader `WireReader.I32(_row, slot)`（`slot = 4 + 2*字段序`），vector 用 `new NArray<int>(WireReader.VecBase(_row, slot), len)`。这比早期 `(TableName, slot, row)` 契约更快（后者每次字段访问还要做一次表名→缓冲查找）。reader 是纯 C# + unsafe 读 FlatBuffers，不依赖 Unity/游戏，可在 `test-proj/ConfigAccessorBench` 独立运行验证；游戏后续集成 reader 或其生成的 accessor。
- 选型：指针式 `(IntPtr row, int slot)`（对齐 harmony/参考，最快）——**采用**；`(tableName, slot, row)`（P1#2 曾用，含表名查找）——**弃用**。
- 行句柄来源：`{Table}Accessor.ByID/ByIndex` 经 reader 的引导层（load bundle → 取表 → `VectorBase`/`Count`/`RowAt`）解析。

### D8：版本守卫/越界检查必须条件编译（`CONFIG_DEBUG`）
实测（`test-proj/ConfigAccessorBench`）：若每次访问都做 `TableVersion.Check` + 越界检查（非条件编译），小表上 `after` 反而比 `before` 慢（ratio 约 1.3–2.0）；把守卫/越界编译成 `[Conditional("CONFIG_DEBUG")]`（harmony `LH_DEBUG` 同款）后，Release 下开销为 0，大表 `after/before ≈ 0.139`（≈7.2× 快）。
- 结论：reader 热路径的守卫/越界**只应在 Debug 生效**，Release 必须编译掉，否则会吃掉基址捕获的收益。

## Risks / Trade-offs

- [读端契约以我们为准] 读取器/accessor 契约由我们定义（D7 指针式），不与游戏现有 `WireReader` 绑定；游戏消费时可集成我们产出的 reader 或生成的 accessor（可能需按游戏环境微调 unsafe/平台）。
- [字符串驻留线程/生命周期] `NStringCache` 需与表版本/切语言联动，防止缓存错版本 → 需版本守卫。
- [ref 缓存失效] id→行缓存需表重载失效（热重载/切语言）→ 用 epoch/版本守卫。
- [生成端与读端须同步] reader 新增 `VecBase`/查询/容器，生成器按其输出；若不升级 reader，生成的 accessor 无法编译/加速。

## Migration Plan

生成端（ct-tool）先改：新增 reader 运行时（`VecBase`/查询/容器）→ 模型加 `ref`/容器类型 → 生成器输出指针式新形状 → golden 测试更新。`test-proj/ConfigAccessorBench` 作为 reader 的独立验证/基准。产物 `gd/output/generated/**` 重生成。无数据迁移（二进制格式不变）。

## Open Questions

- **（已决）读端契约由我们定义**（D7：指针式 `(IntPtr row, int slot)`，行句柄持 `IntPtr`；reader 独立可运行）。
- **（已决）字符串驻留本期必做**：读端提供 `NStringCache` 等价物（对齐 harmony），不牵动 schema/export；随表版本/语言切换失效。
- 读端 reader 运行时在仓库中的落位：是作为独立项目（如 `ct-reader/` 或并入 `test-proj/`），还是作为 ct-tool 一份“运行时契约 + 基准工程”交付？
