# 原生导出与独立 C# 读取端验收

在仓库根目录先构建发布版 `ct`，再运行：

```sh
cargo build --manifest-path native/Cargo.toml -p ct-cli --release
node test-proj/ExportAccessorVerify/prepare-native.mjs
```

脚本复制 `native/fixtures/accessor_verify/workspace` 到临时目录，由原生 `ct export --all` 生成 Binary、JSON 与 C# Accessor，再临时编译本项目的 `Program.cs` 和独立读取器。它逐行逐字段对照导出 JSON，并验证 CodeName、语言切换和标量边界；失败返回非零。运行期间不读取或修改真实 `gd/`，也不调用 Python。`CT_NATIVE_BIN` 与 `DOTNET_BIN` 可覆盖二进制位置。

`fixtures/fnv_vectors.tsv` 和 Scalars 三件夹具是已冻结的独立参照；默认验收不会重新生成期望值。旧 `prepare.py` 是历史 Python 准备入口，不属于新的正式命令。
