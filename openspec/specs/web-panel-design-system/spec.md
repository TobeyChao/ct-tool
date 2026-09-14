# web-panel-design-system Specification

## Purpose
定义 ct Web Panel 跨导出、i18n、Schema、日志和历史模块共享的视觉、组件、任务反馈和可访问性交互契约，使所有页面呈现为同一个高密度商业化数据工作台。

## Requirements

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
- **WHEN** Schema 候选存在已知结构阻塞项
- **THEN** 「保存变更」禁用且附近说明原因，破坏性「放弃草稿」使用非 primary 危险样式

### Requirement: Frontend accessibility baseline
共享组件 SHALL 提供键盘路径、可见焦点、标签、语义状态、焦点恢复和足够文本对比度；隐藏内容 SHALL 使用条件渲染或 `hidden/inert`，不能仅靠透明度或负位移。

#### Scenario: Operate the panel without a pointer
- **WHEN** 用户只使用键盘浏览模块、表格、检查器和 Dialog
- **THEN** 焦点顺序与视觉顺序一致，所有关键操作可达，关闭临时 UI 后焦点回到合理触发点

### Requirement: Dialog variant contract
共享 Dialog SHALL 提供危险确认、表单、选择器和调色板四种变体，并复用同一模态骨架：焦点陷阱（跳过 disabled 控件）、Escape 关闭最上层、关闭后还焦触发元素、背景点击关闭、打开时对下层内容应用 inert；弹窗标题 id SHALL 唯一，嵌套打开不得冲突。宽度变体 SHALL 为：小号 `min(420px, 92vw)`、标准 `min(560px, 100vw-40px)`、快速打开调色板 `min(480px, 92vw)`。初始焦点 SHALL 遵循：危险确认 → 取消按钮，表单 → 第一个输入框，选择器 → 搜索框。危险操作主按钮 SHALL 使用独立 danger 语义色且配按钮文案，不得只靠颜色传达。

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
Schema 编辑 SHALL 不提供「加入草稿」步骤；操作进入可撤销的工作区草稿。壳层底部跨模块状态条 SHALL 显示最终变化资源数、撤销/重做、「保存变更」及放弃入口，不显示操作次数作为未保存数。重命名同一资源 SHALL 计一次，引用连带修改的资源 SHALL 分别计数。净差异为零时 SHALL 禁用保存并保留可用历史入口；没有历史、警告或成功反馈时隐藏。持久化警告 SHALL 持续显示，⌘Z/⇧⌘Z SHALL 保留逐步撤销/重做行为。

#### Scenario: Delete lands in draft
- **WHEN** 用户在删除确认弹窗点击删除
- **THEN** 文件未被修改，状态条显示净变化资源数

#### Scenario: Toggle returns to baseline
- **WHEN** CodeName 开启再关闭且没有其他净变化
- **THEN** 显示「无未保存修改」，保存禁用，撤销仍可回到开启状态

#### Scenario: Undo to zero keeps redo reachable
- **WHEN** 用户撤销至基线且存在重做分支
- **THEN** 状态条保留，保存禁用，重做可用

#### Scenario: Persistence failure warning persists
- **WHEN** IndexedDB 写入草稿失败
- **THEN** 状态条持续显示草稿未持久化，内存编辑继续可用

#### Scenario: Keyboard undo and redo
- **WHEN** 用户在任意模块按草稿撤销/重做快捷键
- **THEN** 移动一条历史步骤，净差异资源数与按钮同步刷新

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

### Requirement: Direct Schema save feedback
「保存变更」SHALL 直接提交当前净差异对应的草稿，不先打开全产物审查弹窗。可查看摘要 SHALL 展示原始到最终的 YAML 结构差异及结构兼容性提示，不承诺 Excel 搬移或产物生成。候选仍在计算或保存进行中 SHALL 禁止提交过期候选；保存期间 SHALL 防止草稿变化被成功响应误清除。保存成功 SHALL 更新基线、清空本次历史、显示「已保存」；失败 SHALL 保留草稿并持续展示问题。

#### Scenario: Repeated rename summary
- **WHEN** 同一字段从 A 经 B 改到 C
- **THEN** 摘要显示 A→C，不展示两次改名为两条待保存变化

#### Scenario: Save without review ceremony
- **WHEN** 用户点击合法且有净变化草稿的保存按钮
- **THEN** 显示保存进度并提交，无计划生成/有效期/应用确认步骤

#### Scenario: Successful save leaves Excel untouched
- **WHEN** 保存完成且受影响表出现模板漂移
- **THEN** 显示 YAML 已保存及模板待更新提示，更新模板由用户独立触发

#### Scenario: Status refresh fails after successful save
- **WHEN** YAML 已成功保存但模板状态查询失败
- **THEN** 仍显示保存成功并说明状态暂不可用，不诱导用户重放已保存命令

#### Scenario: Delete confirmation states scope
- **WHEN** 用户准备删除资源
- **THEN** 删除确认保留引用阻塞与取消默认焦点，说明仅保存时删除 YAML、Excel 和产物保留，不提供嵌套完整计划预览

#### Scenario: Discard draft requires confirmation
- **WHEN** 用户点击放弃草稿
- **THEN** 显示按净变化资源数描述的小号确认弹窗，取消不改变草稿；仅有历史时说明清除编辑历史，确认后清空历史
