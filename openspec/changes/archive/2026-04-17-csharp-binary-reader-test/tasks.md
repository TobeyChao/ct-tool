## 1. 工程搭建

- [x] 1.1 在 `test-proj/` 下执行 `dotnet new console -n BinaryReaderTest`（使用默认 .NET 10），然后 `dotnet add package Google.FlatBuffers --version 24.3.25`
- [x] 1.2 将 `gd/output/generated/csharp/` 中所有 `.cs` 文件复制到 `test-proj/BinaryReaderTest/Generated/`
- [x] 1.3 创建 `GDNative.cs`，实现 `GetMainBytes()`（从相对路径加载 `data_en.bin`）和 `GetI18nBytes()`（返回空数组）

## 2. 测试逻辑实现

- [x] 2.1 在 `Program.cs` 中实现 `LoadBundle()`：读取文件字节，调用 `DataBundle.GetRootAsDataBundle`，文件不存在时打印路径并退出
- [x] 2.2 实现 `TestItemTable(DataBundle bundle)`：找到 `item` 表，反序列化 `ItemTable`，断言行数 > 0、第一行 Id > 0、Name 非空、Price >= 0
- [x] 2.3 在 `TestItemTable` 中额外验证 `DropRange.Min <= DropRange.Max` 及 `Tags` 数组不抛异常
- [x] 2.4 实现 `TestItemTypeTable(DataBundle bundle)`：找到 `item_type` 表，断言行数 > 0、第一行 Id > 0
- [x] 2.5 实现 `TestQuestTable(DataBundle bundle)`：找到 `quest` 表，断言行数 > 0、第一行 Id > 0
- [x] 2.6 在 `Program.cs` main 函数中串联所有测试，收集失败计数，打印 PASS/FAIL 汇总，失败时 `Environment.Exit(1)`

## 3. 验证

- [x] 3.1 执行 `dotnet build`，确认无编译错误
- [x] 3.2 执行 `dotnet run`，确认输出 `[PASS]` 行及 `All tests passed.`
- [x] 3.3 人为破坏一个断言（如删除 bin 文件），确认输出 `[FAIL]` 行且退出码为 1，然后还原
