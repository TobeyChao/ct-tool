# ConfigAccessorBench — 独立 reader runtime + accessor 接口/性能基准

仓库内**独立于游戏/Unity** 运行的 .NET 10 工程：实现并验证“为 ct 导出物设计的指针式 reader runtime”（对齐 参考实现 读取模型），并基准对比 accessor 读取方式。它只依赖 `gd/output/binary/data_zh.bin`，可在本工程直接 `dotnet run`。

> 本工程是 reader 运行时的**首版落点**（按 change `align-config-accessor-api`），后续 ct 生成器按此契约输出、游戏工程再集成。

---

## ⛔ 时效：本工程是**冻结的历史原型**（2026-09-12 追加）

本工程（含 `WireReader.cs` / `Runtime.cs` / `ConfigReader.cs` 与 `*.g.cs`）是 **2026-08 的首版落点**，
**此后未再随 ct 契约演进**：它的 `*.g.cs` 仍用 `ItemRow` 命名，reader 里仍留着 `IndexSearch`（二分兜底）
与 `[Conditional("CONFIG_DEBUG")]` 守卫。**请勿把本工程当作当前契约**，也不要据此改 ct 生成器 —— 它是快照，不是合同。

### 当前契约（与本文不同）

| 本工程（历史原型） | 当前契约 |
|---|---|
| `WireReader.IndexSearch`：主键查询走**二分查找**（stride 8 的 `(key, row)` 有序数组），**没有任何哈希路径** | **查找全部走哈希，读路径无二分、无兜底**：容器 slot 1 `index` 是 `(key,row)` 有序对（仍是行的来源），slot 2 `idHash` 是主键哈希桶（存 `index` 位置 + 1，`0` = 空），slot 3 是 `codeNameIndex`。缺 `idHash` 在建表期（C#）/首次查询（Lua、原生）**硬报错**。`IndexSearch` / `lower_bound` / `upper_bound` / `gd_index_bsearch` 在代码中**已不存在** |
| 守卫用 `[Conditional("CONFIG_DEBUG")]`（或常驻调用 + 发布期空实现） | 守卫必须是**源码级** `#if CONFIG_DEBUG \|\| UNITY_EDITOR \|\| DEVELOPMENT_BUILD` 包裹。`[Conditional(...)]` 与「常驻空实现」都被项目契约测试明确拒绝 —— 后者实测有热路径回归（float32 字段读 **+12.7%**、定宽 `.Id` +9.8%），发布包必须与「没有守卫」逐字节一致 |
| `*.g.cs` 用 `ItemRow` 等 `*Row` 后缀类型名 | C# 产物包在固定命名空间 `GameFramework.ConfigGen`，行类型**以表名本身命名**（`Item`，**无 `Row` 后缀**） |
| `Runtime.ByCode` / `GroupKey` | 只有 `ByCodeName(codeName)`（且**仅当该表声明了 codename 索引**时生成）；**`ByCode` 不存在**；**Group 查询索引已整体删除**（容器 slot 4/5 空出） |
| 偏移预取：无 | 填充率 ≥ 0.75 的定宽（uniform）表由生成器直接发射**字面量偏移**（`ROW_MODE_LITERAL`） |
| `output/generated/csharp/` 无枚举声明 | **`Enums.cs` / `Enums.lua` 会产出**具名枚举声明 |

> 现役参考实现与实测在 `test-proj/RefConfigBench/`；当前契约的权威描述见 `openspec/specs/flatbuffers-export/spec.md` 与 `ct/docs/README.md`。

## 文件

| 文件 | 职责 |
|---|---|
| `WireReader.cs` | 指针式 FlatBuffers 读取核心（`FieldOffset/Indirect/I8/I32/.../Str/ArrLen/ArrI32/...`）、`VectorBase/Count/RowAt`、**`IndexSearch`（⚠️ 历史二分兜底，当前契约已无，见上「当前契约」）**、`VecBase/VecLen`、`DataBundle` 解析 |
| `Runtime.cs` | `IConfigStruct` / `NArray<T>`（标量向量，一次 Indirect 拿基址+长度，`[i]` 直读）/ `NStructArray<T>`（结构体向量）/ `NString` + `NStringCache`（驻留）/ `TableVersion`（版本守卫，**⚠️ 本工程用的是 `CONFIG_DEBUG` 条件编译；当前契约是源码级 `#if CONFIG_DEBUG \|\| UNITY_EDITOR \|\| DEVELOPMENT_BUILD`**） |
| `ConfigReader.cs` | 引导层：`GCHandle` 钉住表缓冲，暴露 `Count/ByID/ByIndex/RowAt` + 版本 |
| `Program.cs` | standalone 演示（正确性 + 性能 + 驻留 + 版本守卫） |

## 运行

```powershell
# 从真实 bundle 读取 Item
dotnet run -c Release -- Item 200000

# 直接读单表 .bin（根为 ItemTable）
dotnet run -c Release -- item_large.bin 1000

# 读取固定 Excel 列 vector fixture，并断言 int32/string vector
dotnet run -c Release -- --fixed-vector
```

## 实测（本机，Release）

**真实 Item（4 行，Tags 1–3，200k 轮）**：before 14.1ms / after 17.7ms（小数据差异小）。

**合成大表（2000 行，Tags 长度 50，1000 轮）**：
```
before  (Count+At, 每元素重复解析基址) : 436.8 ms
after   (NArray 捕获基址直读)          :  60.6 ms
ratio  after/before = 0.139  (≈7.2× 更快)
```

**关键结论**：
1. **性能对齐 参考实现 靠“构造时一次捕获向量基址（`VecBase`）+ `[i]` 直读”**，向量越长收益越大。
2. **版本守卫/越界必须 `[Conditional("CONFIG_DEBUG")]`**（参考实现 `LH_DEBUG` 同款）：否则每次访问的开销会吃掉基址捕获收益——这正是本工程先发现、写进 `design.md` 的点。
   ⚠️ **2026-09-12 勘误**：这条**只对本工程的历史原型成立，不再是当前契约** —— 当前实现要求守卫是**源码级** `#if CONFIG_DEBUG || UNITY_EDITOR || DEVELOPMENT_BUILD` 包裹；`[Conditional("CONFIG_DEBUG")]`（以及「常驻调用 + 发布期空实现」）已被项目契约测试明确拒绝，后者实测有热路径回归（float32 字段读 **+12.7%**）。
3. 读端契约由我们定义（指针式 `(IntPtr row, int slot)`，行句柄持 `IntPtr`），独立可运行；游戏后续集成。

## 再生成大表测试数据

见 change `align-config-accessor-api` 的 `tasks.md` 6.2，或直接：
```powershell
cd ct; .venv\Scripts\python -c "from ct.app.canonical_workspace import CanonicalWorkspace; from ct.export.canonical_binary import build_canonical_table_bytes; ws=CanonicalWorkspace.load(Path('../gd')); rec={r.name:r for r in ws.records}; en={e.name:e for e in ws.enums}; item=next(t for t in ws.tables if t.table=='Item'); rows=[{'Id':i,'Name':f'item{i}','Price':float(i),'Rarity':'common','ItemTypeId':(i%3)+1,'DropRange':{'Min':i,'Max':i+5},'Tags':list(range(i,i+50)),'IsActive':True} for i in range(1,2001)]; Path('../test-proj/ConfigAccessorBench/item_large.bin').write_bytes(build_canonical_table_bytes(rows,item,records=rec,enums=en))"
```
