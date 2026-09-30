# 原生导出与独立 C# 读取端验收

在仓库根目录先构建发布版 `ct`，再运行：

```sh
cargo build --manifest-path native/Cargo.toml -p ct-cli --release
cargo build --manifest-path native/Cargo.toml -p ct-xtask --locked
node test-proj/check-retirement.mjs
node test-proj/ExportAccessorVerify/prepare-native.mjs
```

脚本复制 `native/fixtures/accessor_verify/workspace` 到临时目录，由原生 `ct export --all` 生成 Binary、JSON 与 C# Accessor，再临时编译本项目的 `Program.cs` 和独立读取器。它逐行逐字段对照导出 JSON，并验证 CodeName、语言切换和标量边界；失败返回非零。运行期间不读取或修改真实 `gd/`，也不调用 Python。`CT_NATIVE_BIN` 与 `DOTNET_BIN` 可覆盖二进制位置。

`CT_XTASK_BIN` 可覆盖 Rust 准备工具位置。它先验证 32 份输入/参照及清单 SHA，再由当前原生生成器再生 Scalars Binary/C#，要求与 main `8dc7b81` 的旧产物逐字节相同；C# 最后逐字段读取这些新产物。`fixtures/scalars.json` 原字节保留，避免 JS 解析舍入 64 位边界。

`fixtures/fnv_vectors.tsv` 和 Scalars 三件夹具是冻结的独立参照，不会重新生成期望值。缺 FNV 或少于 127 项检查均失败。旧 `prepare.py`、`gen_scalars_bench.py` 只保留历史来源，分类与现役命令见 [test-proj 总览](../README.md)。
