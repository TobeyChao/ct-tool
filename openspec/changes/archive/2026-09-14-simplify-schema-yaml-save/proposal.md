## Why

现有「审查并应用」规范把 Schema 保存与 Excel 重建、导出产物生成绑定，实际实现却仅写 YAML，并维护两套计划与事务机制。草稿还把反复勾选、取消和重命名的操作次数当作未保存变更，增加理解成本；需要让保存边界和最终差异一致。

## What Changes

- **BREAKING** 将「审查并应用」替换为「保存变更」：仅校验并事务化保存配置目录内 Table/Record/Enum YAML，不改 Excel、layout manifest、翻译文件或导出产物。
- 用一次带 Schema 基线的保存请求替代 change-plan → prepare-apply → apply；移除持久化计划与两小时 TTL，统一复用工作区锁和可恢复文件发布。
- 保留完整命令历史及撤销光标；从原始结构和最终候选计算净差异，按变化资源展示摘要。往返修改归零时禁止保存且不改文件，历史仍可撤销/重做。
- 只写真实变化的 YAML，正确处理资源删除、重命名及引用更新；结构校验失败或源文件并发变化时保留草稿。
- Excel 更新保持独立显式操作；保存后提示模板待更新，validate/export 在布局无法确认匹配时拒绝误读，不能借导出刷新 manifest 掩盖漂移。保存不再有数据预检，因此数据侧约束必须由 validate/export 独自兜住：Enum token 域校验补进共享数据校验（当前未知 token 会被 Binary serializer 静默写成 ordinal 0）。
- 不新增持久化重命名迁移记录或自动迁移向导；后续模板更新无法证明无损时停止，不猜测字段映射。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `schema-editor/workspace-draft`: YAML-only 保存事务、Schema 基线并发保护、净差异与历史分离，替换完整流水线 Apply 与持久计划契约。
- `web-panel-design-system`: 草稿条显示变化资源数与保存动作，移除强制计划弹窗和产物重建承诺，保留可定位错误与必要删除确认；同时移除已死的「变更计划」Dialog 宽度变体。
- `excel-processing`: 将迁移风险处理移到显式模板更新；定义与保存解耦的读取兼容性闸门。
- `schema-management`: Enum 重命名/删除/重排的呈现改由净差异摘要承担；删除仍被数据使用的 item 不再阻止保存，数据侧交给读取闸门。
- `schema-editor/query-indexes`: 删除编辑器侧数据预检，CodeName 非空/唯一约束明确只在 validate/export 执行。
- `schema-editor/type-system`、`schema-editor/workbench`、`flatbuffers-export`: 去掉对 Change Plan / Apply 的引用，改为净差异摘要、保存前校验与读取兼容性检查的措辞。
- `incremental-export`: 删除描述独立 Apply 的 requirement（其记录的「fingerprint/cache 发布未实现」结论保留在迁移说明中）。
- `data-validation`: 新增 Enum token 域闸门 —— 未知 token 必须在 validate/export 报类型错误，不再被 Binary serializer 静默映射为 ordinal 0。

## Impact

涉及 `ct/app/schema_workspace/`、Schema Web API、草稿 IndexedDB 与前端状态条/弹窗、共享数据读取 preparation（新增 Enum token 域闸门）、模板更新预检、文档及相关测试。本变更同时要收口 11 个能力的主规格措辞：`Change Plan`/`Apply` 被删除后，`schema-management`、`schema-editor/{query-indexes,type-system,workbench}`、`flatbuffers-export`、`incremental-export`、`web-panel-design-system` 中指向该机制的 requirement 必须由 delta 重述，`schema-editor/workspace-draft` 的 Purpose 只能在归档后手工修正（工具忽略已有规格的 delta Purpose）。内部 Schema Web API 为破坏性切换，前后端同步发布；现有 YAML 格式和 CLI 命令不变，不增加第三方依赖。共享锁/发布器复用现有实现，旧 Apply 未完成事务须安全恢复后才能切换，不能直接清理恢复材料。此变更不实现 Excel 表头重建新算法、不自动迁移 i18n、不自动导出或部署。
