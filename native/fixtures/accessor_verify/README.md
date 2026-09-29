# 独立 C# 读取端夹具

`workspace/` 冻结自 main 旧 `ct/tests/fixtures/repository_cutover/workspace` 的 `config/`、`excel/`、`i18n/`（25 个文件）。这是测试专用小工作区，不是实际 `gd/`。保留原始 Excel 与 Schema，供原生 `ct export` 在临时副本中生成 Binary、JSON 和 C# Accessor，再由 `test-proj/ExportAccessorVerify` 的独立 C# 读取端逐字段比对。

默认验收入口是 `node test-proj/ExportAccessorVerify/prepare-native.mjs`；仅需发布版 `native/target/release/ct`、Node 与 .NET，不调用 `ct/` 或 Python。旧 `prepare.py` 仅保留历史参照，完成 7.3 后再处理其活跃引用。
