## Why

`ct export` 生成的 `data_en.bin` / `data_zh.bin` 二进制产物目前没有任何 C# 侧读取测试，无法验证 Python 端 FlatBuffers 序列化与 C# `Google.FlatBuffers` 反序列化是否端到端一致。`test-proj/` 目录尚不存在，需要从零创建一个独立的 .NET 控制台工程来覆盖这个验证盲区。

## What Changes

- 在 `test-proj/` 下新建 .NET 8 控制台工程 `BinaryReaderTest`
- 引用 `Google.FlatBuffers` NuGet 包
- 将已生成的 C# FlatBuffers accessor 文件（`gd/output/generated/csharp/`）链接／复制进工程
- 实现 `GDNative` 静态辅助类，从文件系统加载 `data_en.bin`
- 编写测试逻辑：解析 `DataBundle` → 按表名查找 BundledTable → 反序列化 `ItemTable`、`ItemTypeTable`、`QuestTable`，断言行数与关键字段值
- 输出 PASS / FAIL 摘要，非零退出码表示失败

## Capabilities

### New Capabilities

- `csharp-binary-reader-test`: 独立 .NET 控制台测试工程，端到端验证 ct 导出的 FlatBuffers 二进制产物在 C# 侧能被正确解析

### Modified Capabilities

（无）

## Impact

- 新增 `test-proj/` 目录，不影响现有 `ct-tool/` 和 `gd/` 工作区
- 依赖 `gd/output/binary/data_en.bin` 和 `gd/output/generated/csharp/` 中的生成文件
- 不修改任何现有源码或产物
