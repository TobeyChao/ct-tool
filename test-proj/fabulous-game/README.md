# 为 fabulous-game 造的语料 / 验证脚手架（ct-tool 侧）

> 2026-09-12 建。这些脚本**从 fabulous-game 仓搬过来** —— 它们全都 `import ct.*`（要用导出器造语料），
> 属于**工具侧的活儿**，放在这里之后 fabulous-game 不再需要 sibling checkout 才能构建/跑基准。

## 方向：tool 产出 → 工程消费（单向）

```
ct-tool（本目录）                       fabulous-game
  造语料 / 生成访问器  ────写入────▶  Docs/TODO/scripts/deployed-perf-bench/{fixtures,*.g.cs}
                                      Docs/TODO/scripts/lua-bench/（写到 /tmp，不入库）
```

⇒ fabulous-game 仓**只消费**已生成好的 fixture / `.g.cs`，**不引用 ct-tool**。
要重新生成时回到这里跑，并显式告诉它工程目录在哪。

## 脚本

| 脚本 | 干什么 | 输出 |
|---|---|---|
| `gen_fixtures.py` | 造 `OurItem`（定宽=部署形态，内联 i18n）/ `OurItemOT`（常规对照）+ 对应 C# 访问器 | `$GAME_BENCH_DIR/{fixtures,*.g.cs}` |
| `gen_bench_fixtures.py` | 造 `ItemBench` / `ArrayBench`（与 参考实现 对标同形状同语料）+ 访问器。**自带语料自检**：非定宽产物必须与 `RefConfigBench/fixtures/*.bin` 逐字节一致 | 同上 |
| `gen-big-table-fixture.py` | 造放大语料（6685 / 15000 / 120000 行）给 Lua 侧基准 | `/tmp/weak/` |
| `gen-two-accessor-variants.py` | 生成「槽位 vs 定宽字面量」两版 Lua 访问器，供 A/B | `/tmp/weak/lib{A,B}/` |
| `uniform-check/*.py` | 验证导出器 uniform（定宽）实现真的产出**单一 vtable**、枚举槽位正确 | 临时目录 |
| `migrate_excel.py` | 一次性：把旧版 Excel 模板升级到当前格式（保留数据） | 就地改 Excel（已用完，留档） |

## 怎么跑

```bash
CT=/path/to/ct-tool

# 重新生成 game 侧基准的 fixture + 访问器（注意 GAME_BENCH_DIR 是**工程**目录）
GAME_BENCH_DIR=/path/to/fabulous-game/Docs/TODO/scripts/deployed-perf-bench \
  $CT/ct/.venv/bin/python gen_fixtures.py

GAME_BENCH_DIR=/path/to/fabulous-game/Docs/TODO/scripts/deployed-perf-bench \
  $CT/ct/.venv/bin/python gen_bench_fixtures.py

# 纯导出器验证（不需要 fabulous-game）
$CT/ct/.venv/bin/python uniform-check/real_uniform_check.py
```

⚠️ `gen_fixtures.py` / `gen_bench_fixtures.py` **必须**给 `GAME_BENCH_DIR`；
不给会直接报错退出（不再有硬编码的兄弟目录猜路径）。

## 为什么不再放 fabulous-game

原先它们住在 `fabulous-game/Docs/TODO/scripts/`，于是：
- `sys.path.insert(0, "<绝对路径>/ct-tool/...")` —— 换台机器、换个目录就断；
- `deployed-perf-bench.csproj` 还**跨工程编译** ct-tool 的两个源文件。

把一个仓库的构建依赖挂到另一个仓库的**未提交文件**上是脆的。现在方向单一：
**tool 产出、工程消费**，两边各自自包含。
