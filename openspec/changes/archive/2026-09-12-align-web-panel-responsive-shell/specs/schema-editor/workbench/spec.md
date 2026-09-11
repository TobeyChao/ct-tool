## REMOVED Requirements

### Requirement: Adaptive 3/2/1 pane projection
**Reason**: 三档渐进投影（wide/medium/compact/phone）与「<600px 模块导航移到底部」被原型定稿的 900/740 两断点抽屉模型取代（900 一刀切，无底部导航）。
**Migration**: 由下方 ADDED「Adaptive pane projection」承接全部行为；状态保持与无横向滚动约束在新需求中保留。

## ADDED Requirements

### Requirement: Adaptive pane projection
工作台 SHALL 按两断点投影：`>=900px` 资源与属性 pane 以可折叠列停靠，且**默认折叠**（首屏编辑器满宽，经编辑器头部「资源面板」按钮与属性活动 Tab 手动开合）；`<900px` 资源与属性 pane 一律变为抽屉 overlay（完整 pane 滑出 + backdrop + 关闭即 inert），不使用页面栈与浏览器历史导航。壳层侧栏在 `>=740px` 常驻、`<740px` 变为汉堡抽屉并出现窄屏顶栏（汉堡 + 品牌标记 + 工作区根目录名）。窗口 resize 跨断点 SHALL 只收不展：`>=900px` 收窄到 `<900px` 时收起资源与属性 pane，`>=1200px` 收窄到 `900-1199px` 时收起属性 pane，`<740px` 放宽到 `>=740px` 时关闭侧栏抽屉；任何方向变化都不得自动展开 pane。Esc 关闭顺序 SHALL 为 dialog > 侧栏抽屉 > 面板抽屉 > 列菜单。布局变化 SHALL 不重置资源选择、页签、字段选择和草稿，且不产生页面级横向滚动。

#### Scenario: Narrow from docked to drawer
- **WHEN** 用户正在编辑 `Item.Rewards` 属性且视口从 1000px 收窄到 800px
- **THEN** 资源与属性 pane 变为抽屉，资源、页签、字段选择和草稿保持不变且不存在页面级横向滚动

#### Scenario: Widen restores docking without reset
- **WHEN** 属性抽屉处于打开状态且视口放宽到 1000px
- **THEN** 资源区选中 Item、主区选中 Rewards、属性 pane 回到可折叠停靠态且保持关闭，不回到首页

#### Scenario: Crossing breakpoints collapses without reopening
- **WHEN** 资源与属性 pane 均展开且视口从 1400px 收窄到 800px 再放宽回 1400px
- **THEN** 收窄时两个 pane 收起为抽屉态，放宽时不自动恢复展开，均由用户手动打开

#### Scenario: Escape unwinds layers in order
- **WHEN** 属性抽屉、侧栏抽屉与列菜单同时打开且用户连按 Esc
- **THEN** 依次关闭列菜单 → 面板抽屉 → 侧栏抽屉，每层关闭后焦点回到该层触发点

## MODIFIED Requirements

### Requirement: Schema workbench resource editing
Schema 工作台 SHALL 在同一工作区中提供 Tables、Records、Enums 三类资源导航；Table 与 Record 使用字段结构编辑器，Enum 使用值编辑器；命名类型与 ref 引用链接（`Table.Field` 形式）跳转 SHALL 复用主编辑区而不是叠加编辑模态。

#### Scenario: Navigate to named record definition
- **WHEN** 用户点击 `vector<DropReward>` 中的 `DropReward`
- **THEN** 主编辑区打开 DropReward 定义，导航历史保留来源字段且 Workspace Draft 不变

#### Scenario: Jump to referenced table from a ref link
- **WHEN** 用户点击字段表中 `ItemType.Id` 引用链接
- **THEN** 主编辑区打开 ItemType，资源树选中并滚动到 ItemType，Workspace Draft 不变

#### Scenario: Edit enum resource
- **WHEN** 用户从 Enums 分组打开 ItemRarity
- **THEN** 主编辑区显示枚举值、wire type、引用数量与草稿状态，不显示 Table 专属查询索引

