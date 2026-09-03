## MODIFIED Requirements

### Requirement: 面板服务与工作区
面板 SHALL 以本地服务方式启动，浏览器打开后展示当前工作区、统一顶栏与导出/翻译/Schema/日志/历史模块导航；工作区不可用或配置缺失时 SHALL 显示占据主内容区的明确错误与修复指引，而不是空白页。页面级导航 SHALL 可恢复当前模块和 Schema 工作上下文。

#### Scenario: 启动并打开面板
- **WHEN** 策划启动面板服务并访问本地地址
- **THEN** 页面展示统一 AppShell、五个模块入口、当前工作区路径与健康摘要

#### Scenario: 工作区缺失
- **WHEN** 工作区目录或 `config/global.yaml` 缺失
- **THEN** 面板显示明确的阻塞错误与修复指引，不崩溃、不显示空白页

#### Scenario: 恢复 Schema 工作上下文
- **WHEN** 用户刷新一个指向 Schema 资源和字段属性的有效页面地址
- **THEN** 面板重新加载工作区并恢复资源、页签和字段上下文，不把 pane 显隐状态当作领域状态

### Requirement: 表格管理
面板 SHALL 通过 Schema Workspace 管理 Table、Record、Enum，而不是使用保存即写盘的表编辑弹窗；新增、编辑、改名和删除 SHALL 进入 Workspace Draft，经完整 Candidate 校验和 Change Plan 后原子应用。模板状态 SHALL 继续识别已同步、漂移和未跟踪，并将模板重建影响纳入计划。

#### Scenario: 新增表
- **WHEN** 策划在 Schema Workspace 新建 Table、设置主键与字段并选择“审查并应用”
- **THEN** Change Plan 展示 Schema 与 Excel 影响；应用成功后原子生成定义和模板，资源区出现新 Table 且模板状态为已同步

#### Scenario: 编辑表并应用
- **WHEN** 策划修改字段定义并通过无阻塞的 Change Plan
- **THEN** 系统按稳定字段路径搬移已有数据并原子更新 Schema、Excel 和必需导出产物，工作区重新加载已应用版本

#### Scenario: 模板漂移
- **WHEN** Schema 在面板外被修改或拉取后模板 hash 不匹配
- **THEN** 资源与详情标记模板漂移，并允许用户将保留数据的模板重建加入 Change Plan

#### Scenario: 删除表
- **WHEN** 策划将未被引用的 Table 标记删除并审查变更
- **THEN** Change Plan 明确列出 Schema、Excel 和生成产物影响，确认应用后才删除；若仍有引用则阻止应用并列出引用路径

#### Scenario: 放弃表格草稿
- **WHEN** 策划修改多个资源后选择“放弃草稿”并确认
- **THEN** 所有未应用修改被丢弃，落盘 Schema、Excel 和产物不发生变化
