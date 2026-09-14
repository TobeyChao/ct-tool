# schema-editor/workbench Specification

## Purpose
定义 Schema Editor  在桌面、窄窗口和移动端中的资源浏览、结构化编辑、快速查找、工具区切换与状态保持行为，使大规模 Schema 工作区仍可预测、可访问且不会因布局变化丢失上下文。

## Requirements

### Requirement: Schema workbench resource editing
Schema 工作台 SHALL 在同一工作区提供 Tables、Records、Enums 三类资源导航；Table 与 Record 使用字段结构编辑器，Enum 使用值编辑器；Enum item SHALL 显示不可编辑的当前 ordinal、可编辑 name 与 comment，并支持追加、重命名、删除和显式重排；可能改变数据或 wire ordinal 的操作 SHALL 在保存前的净差异摘要中呈现风险。命名类型与 ref 引用链接（`Table.Field` 形式）跳转 SHALL 复用主编辑区而不是叠加编辑模态。

#### Scenario: Navigate to named record definition
- **WHEN** 用户点击 `vector<DropReward>` 中的 DropReward
- **THEN** 主编辑区打开 DropReward 定义，导航历史保留来源字段且 Workspace Draft 不变

#### Scenario: Jump to referenced table from a ref link
- **WHEN** 用户点击字段表中 `ItemType.Id` 引用链接
- **THEN** 主编辑区打开 ItemType，资源树选中并滚动到 ItemType，Workspace Draft 不变

#### Scenario: Edit enum resource
- **WHEN** 用户从 Enums 分组打开 ItemRarity
- **THEN** 主编辑区显示枚举值、wire type、引用数量与草稿状态，不显示 Table 专属查询索引

#### Scenario: Reorder Enum items shows wire risk
- **WHEN** 用户拖动或命令式重排 Enum item
- **THEN** 工作台在保存前显示所有受影响 item 的旧/新 ordinal

#### Scenario: Add Enum item defaults to append
- **WHEN** 用户新增 Enum item
- **THEN** 新项默认追加到列表尾部并获得下一个 ordinal

#### Scenario: Rename Enum item is explicit
- **WHEN** 用户修改已有 Enum item 的 name 并确认重命名
- **THEN** Draft 记录包含 oldName、newName 与 originalOrdinal 的显式 rename 命令，净差异摘要按最终身份显示生成 API 名称影响，而不是推断为删除后新增

### Requirement: Local resource filtering
资源区 SHALL 支持名称 fuzzy 过滤、命中字符高亮、分组匹配计数、空结果反馈和完整键盘操作；搜索期间 SHALL 临时展示所有存在命中的分组，清空后恢复用户原有折叠状态。

#### Scenario: Filter resources inside collapsed groups
- **WHEN** Records 分组原本折叠且用户输入可匹配 `DropReward` 的查询
- **THEN** Records 临时显示匹配项并显示匹配数，清空查询后恢复折叠状态

#### Scenario: Navigate filtered results by keyboard
- **WHEN** 搜索框有多个匹配项且用户按 Up/Down 后按 Enter
- **THEN** 焦点在可见结果间移动，Enter 打开当前结果，Esc 先清空查询再退出搜索

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

### Requirement: Workbench accessibility and verification matrix
工作台 SHALL 提供可见焦点、语义标签、合理焦点恢复和隐藏页面不可聚焦保证，并 SHALL 在规定尺寸与缩放矩阵完成浏览器验收。

#### Scenario: Close temporary resource selector
- **WHEN** 中屏资源选择层通过 Esc 或选择资源关闭
- **THEN** 焦点回到打开入口或新打开资源标题，关闭层不占位、不露边且不可 Tab 到达

#### Scenario: Required viewport verification
- **WHEN** 执行发布前界面验收
- **THEN** 覆盖 1600×900、1360×768、1280×720、960×640、720×460、390×844 及 100%/125%/150% 缩放，并验证无错位、遮挡和状态重置

