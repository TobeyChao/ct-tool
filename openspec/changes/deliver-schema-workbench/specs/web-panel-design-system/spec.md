## Purpose

定义 ct Web Panel 跨导出、i18n、Schema、日志和历史模块共享的视觉、组件、任务反馈和可访问性交互契约，使所有页面呈现为同一个高密度商业化数据工作台。

## ADDED Requirements

### Requirement: Unified application shell
Web Panel SHALL 使用统一顶栏与模块导航；顶栏只展示品牌、工作区路径、健康摘要和当前模块主操作，模块导航 SHALL 覆盖导出、翻译、Schema、日志和历史且在手机宽度移到底部。

#### Scenario: Switch modules during an active task
- **WHEN** 导出运行中用户切换到 Schema
- **THEN** 模块内容切换但全局 TaskBar 继续显示导出状态，工作区路径和健康摘要保持一致

### Requirement: Shared visual tokens
所有模块 SHALL 使用同一套颜色、字体、间距、边界、焦点和状态 token；品牌交互色 SHALL 使用森林绿体系，warning 和 danger SHALL 使用独立语义色且不得只依赖颜色传达含义。

#### Scenario: Render a blocking error
- **WHEN** 任一模块显示阻塞错误
- **THEN** 错误使用统一 danger token、图标或文案和可定位入口，不使用绿色或仅颜色差异表达

### Requirement: Shared component contracts
AppShell、ModuleHeader、CommandBar、DataTable、Inspector、StatusBadge、InlineIssue、TaskBar、Dialog、Toast 和 EmptyState SHALL 在模块间复用相同的结构与交互契约，不得为每个页面复制变体 CSS 和状态逻辑。

#### Scenario: Display an empty module state
- **WHEN** 某模块没有可显示数据
- **THEN** EmptyState 解释为空原因并提供唯一下一步，不使用装饰性大卡片或与其他模块不同的按钮层级

### Requirement: Error and task persistence
需要处理的错误 SHALL 与对象相邻或保留在任务状态中；异步任务进度和失败 SHALL 跨模块切换保持可见，Toast 只反馈已完成的轻量动作。

#### Scenario: Export fails after leaving export module
- **WHEN** 用户已切到日志模块且后台导出失败
- **THEN** TaskBar 保留失败步骤与入口，用户可定位日志；系统不只弹出会消失的 toast

### Requirement: Consistent actions and motion
每个可见工作区 SHALL 最多有一个实心 primary action；危险操作不得使用 primary 样式；动效 SHALL 只表达 180-200ms 状态切换或轻量反馈，并尊重 reduced motion。

#### Scenario: Schema draft has blocking issues
- **WHEN** Change Plan 存在阻塞项
- **THEN** “应用变更”禁用且附近说明原因，破坏性“放弃草稿”使用非 primary 危险样式

### Requirement: Frontend accessibility baseline
共享组件 SHALL 提供键盘路径、可见焦点、标签、语义状态、焦点恢复和足够文本对比度；隐藏内容 SHALL 使用条件渲染或 `hidden/inert`，不能仅靠透明度或负位移。

#### Scenario: Operate the panel without a pointer
- **WHEN** 用户只使用键盘浏览模块、表格、检查器和 Dialog
- **THEN** 焦点顺序与视觉顺序一致，所有关键操作可达，关闭临时 UI 后焦点回到合理触发点
