## Purpose

定义原生桌面翻译页在多行文本、中文输入法、长文本对照与显式保存场景下的编辑契约，使翻译人员可以稳定地逐条查看、修改和确认译文。

## ADDED Requirements

### Requirement: Focused translation entry editor

原生翻译页 SHALL 保留表、语言、状态筛选、列显隐和分页能力，并 SHALL 允许用户选择一个译文条目进入专注编辑。专注编辑 SHALL 展示条目键、表与语言、只读原文和可编辑译文；原文 SHALL 可选中并保留换行，译文 SHALL 支持多行输入和滚动查看。切换表或语言时 SHALL 清除不再属于当前结果集的选中条目和未提交草稿，不得把旧表或旧语言的草稿写入新上下文。

#### Scenario: Select an entry for focused editing
- **WHEN** 用户在翻译表中选择一个条目
- **THEN** 页面展示该条目的键、表、语言、只读原文和可编辑译文，后续文本修改进入该条目的草稿

#### Scenario: Change table while an entry is selected
- **WHEN** 用户在存在选中条目时切换表或语言
- **THEN** 页面清除旧选中条目与未提交草稿，并使用新上下文加载条目列表

### Requirement: Multiline translation editing

译文编辑器 SHALL 把换行作为普通文本内容处理：`Enter` 和 `Shift+Enter` SHALL 插入换行，SHALL NOT 触发保存、确认或跳到下一条。多行文本在编辑、取消、保存和重新加载后 SHALL 保持原有换行，不得被截断、合并或丢弃。

#### Scenario: Enter inserts a newline
- **WHEN** 用户在专注编辑器中按 `Enter` 或 `Shift+Enter`
- **THEN** 光标处插入换行，不发送 `i18n.save`

#### Scenario: Existing multiline text round-trips
- **WHEN** 一个条目的原文或译文包含多行文本
- **THEN** 专注编辑器完整显示这些行，保存后再次读取仍保持相同换行内容

### Requirement: IME-safe translation shortcuts

专注编辑器 SHALL 使用 IME 安全的快捷键语义。输入法正在组合文本时，`Enter`、`Shift+Enter`、`Ctrl/Cmd+Enter` 和 `Esc` SHALL 先交给输入法处理，界面 SHALL NOT 在组合态提交或取消翻译。组合结束后，`Ctrl/Cmd+Enter` SHALL 保存并确认当前条目，`Esc` SHALL 放弃当前草稿并恢复最近一次已保存内容。翻译编辑器 SHALL NOT 抢占全局 `Ctrl/Cmd+S`。

#### Scenario: Composition is not submitted
- **WHEN** 中文输入法仍在组合文本且用户按下 `Ctrl/Cmd+Enter`
- **THEN** 不发送 `i18n.save`，组合文本继续由输入法处理

#### Scenario: Confirmed save shortcut
- **WHEN** 编辑器没有处于组合态且用户按下 `Ctrl/Cmd+Enter`
- **THEN** 当前译文通过单条 `i18n.save` 保存，`confirmed=true`，成功后状态由内核返回值更新

#### Scenario: Cancel shortcut restores saved text
- **WHEN** 用户修改译文后按 `Esc`
- **THEN** 草稿恢复为最近一次已保存的文本，且不发送 `i18n.save`

#### Scenario: Global save shortcut is preserved
- **WHEN** 用户聚焦翻译编辑器并按 `Ctrl/Cmd+S`
- **THEN** 翻译编辑器不处理该快捷键，应用原有 Schema 草稿保存语义保持不变

### Requirement: Explicit focused-editor save

专注编辑器 SHALL 使用显式保存，SHALL NOT 在失焦时自动提交。用户存在未保存草稿时切换条目、表、语言或筛选，界面 SHALL 先提供保存、放弃或取消选择的选择，不得静默丢弃草稿。保存成功 SHALL 更新当前条目的确认位和状态徽标；保存失败 SHALL 保留草稿、选中条目和编辑焦点，不得把状态标记为成功。

#### Scenario: Blur does not submit
- **WHEN** 用户在专注编辑器中修改译文后点击页面其他区域使输入框失焦
- **THEN** 草稿仍保留，未发送 `i18n.save`

#### Scenario: Save failure preserves draft
- **WHEN** `i18n.save` 返回错误
- **THEN** 错误可见，草稿和选中条目保留，状态徽标不显示成功

#### Scenario: Successful save updates state
- **WHEN** `i18n.save` 成功返回
- **THEN** 当前条目使用内核返回的状态更新确认位和状态徽标，筛选结果不得伪造客户端状态

### Requirement: Responsive focused editor layout

专注编辑区 SHALL 根据可用宽度适配：宽窗口 SHALL 让条目导航与编辑区同时可见并使用左右原文/译文对照；较窄窗口 SHALL 使用上下布局或全屏编辑回退。响应式切换 SHALL NOT 丢失当前选择或草稿，关键操作（保存、取消、返回列表）SHALL 始终可达，主区域 SHALL NOT 横向溢出。

#### Scenario: Wide window keeps navigation and editor visible
- **WHEN** 工作台在支持的宽窗口中显示翻译页且用户选中一个条目
- **THEN** 条目导航与专注编辑器同时可见，原文与译文可对照阅读

#### Scenario: Narrow window falls back without losing draft
- **WHEN** 用户缩小窗口到全屏编辑回退尺寸后再放大
- **THEN** 当前选中条目和未保存草稿保留，布局重新适配且主操作可达