### Requirement: Add-field role and constraint mutual exclusion
添加字段流程 SHALL 依据真实 schema 功能联动「角色」「约束」与「类型修饰」，禁止产出非法或客户端不可用的字段配置；主键字段 `Id` 为固定必有不通过添加字段指派，代号字段 `CodeName` 为可选固定名字段，`vector` 为可选类型修饰符；变长 scalar/Enum/string vector 使用内置 `[...]` 逗号文法且不提供 separator，定长形态使用 `excel_columns` 表示最大槽位数，Record vector 仅允许定长展开，ref 不允许 vector；无真实语义的约束只作信息提示，不进入草稿命令。

#### Scenario: Primary key field is fixed and not offered in add-field
- **WHEN** 用户打开添加字段流程
- **THEN** 不提供「主键」指派（主键是固定字段 `Id`，由表定义与固定字段编辑维护；其类型 `int32`、非 `i18n`、非 `server_only` 由模型校验保障——主键在索引向量、`idHash` 与生成的 `ByID(int)` 上均以 32 位承载，故除 `int32` 外的整数标量在保存时同样被模型拒绝）

#### Scenario: I18N role restricted to string type
- **WHEN** 角色选择 I18N 后选择非 `string` 类型（含勾选 vector）
- **THEN** 类型选择对 I18N 角色仅允许 `string`，或提交时给出校验错误

#### Scenario: Codename (CodeName) is optional with a fixed name and role
- **WHEN** 用户选择添加代号字段
- **THEN** 弹窗固定字段名为 `CodeName`、类型为 `string`、角色仅为「无」（非 `i18n`、非 `server_only`）；一表至多一个 `CodeName`，已存在时阻止并提示
- **AND WHEN** 用户为该表声明 codename 索引
- **THEN** 提示「CodeName 索引要求：非空 · 表内唯一 · 非 i18n string」；该约束只作用于**声明了索引的表**，未声明索引时 `CodeName` 是可选、可重复的普通字段

#### Scenario: Vector is a modifier with built-in separator
- **WHEN** 用户勾选「vector」修饰符
- **THEN** 基础类型字段保持所选 T（标量 / Enum / Record），提交类型为 `vector<${T}>`；形态可选择「定长」或「变长」
- **AND WHEN** 基础类型 T 为 Record
- **THEN** 形态仅允许「定长」（变长禁用），并需配置展开组数 `excel_columns`
- **AND WHEN** 基础类型 T 为标量 / Enum / string
- **THEN** 可选择单格变长录入或固定列数录入；变长使用内置分隔符，定长配置 `excel_columns`；两者运行时都生成普通变长 vector
- **AND WHEN** 基础类型 T 为 ref 外键
- **THEN** 不支持勾选 vector

#### Scenario: Fixed vector explains maximum slots
- **WHEN** 用户选择定长 vector 并填写 N
- **THEN** 提交 `excel_columns: N` 且 UI 明确 N 是最大槽位数、末尾空槽位不计入长度

#### Scenario: Record and reference vector constraints
- **WHEN** 基础类型是 Record 或 ref
- **THEN** Record vector 只允许配置 excel_columns 的展开形态，ref 禁止 vector

#### Scenario: Informational constraints only
- **WHEN** 字段涉及工具强制的约束（ref 外键有效性、声明了 codename 索引的表的 `CodeName` 非空唯一等）
- **THEN** 弹窗以只读提示呈现，不提供无真实语义的勾选（如「必填」、可配置分隔符），且提示不进入草稿命令

### Requirement: Create Schema resources from the workbench
工作台 SHALL 提供「新增 Schema」入口及 Table、Record、Enum 类型选择，资源分组入口 SHALL 预选对应类型；入口 SHALL 在资源面板折叠、空分组和已配置但没有任何资源的工作区可用。创建表单 SHALL 支持名称、注释和类型对应的最小合法内容，遵守既有键盘、焦点恢复及窄屏交互规范。

#### Scenario: Create from an empty workspace
- **WHEN** 已配置工作区无任何 Schema 且用户选择新增 Table
- **THEN** 可完成表单并进入新 Table 编辑器，无须先手写 YAML 或打开已有资源

