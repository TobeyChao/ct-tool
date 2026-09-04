## REMOVED Requirements

### Requirement: 工程可独立构建
测试工程 `test-proj/BinaryReaderTest/BinaryReaderTest.csproj` SHALL 以 `dotnet build` 成功编译，仅依赖 `Google.FlatBuffers 24.3.25` NuGet 包，无其他外部依赖。

### Requirement: 读取并验证 DataBundle
程序 SHALL 从 `gd/output/binary/data_en.bin` 加载字节，使用 `DataBundle.GetRootAsDataBundle` 解析，断言 `TablesLength > 0`。

### Requirement: 验证 item 表
程序 SHALL 在 Bundle 中找到名称为 `item` 的 BundledTable，将其 `data` 字节反序列化为 `ItemTable`，断言行数 > 0，并验证第一行的 `Id`、`Name`、`Price` 字段值合理（Id > 0，Name 非空，Price >= 0）。
