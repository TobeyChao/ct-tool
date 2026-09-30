# 独立 C# 读取端夹具

`workspace/` 冻结自 main 的历史测试小工作区的 `config/`、`excel/`、`i18n/`（25 个文件）。这是测试专用小工作区，不是实际 `gd/`。保留原始 Excel 与 Schema，供原生 `ct export` 在临时副本中生成 Binary、JSON 和 C# Accessor，再由 `test-proj/ExportAccessorVerify` 的独立 C# 读取端逐字段比对。

默认验收入口是 `node test-proj/ExportAccessorVerify/prepare-native.mjs`；仅需原生 `ct`、`xtask`、Node 与 .NET。`prepare.py` 与 `gen_scalars_bench.py` 只保留来源文本，不执行。

`independent-oracles.json` + `.sha256` 固定 25 份工作区输入、四份 main 标量/FNV 参照、新声明式标量 Schema、两份 main `8dc7b81` 来源脚本文本（32 文件）。旧工作区和参照字节与 main 相同，Schema 按来源脚本的字段顺序转录。`xtask accessor-fixtures --out <临时目录>` 先校验全部摘要，由当前 Rust Binary/C# 生成器再生标量产物，逐字节匹配旧独立参照后写入临时输出；期望值始终冻结，来源文本不执行。