#### Scenario: Create while resource pane is collapsed
- **WHEN** 资源面板折叠且用户用键盘打开新增入口
- **THEN** 可选择三类资源；取消后焦点回到入口，成功后焦点进入新资源标题，390px 窄屏没有页面横向溢出

### Requirement: Kind-specific creation forms
Table 创建 SHALL 自动包含固定 `primary: Id` 和 `Id: int32`，不自动添加 CodeName 或索引；Record SHALL 至少填写一个合法字段，不能隐式添加主键；Enum SHALL 至少填写一个具名项并支持 comment，ordinal 从 0 按输入顺序派生。空名称、不合法名称、重复名称、空 Record/Enum SHALL 阻止创建并保留输入，校验不得通过静默改名修复。

#### Scenario: Minimal Table
- **WHEN** 用户以合法名称 Item 完成 Table 创建
- **THEN** 草稿 Table 包含 Id 主键，Excel 文件和 JSON key 使用既有默认规则，用户可继续添加普通字段和查询索引

#### Scenario: Minimal Record
- **WHEN** 用户创建 DropReward 并填写首个字段 Min、类型 int32
- **THEN** 草稿 Record 包含 Min 且不包含自动生成的 Id；未填写首字段时不能提交

#### Scenario: Minimal Enum
- **WHEN** 用户创建 ItemRarity 并填写首项 Common、注释「普通」
- **THEN** 草稿 Enum 显示 Common 的 ordinal 为 0，继续追加值沿用现有编辑器行为；空项和重复项被拒绝

#### Scenario: Existing resource name collision
- **WHEN** 用户以现有或当前草稿资源的名称创建任意类别资源
- **THEN** 表单显示名称冲突且不增加命令，不因类别不同而允许重名

### Requirement: Newly created resources participate in draft navigation
创建成功 SHALL 仅加入草稿，自动选中新资源并标记未保存；资源列表、计数、过滤、Quick Open、类型选择和 ref 选择 SHALL 反映当前撤销光标下的候选资源。Record/Enum SHALL 可被当前草稿的字段引用，Table SHALL 仅作为合法 ref 目标而非具名字段类型。取消表单 SHALL 不改变草稿。

#### Scenario: Build three related resources without saving between them
- **WHEN** 用户依次创建 ItemRarity、引用它的 DropReward、引用 DropReward 的 Item
- **THEN** 每次创建后后续类型选择均能找到新类型，三者可在同一草稿中编辑和保存

#### Scenario: Undo selected resource creation
- **WHEN** 用户撤销当前选中资源的创建
- **THEN** 资源从所有候选列表消失，主区回到有效资源或空状态而不保留失效详情；重做可恢复资源

### Requirement: Explicit post-save Table workflow
新 Table 保存成功后 SHALL 展示真实模板状态，缺失时提供针对该表的显式生成模板操作；尚未保存时 SHALL 提示先保存且不能向模板操作传入未落盘资源。保存 SHALL 不自动生成 Excel 或导出产物。Record/Enum SHALL 不提供独立 Excel 模板操作。

#### Scenario: Save then generate and export
- **WHEN** 用户保存包含新 Table 的草稿，再显式生成模板、填写合法数据、执行校验及导出
- **THEN** 模板包含新字段布局，校验成功，JSON、FBS、Binary 与 C#/Lua Accessor 按当前配置包含新表及其引用类型

#### Scenario: Existing workbook at the new Table path
- **WHEN** 新 Table 对应路径已有 Excel 且用户显式生成模板
- **THEN** 使用既有无损预检，不能证明数据可保留时拒绝覆盖并显示问题，已保存 YAML 与原工作簿保持不变

#### Scenario: Template generation fails after save
- **WHEN** YAML 已保存而显式模板生成失败
- **THEN** 界面分别显示保存成功与模板生成失败，可重试模板操作，不把 YAML 保存标记为失败或恢复已保存草稿