### Requirement: Global resource Quick Open
工作台 SHALL 提供 `Cmd/Ctrl+P` Quick Open，在任意模块全局可用且不依赖资源 pane 是否可见；空查询显示最近打开资源，输入后使用统一 fuzzy scorer 搜索所有 Table、Record、Enum，并以类型和上下文消歧同名结果；打开结果时若当前不在 Schema 模块 SHALL 自动切换到 Schema 模块。

#### Scenario: Open a recent resource
- **WHEN** 用户打开 Quick Open 但未输入查询
- **THEN** 系统按最近使用顺序展示资源，用户可用键盘选择并打开

#### Scenario: Open from another module
- **WHEN** 用户在导出模块按 `Cmd/Ctrl+P`、选择目标资源并按 Enter
- **THEN** 应用切换到 Schema 模块并打开该资源，调色板关闭且焦点落在新资源标题

#### Scenario: Search all resources while resource pane is closed
- **WHEN** 资源 pane 收起且用户通过 Quick Open 搜索 `reward`
- **THEN** 系统返回全工作区匹配资源并高亮命中，打开结果不强制展开资源 pane

#### Scenario: Escape clears query before closing
- **WHEN** 调色板内有搜索词且用户按 Esc
- **THEN** 第一次按 Esc 清空搜索词并恢复列表，再按 Esc 关闭调色板并还焦触发元素

### Requirement: Side area interaction states
左右辅助区（资源 pane、属性 pane）SHALL 支持停靠与抽屉两种呈现：`>=900px` 以可折叠列停靠且默认折叠，编辑器头部「资源面板」按钮与属性活动 Tab 同时作为收起和恢复入口（IDE 式激活态：展开时入口高亮；收起即 `inert`，恢复回到最近上下文）；`<900px` 呈现为抽屉 overlay，打开时主内容加 `inert`，关闭后焦点回到触发点。隐藏 SHALL 只用 transform 滑出 + `inert`/`aria-hidden`，不得用透明度或负位移，同一 pane 不得叠加多种隐藏机制。

#### Scenario: Toggle the active inspector tab
- **WHEN** 桌面宽度下用户点击已激活的右侧属性活动 Tab
- **THEN** 属性 pane 收起且活动 Tab 保留，字段表获得满宽，收起的 pane 不可 Tab 到达；再次点击恢复最近字段上下文

#### Scenario: Drawer overlay on narrow width
- **WHEN** 视口 `<900px` 且用户打开属性抽屉（属性活动 Tab 或模块头「属性」按钮）
- **THEN** 属性 pane 以 overlay 抽屉呈现并带 backdrop，主内容 inert；Esc、backdrop 点击或关闭按钮关闭后焦点回到触发点

#### Scenario: Reduced motion
- **WHEN** 系统启用 `prefers-reduced-motion`
- **THEN** pane 切换即时完成，不播放轨道动画，并同步更新 `inert`、`aria-hidden` 与焦点

### Requirement: Stable table layout and small-screen representation
字段表头与字段行 SHALL 共享同一列定义和滚动容器：`>=900px` 字段表保持表格形态（最小宽度触发容器内横向滚动，右缘以滚动光晕提示），操作列固定宽度不被滚出；`<900px` 字段列表 SHALL 转为字段卡片分组（表头隐藏，每字段按名称+操作、类型+操作、Excel 表达、角色与约束分区展示），操作保持常显可达；查询索引、依赖矩阵和代码 diff SHALL 在自身容器内滚动。

#### Scenario: Resize a desktop field table
- **WHEN** 用户连续调整窗口或检查器宽度
- **THEN** 字段表头与数据单元格始终对齐，横向滚动只发生在同一个表格容器

#### Scenario: Render fields on phone
- **WHEN** 视口为 390×844
- **THEN** 每个字段以名称与操作、类型、Excel 表达、角色约束分区的卡片呈现，操作始终可见可达，不出现页面级横向滚动
