## Purpose

定义 Schema Editor v4 在桌面、窄窗口和移动端中的资源浏览、结构化编辑、快速查找、工具区切换与状态保持行为，使大规模 Schema 工作区仍可预测、可访问且不会因布局变化丢失上下文。

## ADDED Requirements

### Requirement: Schema workbench resource editing
Schema 工作台 SHALL 在同一工作区中提供 Tables、Records、Enums 三类资源导航；Table 与 Record 使用字段结构编辑器，Enum 使用值编辑器，命名类型跳转 SHALL 复用主编辑区而不是叠加编辑模态。

#### Scenario: Navigate to named record definition
- **WHEN** 用户点击 `vector<DropReward>` 中的 `DropReward`
- **THEN** 主编辑区打开 DropReward 定义，导航历史保留来源字段且 Workspace Draft 不变

#### Scenario: Edit enum resource
- **WHEN** 用户从 Enums 分组打开 ItemRarity
- **THEN** 主编辑区显示枚举值、wire type、引用数量与草稿状态，不显示 Table 专属查询索引

### Requirement: Local resource filtering
资源区 SHALL 支持名称 fuzzy 过滤、命中字符高亮、分组匹配计数、空结果反馈和完整键盘操作；搜索期间 SHALL 临时展示所有存在命中的分组，清空后恢复用户原有折叠状态。

#### Scenario: Filter resources inside collapsed groups
- **WHEN** Records 分组原本折叠且用户输入可匹配 `DropReward` 的查询
- **THEN** Records 临时显示匹配项并显示匹配数，清空查询后恢复折叠状态

#### Scenario: Navigate filtered results by keyboard
- **WHEN** 搜索框有多个匹配项且用户按 Up/Down 后按 Enter
- **THEN** 焦点在可见结果间移动，Enter 打开当前结果，Esc 先清空查询再退出搜索

### Requirement: Global resource Quick Open
工作台 SHALL 提供 `Cmd/Ctrl+P` Quick Open，不依赖资源 pane 是否可见；空查询显示最近打开资源，输入后使用统一 fuzzy scorer 搜索所有 Table、Record、Enum，并以类型和上下文消歧同名结果。

#### Scenario: Open a recent resource
- **WHEN** 用户打开 Quick Open 但未输入查询
- **THEN** 系统按最近使用顺序展示资源，用户可用键盘选择并打开

#### Scenario: Search all resources while resource pane is closed
- **WHEN** 资源 pane 收起且用户通过 Quick Open 搜索 `reward`
- **THEN** 系统返回全工作区匹配资源并高亮命中，打开结果不强制展开资源 pane

### Requirement: Adaptive 3/2/1 pane projection
工作台 SHALL 依据 CSS 可用宽度投影为 `wide`、`medium`、`compact`、`phone`：`>=1360px` 显示资源、主区和检查器；`960-1359px` 显示主区与检查器，资源为唯一临时选择层；`<960px` 使用资源→主区→属性页面栈；`<600px` 将模块导航移到底部。

#### Scenario: Narrow from wide to compact
- **WHEN** 用户正在编辑 `Item.Rewards` 属性且视口从 1600px 收窄到 720px
- **THEN** 当前显示最深的属性页面，资源、页签、字段选择和草稿保持不变且不存在页面级横向滚动

#### Scenario: Widen from phone to desktop
- **WHEN** 当前手机路径为 Item 的 Rewards 属性页且视口放宽到 1600px
- **THEN** 资源区选中 Item、主区选中 Rewards、检查器显示 Rewards 属性，不回到首页

### Requirement: Side area interaction states
左右辅助区 SHALL 仅具有 `activeTool` 或无活动工具两态；不得叠加 hidden/collapsed/overlay 状态，也不得用完整 pane 横向移出屏幕。活动 Tab SHALL 同时作为收起和恢复入口，右侧检查器收起后仍保留稳定的 Activity Tab。

#### Scenario: Toggle the active inspector tab
- **WHEN** 用户点击已激活的右侧属性 Tab
- **THEN** 属性内容在 Tab 边界内收起且 Tab 保留；再次点击恢复最近字段上下文

#### Scenario: Reduced motion
- **WHEN** 系统启用 `prefers-reduced-motion`
- **THEN** pane 切换即时完成，不播放轨道动画，并同步更新 `inert`、`aria-hidden` 与焦点

### Requirement: Stable table layout and small-screen representation
字段表头与字段行 SHALL 共享同一列定义和滚动容器；`<960px` 时字段列表 SHALL 转为语义明确的紧凑行分组，而查询索引、依赖矩阵和代码 diff SHALL 在自身容器内滚动。

#### Scenario: Resize a desktop field table
- **WHEN** 用户连续调整窗口或检查器宽度
- **THEN** 字段表头与数据单元格始终对齐，横向滚动只发生在同一个表格容器

#### Scenario: Render fields on phone
- **WHEN** 视口为 390×844
- **THEN** 每个字段以名称和类型首行、角色和变更次行显示，点击进入独立属性页且操作不会被横向滚出屏幕

### Requirement: Workbench accessibility and verification matrix
工作台 SHALL 提供可见焦点、语义标签、合理焦点恢复和隐藏页面不可聚焦保证，并 SHALL 在规定尺寸与缩放矩阵完成浏览器验收。

#### Scenario: Close temporary resource selector
- **WHEN** 中屏资源选择层通过 Esc 或选择资源关闭
- **THEN** 焦点回到打开入口或新打开资源标题，关闭层不占位、不露边且不可 Tab 到达

#### Scenario: Required viewport verification
- **WHEN** 执行发布前界面验收
- **THEN** 覆盖 1600×900、1360×768、1280×720、960×640、720×460、390×844 及 100%/125%/150% 缩放，并验证无错位、遮挡和状态重置
