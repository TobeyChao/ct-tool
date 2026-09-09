# schema-editor/workbench Specification

## Purpose
定义 Schema Editor  在桌面、窄窗口和移动端中的资源浏览、结构化编辑、快速查找、工具区切换与状态保持行为，使大规模 Schema 工作区仍可预测、可访问且不会因布局变化丢失上下文。

## Requirements

### Requirement: Schema workbench resource editing
Schema 工作台 SHALL 在同一工作区提供 Tables、Records、Enums 三类资源导航；Table/Record 使用字段编辑器，Enum 使用按序 item 编辑器。Enum item SHALL 显示不可编辑的当前 ordinal、可编辑 name 与 comment，并支持追加、重命名、删除和显式重排；可能改变数据或 wire ordinal 的操作 SHALL 在计划中呈现风险。

#### Scenario: Navigate to named record definition
- **WHEN** 用户点击 `vector<DropReward>` 中的 DropReward
- **THEN** 主编辑区打开 DropReward，导航历史保留来源字段且 Workspace Draft 不变

#### Scenario: Edit enum resource
- **WHEN** 用户编辑 ItemRarity.Rare 的 comment
- **THEN** 草稿只记录注释变化，Rare 的 name、位置和 ordinal 不变

#### Scenario: Reorder Enum items shows wire risk
- **WHEN** 用户拖动或命令式重排 Enum item
- **THEN** 工作台在 Apply 前显示所有受影响 item 的旧/新 ordinal

#### Scenario: Add Enum item defaults to append
- **WHEN** 用户新增 Enum item
- **THEN** 新项默认追加到列表尾部并获得下一个 ordinal

#### Scenario: Rename Enum item is explicit
- **WHEN** 用户修改已有 Enum item 的 name 并确认重命名
- **THEN** Draft 记录包含 oldName、newName 与 originalOrdinal 的显式 rename 命令，Change Plan 显示 Excel 值迁移数量和生成 API 名称影响，而不是推断为删除后新增

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

### Requirement: Add-field role and constraint mutual exclusion
添加字段流程 SHALL 依据 canonical 类型与角色约束产出合法字段。主键 Id 固定存在、Code 为可选固定名、vector 为类型修饰符；变长 scalar/Enum/string vector 使用内置 `[...]` 逗号文法且不提供 separator，定长形态使用 `excel_columns` 表示最大槽位数，Record vector 仅允许定长展开，ref 不允许 vector。

#### Scenario: Primary key field is fixed and not offered in add-field
- **WHEN** 用户打开添加字段流程
- **THEN** 不提供主键指派，Id 的整数类型及角色约束由模型保障

#### Scenario: I18N role restricted to string type
- **WHEN** 角色选择 I18N
- **THEN** 类型仅允许非 vector string，或提交时返回明确校验错误

#### Scenario: Codename (Code) is optional with a fixed name and role
- **WHEN** 用户选择添加 Code 字段
- **THEN** 名称固定 Code、类型固定 string、角色为无，并保障一表至多一个

#### Scenario: Vector is a modifier with built-in separator
- **WHEN** 用户为 scalar、Enum 或 string 勾选 vector 并选择变长
- **THEN** 提交 `vector<T>`、不携带 excel_columns 或 separator，并显示对应 `[...]` 输入示例

#### Scenario: Fixed vector explains maximum slots
- **WHEN** 用户选择定长 vector 并填写 N
- **THEN** 提交 `excel_columns: N` 且 UI 明确 N 是最大槽位数、末尾空槽位不计入长度

#### Scenario: Record and reference vector constraints
- **WHEN** 基础类型是 Record 或 ref
- **THEN** Record vector 只允许配置 excel_columns 的展开形态，ref 禁止 vector

#### Scenario: Informational constraints only
- **WHEN** 字段涉及 ref 有效性或 Code 唯一性等工具强制约束
- **THEN** 弹窗只显示说明，不创建无对应 Schema 语义的开关
