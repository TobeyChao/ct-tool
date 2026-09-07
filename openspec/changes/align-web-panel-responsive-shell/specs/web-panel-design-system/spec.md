## MODIFIED Requirements

### Requirement: Unified application shell
Web Panel SHALL 使用统一侧栏式壳层：`>=740px` 侧栏常驻（品牌 + 模块文字导航 + 底部辅助入口），不显示全局顶栏；`<740px` 显示窄屏顶栏（汉堡按钮 + 品牌标记 + 工作区根目录名），侧栏变为汉堡抽屉（backdrop 遮罩 + Esc 关闭），不提供手机底部导航。模块导航 SHALL 覆盖导出、翻译、Schema、日志和历史；健康摘要仅由导出页内容呈现。

#### Scenario: Switch modules during an active task
- **WHEN** 导出运行中用户切换到 Schema
- **THEN** 模块内容切换但全局 TaskBar 继续显示导出状态，侧栏高亮与新模块一致

#### Scenario: Narrow to hamburger drawer
- **WHEN** 视口 `<740px` 且用户点击汉堡按钮
- **THEN** 侧栏以抽屉滑入并带 backdrop，Esc、backdrop 点击或选择模块后关闭抽屉且焦点回到汉堡按钮；页面不出现底部导航

#### Scenario: Desktop has no global workspace chrome
- **WHEN** 视口 `>=740px` 打开面板
- **THEN** 不显示顶栏、全局工作区路径或健康摘要；工作区上下文仅由导出页内容与窄屏顶栏（根目录名）呈现

## ADDED Requirements

### Requirement: Dialog variant contract
共享 Dialog SHALL 提供危险确认、表单、选择器和调色板四种变体，并复用同一模态骨架：焦点陷阱（跳过 disabled 控件）、Escape 关闭最上层、关闭后还焦触发元素、背景点击关闭、打开时对下层内容应用 inert；弹窗标题 id SHALL 唯一，嵌套打开不得冲突。宽度变体 SHALL 为：小号 `min(420px, 92vw)`、标准 `min(560px, 100vw-40px)`、变更计划 `min(640px, 100vw-40px)`、快速打开调色板 `min(480px, 92vw)`。初始焦点 SHALL 遵循：危险确认 → 取消按钮，表单 → 第一个输入框，选择器 → 搜索框。危险操作主按钮 SHALL 使用独立 danger 语义色且配按钮文案，不得只靠颜色传达。

#### Scenario: Danger confirm with reverse references
- **WHEN** 用户尝试删除仍被反向引用的资源
- **THEN** 弹窗显示反向引用 blocker 列表，主删除按钮禁用，文案表明不提供级联删除

#### Scenario: Danger confirm initial focus
- **WHEN** 删除确认弹窗打开且用户按 Enter
- **THEN** 焦点位于「取消」，不会触发删除

#### Scenario: Form validation blocks submit
- **WHEN** 用户在添加字段弹窗输入非法字段名并点击「添加字段」
- **THEN** 弹窗不关闭，字段名输入框红框并显示行内校验提示，命令未进入草稿

#### Scenario: Type picker returns selection
- **WHEN** 用户在类型选择器点选 ItemRarity
- **THEN** 选择器关闭，添加字段弹窗的类型行回填为 ItemRarity

#### Scenario: Nested dialogs unwind by Escape
- **WHEN** 添加字段弹窗上叠开类型选择器且用户连按 Esc
- **THEN** 先关闭类型选择器回到添加字段弹窗，再按 Esc 关闭添加字段弹窗，焦点逐层恢复

### Requirement: Implicit workspace draft surfacing
Schema 编辑 SHALL 不提供「加入草稿」显式用户步骤：删除/添加等命令经确认后立即进入 Workspace Draft。草稿表面 SHALL 为壳层 main 底部常驻状态条且跨模块可见：未应用命令数（按待应用光标计数）+ 撤销/重做 + 「审查并应用」主操作；无待应用命令且无重做分支时状态条隐藏。全部撤销后状态条 SHALL 保留并呈现可重做态。草稿持久化失败 SHALL 在状态条上持续显示可处理的警告（不只 Toast），内存草稿仍可用。⌘Z / ⇧⌘Z SHALL 触发草稿撤销/重做。

