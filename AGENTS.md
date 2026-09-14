# AGENTS.md

本仓库是 `ct` 配表导出工具：从 Excel + YAML Schema 生成 JSON、FlatBuffers Binary 和 C#/Lua Accessor。`ct/` 是自包含 Python 工具，`gd/` 是真实游戏数据工作区，`launcher/` 是 Flutter 桌面壳。当前只有 canonical 一套实现。

## 工作方式与完成标准

- 在用户要求的范围内持续完成工作。实现任务包括把相关流程运行起来、检查结果并修复本次改动引入的问题，不以第一版代码作为完成点；普通实现选择自行判断，影响产品范围或兼容性的关键歧义再询问。
- 本地测试使用临时工作区夹具，可自行运行、修复与复验，无须逐步申请许可。按改动影响选择验证；文档小改不需要全套测试，已有检查通过且没有新风险时无需重复运行。
- 保护用户和其他任务的改动；遇到并发修改先重新读取并整合。真实 `gd/` 不用作测试夹具，生成其产物仅在任务涉及该工作区时进行。
- 仅 review 时报告有依据的问题；要求「有问题就修」时完成修复与回归验证。未提交实现通常以 `HEAD` 为审查基线，包含相关未跟踪文件。
- 完成时简述结果、实际验证和剩余限制。提交、推送、部署及历史改写按用户授权执行。

## 项目约束

- Python 使用 `ct/.venv`，不要全局安装。例：在仓库根目录运行 `ct/.venv/bin/python -m pytest ct/tests/app/`；Windows 使用 `ct/.venv/Scripts/python.exe`。浏览器测试需要 Playwright Chromium。
- CLI/Web 是薄壳，复用 canonical app 用例、领域校验和存储能力；不要新增平行业务链路。配置路径通过 `cfg.resolve(...)` 相对游戏工作区解析。
- Schema 编辑走 Draft → 服务端候选/净差异 → YAML-only 保存。`schemaRevision` 与 `candidateHash` 是必需守卫；候选刷新不能替换草稿基线。保存不改 Excel、翻译、导出产物或成功账本，模板生成、导出与部署保持显式独立。
- save/export/deploy 复用工作区锁与可恢复发布器。恢复须在加载资源前完成，既还原旧文件也清理本事务新增文件。资源创建检查名称、规范化目标路径、跨平台大小写冲突和 Excel 归属。
- 导出先通过读取、类型、主键及 ref 校验闸门再发布。生成缓存可丢弃，成功账本只在成功后推进；修改生成器行为时更新 `exporting/build.CODEGEN_VERSION`。
- proposal 请求只产出规划；明确要求实施后再实现。OpenSpec 任务按实际验收结果勾选，规格同步和归档不能代替实现验证。
- 本地搜索优先 `rg`；网络搜索使用 anysearch MCP，不可用时说明并使用可用工具。

## 按需查阅

只读取当前任务需要的内容，无需每次编辑先遍历文档。

- 安装、CLI、数据目录和术语：[`ct/docs/README.md`](ct/docs/README.md)；详细目录与命令见[项目参考](ct/docs/agent-project-reference.md)。
- 调整模块职责、数据流、i18n 或 Schema 格式：[项目参考的架构与格式说明](ct/docs/agent-project-reference.md#架构)。
- 修改 Schema 保存、草稿恢复或旧 Apply 迁移：[`ct/docs/schema-save-migration.md`](ct/docs/schema-save-migration.md) 和 `openspec/specs/schema-editor/` 中对应规格。
- 修改 Excel 表头：`openspec/specs/excel-template-styling/spec.md`；修改数据读取或模板迁移：`openspec/specs/excel-processing/spec.md`。
- 实施 OpenSpec change：读取该 change 的 proposal、design、delta specs、tasks 及相关前置；其他任务按需查 `openspec/specs/` 中对应能力。
- launcher 构建与分发：[项目参考](ct/docs/agent-project-reference.md#launcher-打包与分发)及 `launcher/docs/design/` 中相关设计。
