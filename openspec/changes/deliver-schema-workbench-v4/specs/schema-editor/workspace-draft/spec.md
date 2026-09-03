## Purpose

定义 Schema 编辑从已落盘快照到 Workspace Draft、Candidate Workspace、Change Plan 和原子 Apply 的事务边界，使跨资源修改可撤销、可审查、可定位，并保证失败时不会留下部分更新的工作区。

## ADDED Requirements

### Requirement: Workspace-scoped draft commands
所有 Schema 编辑 SHALL 先记录为 Workspace Draft command，不立即写 YAML、Excel 或导出产物；Draft SHALL 支持 undo、redo、撤销当前字段修改和放弃全部，并独立于页面与 pane 生命周期。

#### Scenario: Undo a resource rename
- **WHEN** 用户改名 Record 后执行 undo
- **THEN** Record 名称及该 command 引起的引用更新一起恢复，其他未撤销 command 保留

#### Scenario: Switch resources with pending changes
- **WHEN** Item 含未应用字段修改且用户切换到 Quest
- **THEN** Item 修改继续存在于 Workspace Draft，草稿摘要显示对应资源和变更数量

### Requirement: Durable browser draft persistence
Web Panel SHALL 将带格式版本的 Draft command log 存入 IndexedDB，并按工作区与 base revision 隔离；`localStorage` SHALL 只存放 pane preference、最近资源等小型偏好。持久化失败 SHALL 保留当前内存 Draft 并显示持续、可处理的警告。

#### Scenario: Restore a matching draft after refresh
- **WHEN** 页面刷新且 IndexedDB 中 Draft 的工作区、格式版本和 base revision 均匹配
- **THEN** 系统恢复 commands、undo cursor 和派生草稿，不依赖 DOM 或当前断点

#### Scenario: Browser storage quota fails
- **WHEN** 写入 Draft 因配额、权限或数据库错误失败
- **THEN** 当前编辑继续保留在内存，TaskBar 或草稿区持续显示“草稿未持久化”，不得仅显示短暂 Toast

### Requirement: Candidate workspace validation
“审查并应用” SHALL 从当前落盘 snapshot 与 Draft 构建完整 Candidate Workspace，执行类型、名称、依赖、引用、数据和生成器能力校验；局部编辑无错误不代表候选工作区可应用。

#### Scenario: Cross-resource validation failure
- **WHEN** 单个字段编辑合法但 Candidate Workspace 中形成资源依赖环
- **THEN** Change Plan 返回阻塞问题和完整循环路径，Apply 不可用

### Requirement: Reviewable Change Plan
系统 SHALL 在不修改文件的情况下生成 Change Plan，按安全新增、数据依赖、数据破坏、客户端不兼容和依赖破坏分类，并展示 Schema、Excel、FBS、Binary、C#/Lua Accessor 影响及可定位的问题。

#### Scenario: Review a field rename
- **WHEN** 用户显式将 `Item.Name` 改名为 `Item.DisplayName`
- **THEN** Change Plan 显示字段路径映射、非空数据行数量、生成 API 变化和是否存在转换失败

#### Scenario: Review a destructive column reduction
- **WHEN** `excel_columns` 收缩且被移除的组中存在数据
- **THEN** Change Plan 将其标记为数据破坏阻塞项，列出 Excel 行列和样例值

### Requirement: Stale plan protection
Change Plan SHALL 绑定 snapshot hash、candidate hash、受管输入 manifest、plan id 和 `expiresAt`；默认有效期 SHALL 为生成后 2 小时。Apply 前 SHALL 重新确认源工作区和候选内容未变化；任一 hash 不匹配或超过有效期都必须拒绝并要求重新审查，TTL 不得替代内容校验。

#### Scenario: Source files change after review
- **WHEN** Change Plan 生成后 YAML 或 Excel 被其他进程修改
- **THEN** Apply 返回 plan stale，不写文件，并提示重新加载与生成计划

#### Scenario: Plan expires without source changes
- **WHEN** 当前时间超过 `expiresAt`，即使 snapshot 与 candidate hash 未变化
- **THEN** Apply 拒绝旧 plan、清理其 staged 资源并要求重新生成计划

### Requirement: Atomic full-pipeline apply
Apply SHALL 在隔离临时目录中生成 Schema、Excel、JSON、FBS、Binary 与 Accessor 必需产物，完成 postcheck 后才原子替换目标；任一必需步骤失败 SHALL 保持原工作区可用且不提交部分结果。

#### Scenario: Accessor generation fails
- **WHEN** Candidate 的 YAML、Excel 和 FBS 已在临时目录生成但 Lua Accessor 生成失败
- **THEN** Apply 整体失败，原 YAML、Excel、Binary 和生成代码保持原状，错误定位到失败步骤

#### Scenario: Apply succeeds
- **WHEN** 全部生成和 postcheck 成功且 plan 仍有效
- **THEN** 系统原子发布候选文件、重新加载 WorkspaceSnapshot、清空已应用 Draft，并返回完整变更摘要

#### Scenario: Excel target is locked on Windows
- **WHEN** 发布前发现待替换 `.xlsx` 正被 Excel/Office 占用且无法原子替换
- **THEN** Apply 在进入 backup/publish 前失败，列出被占用路径并提示关闭 Excel 后重试，原工作区与 cache 均不改变

### Requirement: Apply recovery and observability
系统 SHALL 为 Apply 保留可恢复备份或等价回滚点，并通过任务状态持续暴露步骤、进度、失败原因和恢复结果；需要用户处理的错误不得只显示 toast。

#### Scenario: Process interruption during publish
- **WHEN** 进程在替换目标文件期间异常中断
- **THEN** 下一次启动检测不完整事务并恢复到一致的旧版本或完成已验证的新版本，不加载混合文件集
