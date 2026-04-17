## Context

`ct export` 使用 Python flatbuffers 库手动序列化数据，生成 `data_en.bin` / `data_zh.bin`。这些 binary 产物将被游戏客户端（C#/Unity）消费，但目前没有任何 C# 侧的端到端验证。`gd/output/generated/csharp/` 中已有 flatc 生成的 accessor 代码，`ItemAccessor` 等类依赖 `GDNative.GetMainBytes()` 和 `GDNative.GetI18nBytes()` 接口。测试工程需要提供这个接口的文件系统实现。

## Goals / Non-Goals

**Goals:**
- 在 `test-proj/BinaryReaderTest/` 创建独立 .NET 10 控制台工程（`dotnet new console`）
- 读取 `gd/output/binary/data_en.bin`，验证 `DataBundle` 能被正确解析
- 逐表测试：找到 `item`、`item_type`、`quest` 三张表，验证行数与关键字段值不为默认值
- 测试枚举、struct（DropRange）、array（Tags）字段的反序列化
- 以 PASS/FAIL 汇总输出，失败时返回非零退出码（适合 CI）

**Non-Goals:**
- 不测试 i18n bundle（`data_zh.bin`）——留作后续
- 不使用 xUnit/NUnit 等测试框架，保持零额外依赖（仅 `Google.FlatBuffers`）
- 不修改 `ct-tool/` 源码或生成文件

## Decisions

**决策 1：将生成的 C# 文件直接复制到工程目录**

理由：生成文件本身是构建产物，不适合作为 ProjectReference 被引用；直接复制简化工程依赖，且测试工程只做读取，不需要跟随生成文件变更自动更新。`README` 中说明需手动同步即可。

备选方案：符号链接或 Directory.Build.props glob include——在 Windows 下 symlink 需要管理员权限，glob include 配合 git 不稳定，故放弃。

**决策 2：自实现 GDNative 静态类**

`ItemAccessor` 等 accessor 依赖 `GDNative.GetMainBytes()` 和 `GDNative.GetI18nBytes()`。测试工程提供 `GDNative.cs`，从相对路径加载 `data_en.bin`；i18n 路径返回空数组。这样测试工程可以完全复用已生成的 accessor，不需要修改生成代码。

备选方案：绕过 accessor，直接用 `DataBundle` 原始 API——会漏掉 accessor 层的索引逻辑，测试覆盖不完整。

**决策 3：相对路径定位 binary 文件**

测试程序以 `../../gd/output/binary/data_en.bin`（相对于工程目录）定位 binary，便于在项目根目录直接运行 `dotnet run`。若未找到文件则打印明确错误并退出。

## Risks / Trade-offs

- [路径依赖] 工程目录层级变更会导致路径失效 → 在 README 中记录，并在程序入口打印实际解析路径方便调试
- [生成文件同步] 手动复制的 C# 文件可能与最新导出不同步 → 在 README 中说明"每次 `ct export` 后需重新复制"，后续可用脚本自动化
- [FlatBuffers 版本] `Google.FlatBuffers` NuGet 版本需与 flatc 生成代码版本匹配（生成代码标注 `FLATBUFFERS_24_3_25`）→ 固定使用 `24.3.25` 版本
