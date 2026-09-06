## ADDED Requirements

### Requirement: Dialog variant contract
共享 Dialog SHALL 提供 danger 确认、表单、选择器和调色板四种变体，并复用同一模态骨架：焦点陷阱、Escape 关闭最上层、关闭后还焦触发元素、背景应用 inert。宽度变体 SHALL 为：标准 `min(560px, 100vw-40px)`、小号 `min(420px, 92vw)`、变更计划 `min(640px, 100vw-40px)`、快速打开调色板 `min(480px, 92vw)`。初始焦点 SHALL 遵循：danger 确认 → 取消按钮，表单 → 第一个输入框，picker → 搜索框。危险操作主按钮 SHALL 使用独立 danger 语义色，且不得只靠颜色传达（配按钮文案）。

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

### Requirement: Implicit workspace draft surfacing
Schema 编辑 SHALL 不提供「加入草稿」显式用户步骤：删除/添加等命令点击即进入 Workspace Draft。草稿表面 SHALL 为编辑器页底常驻状态条：未应用命令数 + 撤销/重做 + 「审查并应用」主操作；无命令时状态条不显示。草稿持久化失败 SHALL 在状态条上持续显示可处理的警告（不只 Toast），内存草稿仍可用。

#### Scenario: Delete lands in draft
- **WHEN** 用户在确认弹窗点击「删除」
- **THEN** 命令立即进入草稿，状态条显示「1 条未应用变更」，文件与导出产物未被修改

#### Scenario: Persistence failure warning persists
- **WHEN** IndexedDB 写入草稿失败
- **THEN** 状态条持续显示「草稿未持久化」警告，编辑继续保留在内存

### Requirement: Change plan review dialog
「审查并应用」SHALL 打开变更计划弹窗：风险徽标（安全/数据依赖/破坏/不兼容/依赖破坏）+ 按影响的产物清单（Schema/Excel/FBS/Binary/Accessor · 表 · 动作）+ 阻塞项列表（含位置与样例值）。存在阻塞项 SHALL 禁用应用按钮。应用成功后弹窗关闭、草稿清空、状态条消失，并原位（编辑器内）显示已应用摘要。

#### Scenario: Blocked plan cannot apply
- **WHEN** 变更计划存在数据破坏或依赖破坏阻塞项
- **THEN** 应用按钮禁用，阻塞项列出位置与样例值

#### Scenario: Successful apply resets draft
- **WHEN** 计划无阻塞且应用成功
- **THEN** 弹窗关闭、状态条消失，编辑器内显示「已应用」摘要，撤销栈清空

#### Scenario: Discard draft requires confirmation
- **WHEN** 用户在变更计划弹窗点击「放弃草稿」
- **THEN** 打开小号确认弹窗「放弃 N 条未应用变更？此操作不可撤销」，初始焦点在「取消」；确认后命令清空、状态条消失；取消则不改变草稿

### Requirement: Quick-open palette
Schema 模块 SHALL 提供快速打开调色板，由编辑器头部按钮与全局 `Cmd/Ctrl+P` 触发：搜索所有 Table/Record/Enum，输入即时过滤；↑/↓ 移动高亮、Enter 打开（关闭并导航到资源）、Escape 先清空搜索词再关闭；点击行打开；无匹配显示空态；关闭后焦点还给触发按钮。

#### Scenario: Keyboard navigation opens resource
- **WHEN** 用户按 Cmd+P、输入「Item」、↓ 选择目标行并按 Enter
- **THEN** 调色板关闭，编辑器标题与资源树选中切换为该资源

#### Scenario: Escape clears query before closing
- **WHEN** 调色板内有搜索词时按 Escape 两次
- **THEN** 第一次清空搜索词恢复全量列表，第二次关闭调色板并还焦触发按钮

### Requirement: i18n table picker
翻译工具栏「选择表」SHALL 打开表选择器：搜索过滤 + 状态筛选 pill（全部/有缺失/有待审/已译完）+ 结果计数 + 每行表名/字段数/i18n 数/状态徽标；点选行关闭并回填当前表；无匹配显示空态。

#### Scenario: Pick a table returns selection
- **WHEN** 用户在表选择器中点击 Quest 行
- **THEN** 选择器关闭，工具栏「选择表」值更新为 Quest，翻译表随之切换

### Requirement: External documentation link
侧栏「导出文档」SHALL 直接打开外部文档页，不弹窗；入口在静态原型中标记为外部链接（`title="外部文档"`）。

#### Scenario: Documentation opens externally
- **WHEN** 用户点击侧栏「导出文档」
- **THEN** 新开外部文档页，应用内不出现浮层或弹窗
