# ConfigAccessorBench — 独立 reader runtime + accessor 接口/性能基准

仓库内**独立于游戏/Unity** 运行的 .NET 工程：实现并验证“为 ct 导出物设计的指针式 reader runtime”（对齐 harmony 读取模型），并基准对比 accessor 读取方式。它只依赖 `gd/output/binary/data_zh.bin` 与 .NET 8，可在本工程直接 `dotnet run`。

> 本工程是 reader 运行时的**首版落点**（按 change `align-config-accessor-api`），后续 ct 生成器按此契约输出、游戏工程再集成。

## 文件

| 文件 | 职责 |
|---|---|
| `WireReader.cs` | 指针式 FlatBuffers 读取核心（`FieldOffset/Indirect/I8/I32/.../Str/ArrLen/ArrI32/...`）、`VectorBase/Count/RowAt/IndexSearch`、`VecBase/VecLen`、`DataBundle` 解析 |
| `Runtime.cs` | `IConfigStruct` / `NArray<T>`（标量向量，一次 Indirect 拿基址+长度，`[i]` 直读）/ `NStructArray<T>`（结构体向量）/ `NString` + `NStringCache`（驻留）/ `TableVersion`（版本守卫，`CONFIG_DEBUG` 条件编译） |
| `ConfigReader.cs` | 引导层：`GCHandle` 钉住表缓冲，暴露 `Count/ByID/ByIndex/RowAt` + 版本 |
| `Program.cs` | standalone 演示（正确性 + 性能 + 驻留 + 版本守卫） |

## 运行

```powershell
# 从真实 bundle 读取 Item
dotnet run -c Release -- Item 200000

# 直接读单表 .bin（根为 ItemTable）
dotnet run -c Release -- item_large.bin 1000
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
1. **性能对齐 harmony 靠“构造时一次捕获向量基址（`VecBase`）+ `[i]` 直读”**，向量越长收益越大。
2. **版本守卫/越界必须 `[Conditional("CONFIG_DEBUG")]`**（harmony `LH_DEBUG` 同款）：否则每次访问的开销会吃掉基址捕获收益——这正是本工程先发现、写进 `design.md` 的点。
3. 读端契约由我们定义（指针式 `(IntPtr row, int slot)`，行句柄持 `IntPtr`），独立可运行；游戏后续集成。

## 再生成大表测试数据

见 change `align-config-accessor-api` 的 `tasks.md` 6.2，或直接：
```powershell
cd ct; .venv\Scripts\python -c "from ct.app.canonical_workspace import CanonicalWorkspace; from ct.export.canonical_binary import build_canonical_table_bytes; ws=CanonicalWorkspace.load(Path('../gd')); rec={r.name:r for r in ws.records}; en={e.name:e for e in ws.enums}; item=next(t for t in ws.tables if t.table=='Item'); rows=[{'Id':i,'Name':f'item{i}','Price':float(i),'Rarity':'common','ItemTypeId':(i%3)+1,'DropRange':{'Min':i,'Max':i+5},'Tags':list(range(i,i+50)),'IsActive':True} for i in range(1,2001)]; Path('../test-proj/ConfigAccessorBench/item_large.bin').write_bytes(build_canonical_table_bytes(rows,item,records=rec,enums=en))"
```
