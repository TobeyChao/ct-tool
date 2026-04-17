## Why

游戏/应用项目中，策划通过 Excel 填写配表数据，程序需要将其转换为服务器可读的 JSON 和客户端可读的 FlatBuffers Binary，目前缺乏统一的自动化工具，手动处理容易出错且效率低。

## What Changes

- 新增 `ct` CLI 工具，支持 `export`、`validate`、`gen-template`、`status` 命令
- 引入外部 YAML Schema 文件，由程序定义表结构、字段类型、跨表引用和 i18n 标记
- 工具根据 Schema 自动生成 Excel 模板头部（前几行），减少策划填表错误
- 支持增量导出（hash 比对），只重新导出有变更的表
- 跨表引用校验（ID 存在性）+ 拓扑排序，确保导出顺序正确
- i18n 多语言支持：主语言全量导出，次语言只导出 i18n 字段差量
- 自动从 Schema 生成 `.fbs` 文件，并调用 `flatc` 编译生成 C++/C#/Lua 代码
- Binary 产物以 FlatBuffers Bundle 形式合并输出，减少文件数量

## Capabilities

### New Capabilities

- `schema-management`: 外部 YAML Schema 的加载、校验、引用图构建与拓扑排序
- `excel-processing`: Excel 文件读取、模板头部生成、hash 变更检测
- `data-validation`: 字段类型校验与跨表引用 ID 存在性校验
- `json-export`: 将配表数据按语言导出为 JSON 文件
- `flatbuffers-export`: 从 Schema 生成 .fbs 文件，构建 FlatBuffers Binary Bundle
- `i18n-pipeline`: i18n 字段提取、翻译文件管理（stale 检测）、多语言合并导出
- `incremental-export`: 基于文件 hash 的增量导出与 cache 状态管理
- `cli-interface`: Typer 实现的 CLI 入口，支持 export/validate/gen-template/status

### Modified Capabilities

## Impact

- **新增依赖**：`openpyxl`（Excel 读写）、`flatbuffers`（Binary 构建）、`typer`（CLI）、`pydantic`（Schema 模型）、`pyyaml`（Schema 加载）
- **外部工具**：需要 `flatc`（FlatBuffers 编译器），通过 `config/global.yaml` 配置相对路径（无需加入 PATH）
- **输出产物**：JSON 文件、FlatBuffers Binary Bundle、.fbs 文件、flatc 生成的 C++/C#/Lua 头文件、i18n 翻译源文件
- **C++ 客户端**：需使用工具生成的 FlatBuffers 头文件读取 Binary Bundle（从零开始，无历史包袱）
