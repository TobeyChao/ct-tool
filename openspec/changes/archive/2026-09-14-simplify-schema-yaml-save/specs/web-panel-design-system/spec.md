## MODIFIED Requirements

### Requirement: Consistent actions and motion
每个可见工作区 SHALL 最多有一个实心 primary action；危险操作不得使用 primary 样式；动效 SHALL 只表达 180-200ms 状态切换或轻量反馈，并尊重 reduced motion。

#### Scenario: Schema draft has blocking issues
- **WHEN** Schema 候选存在已知结构阻塞项
- **THEN** 「保存变更」禁用且附近说明原因，破坏性「放弃草稿」使用非 primary 危险样式

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

## REMOVED Requirements

### Requirement: Change plan review dialog
**Reason**: YAML 保存不需要持久化全产物计划或强制审查弹窗。
**Migration**: 使用草稿净差异摘要和直接保存，保留删除/放弃确认及持续错误反馈，移除两小时有效期和嵌套计划预览。

## ADDED Requirements

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