#### Scenario: Delete lands in draft
- **WHEN** 用户在删除确认弹窗点击「删除」
- **THEN** 命令立即进入草稿，状态条显示「1 条未应用变更」，文件与导出产物未被修改

#### Scenario: Undo to zero keeps redo reachable
- **WHEN** 用户撤销至待应用命令为 0 且存在重做分支
- **THEN** 状态条保留并显示「已全部撤销 · 可重做」，撤销/审查禁用、重做可用

#### Scenario: Persistence failure warning persists
- **WHEN** IndexedDB 写入草稿失败
- **THEN** 状态条持续显示「草稿未持久化」警告，编辑继续保留在内存

#### Scenario: Keyboard undo and redo
- **WHEN** 用户在任意模块按 ⌘Z 或 ⇧⌘Z
- **THEN** Schema 草稿相应撤销/重做一条命令，状态条计数与按钮态同步

### Requirement: Change plan review dialog
「审查并应用」SHALL 打开变更计划弹窗：风险徽标（安全/数据依赖/破坏/不兼容/依赖破坏）+ 按影响的产物清单（Schema/Excel/FBS/Binary/Accessor · 表 · 动作）+ 阻塞项列表（含位置与样例值）+ 计划有效期提示（默认 2 小时，过期需重新生成）。存在阻塞项 SHALL 禁用应用按钮。删除资源确认弹窗 SHALL 提供「查看影响」入口，以预览模式打开本弹窗（该命令未进入草稿，应用与放弃草稿禁用）。应用成功后弹窗关闭、草稿清空，状态条以成功态短暂显示已应用清单后隐藏。

#### Scenario: Blocked plan cannot apply
- **WHEN** 变更计划存在数据破坏或依赖破坏阻塞项
- **THEN** 应用按钮禁用，阻塞项列出位置与样例值

#### Scenario: Delete dialog previews impact
- **WHEN** 用户在删除资源确认弹窗点击「查看影响」
- **THEN** 变更计划弹窗以预览模式打开：横幅标明该删除「尚未加入草稿」，应用与放弃草稿按钮禁用；关闭预览后回到删除确认弹窗

#### Scenario: Successful apply resets draft
- **WHEN** 计划无阻塞且应用成功
- **THEN** 弹窗关闭、状态条以成功态显示「已应用：<资源清单>」并在数秒后自动隐藏，撤销栈清空

#### Scenario: Discard draft requires confirmation
- **WHEN** 用户在变更计划弹窗点击「放弃草稿」
- **THEN** 打开小号确认弹窗「放弃 N 条未应用变更？此操作不可撤销」，初始焦点在「取消」；确认后命令清空、状态条消失、变更计划弹窗一并关闭；取消则不改变草稿

### Requirement: External documentation link
侧栏「导出文档」SHALL 直接打开外部文档页，不弹窗（标记为外部链接）。

#### Scenario: Documentation opens externally
- **WHEN** 用户点击侧栏「导出文档」
- **THEN** 新开外部文档页，应用内不出现浮层或弹窗

### Requirement: About and Help dialogs
侧栏底部 SHALL 提供「导出文档 / 帮助与反馈 / 关于」入口：帮助与反馈与关于 SHALL 打开标准骨架静态弹窗（Esc、背景点击、关闭按钮均可关闭），帮助内容列出的快捷键 SHALL 与实际实现的快捷键一致。

#### Scenario: Open about from sidebar
- **WHEN** 用户点击侧栏底部「关于」
- **THEN** 打开关于弹窗（版本与工作区信息），三种方式均可关闭且不残留遮罩

#### Scenario: Help shortcuts are truthful
- **WHEN** 用户打开帮助与反馈弹窗
- **THEN** 列出的快捷键（⌘P、⌘Z/⇧⌘Z、Esc）均为实际生效的快捷键
