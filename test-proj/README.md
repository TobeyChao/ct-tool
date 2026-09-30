# 独立读取验收与历史实验

当前正式入口在仓库根目录执行，仅需要 Rust、Node 22+ 和 .NET 10：

```sh
cargo build --manifest-path native/Cargo.toml -p ct-cli --release --locked
cargo build --manifest-path native/Cargo.toml -p ct-xtask --locked
node test-proj/check-retirement.mjs
node test-proj/ExportAccessorVerify/prepare-native.mjs
```

准备脚本只写系统临时目录。原生内核导出小工作区，并再生 Scalars Binary/C#；独立 C# 读取器验证 127 项，包括定宽/变长表、CodeName、九个 FNV 向量、稀疏翻译与语言切换、十二种标量及 64 位边界。输入、旧标量期望和来源脚本由 `native/fixtures/accessor_verify/independent-oracles.json` 固定摘要，先校验再生成，参照不会由被测代码覆盖。缺参照、少检查或字段不一致都返回非零。`CT_NATIVE_BIN`、`CT_XTASK_BIN`、`DOTNET_BIN` 可覆盖可执行文件位置。

`ConfigAccessorBench/WireReader.cs`、`Runtime.cs`、`ConfigReader.cs` 是现役独立读取依赖；其历史 standalone 演示、旧 `*.g.cs`、性能报告和大表生成命令不代表当前契约。

[`python-retirement.json`](python-retirement.json) 逐项记录 19 个旧脚本：`prepare.py`、`gen_scalars_bench.py` 两条正式准备入口已替代，其余 17 条为非活跃历史实验。`check-retirement.mjs` 检查路径全集、来源摘要、分类理由和现役能力位置；新增脚本或改写历史来源需重新审计。

`RefConfigBench/`、`UniformE2EBench/` 和 `fabulous-game/` 保留过去的 C++/Lua/Unity 对标材料、特定语料和一次性迁移说明。它们不进入当前构建、测试、夹具再生或发行链，也不作为 G1/G2/G3 通过证据。旧规模、随机分布及外部游戏结果不能与新 S/M/L 或 r/r-full 留档混用；登记中的 successor 仅指现役相关能力。当前性能入口见 [`native/README.md`](../native/README.md)。历史命令不再受支持，本轮保留文件，不批量清理实验资料。
