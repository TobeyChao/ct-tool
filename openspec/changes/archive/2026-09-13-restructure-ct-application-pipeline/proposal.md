## Why

ct 已有可用的 canonical 领域模型、纯生成器和 Schema Draft→Plan→Apply，但应用层把读取、校验、缓存、生成、发布和成功记账交织在一起：后段失败可能留下部分新产物，CLI/Web 各自定义完成边界，架构依赖检查还存在空扫描。增量导出已在基线提交 `95f04ad` 落地，此时应围绕现有能力建立清晰边界，避免继续增加隐式耦合。

## What Changes

- 保持单进程 Python 模块化架构；提炼共享数据准备/校验服务，把导出拆成输入快照、产物构建、可恢复发布和入口策略驱动的完成流程。
- 以类型化内部请求/结果替代跨阶段的散落字典，保留原 canonical 函数入口与外部返回形状；CLI/Web 只负责参数、呈现和任务生命周期。
- 所有生成及 FBS 检查完成后才发布输出和导出产生的 layout manifest；发布失败可回滚，中断可恢复，同一工作区的 export/deploy 互斥。
- 保留 CLI 导出后部署、Web 仅导出、部署失败不提交成功账本的区别，由同一个应用用例显式表达。
- 保留当前工作树中的内容寻址生成缓存、默认增量、`--all` 强制生成写出、相同内容保留 mtime；修订仍声称“每次全量重建”的规范。
- 修复架构测试的模块发现、单文件模块扫描和 import 节点归一化，增加能证明检查会失败的负例。

## Capabilities

### New Capabilities

- `export-publication`: 全部生成完成后的可恢复发布、取消边界、同工作区 export/deploy 互斥，以及输入快照与成功账本的一致性。

### Modified Capabilities

- `incremental-export`: 将默认增量及强制重建写为正式契约，区分可丢弃生成缓存与成功账本，保留过滤范围。
- `cli-interface`: 更新 export 的增量语义及完成边界，明确现有语言过滤的主语言 JSON 例外，保持参数与部署策略。
- `unity-deploy`: 明确缓存全命中也执行部署，保留 CLI-only 与部署失败的账本语义。

## Impact

- 核心涉及 `ct/src/ct/app/canonical_export.py`、`canonical_commands.py`、`events.py`、`ct/cache/`、`ct/export/deploy.py`、CLI/Web 适配器和 architecture/app/cutover 测试；新增小型 `ct/app/exporting/` 与 `ct/storage/` 模块。
- 不改变 YAML Schema、JSON/FBS/Binary、C#/Lua API、Excel 布局、Web API 路由、launcher 启动协议，不增加服务或数据库；保留当前过滤 Bundle 的内容和输出位置。
- 基线为 2026-09-13 提交 `95f04ad`（增量导出：内容寻址生成缓存 + 传递闭包 schema_hash）；增量代码已随该提交落地，修订时工作树无本地改动，属于基线而非本 change 的成果。实现前记录并复核该提交与产物对照，不重写基线实现。

## Non-goals

- 不重写领域模型、生成器、前端或 launcher，不引入通用 DAG 调度、插件系统、微服务或全仓目录迁移。
- 不改变单表导出的 ref 数据加载范围和过滤 Bundle 语义；相关问题记录为后续独立变更。
- 不把 Unity 目录纳入跨目录事务，不承诺外部读取者在逐文件发布期间看到瞬时原子快照，不重构 Schema Apply 的完整事务协议。
