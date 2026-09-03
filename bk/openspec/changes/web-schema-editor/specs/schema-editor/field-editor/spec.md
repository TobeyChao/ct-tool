## Purpose

字段编辑器需求全集：定义字段行的类型胶囊 + pick 模态、状态 tags、类型表达式语言、inline edit 与空名占位等交互契约，与类型库、web 编辑器共同构成结构化编辑体验。

## ADDED Requirements

### Requirement: 字段行布局与对齐

字段行 SHALL 为「类型胶囊（固定宽）｜字段名｜状态 tags｜操作按钮（右对齐）」结构：类型胶囊 = 固定宽度类型名 + pick 按钮（✎）一组整体；类型胶囊固定宽，每行同位全对齐；字段名左边缘 SHALL 全行一致（含 Id/CodeName 锁定行）；操作按钮（↑↓⚙✕）统一右对齐。

#### Scenario: 类型列与字段名列对齐
- **WHEN** 编辑包含不同类型（int32 / Rarity / int32[] / DropRange[]）的字段表
- **THEN** 所有字段行的类型胶囊左边缘一致、字段名左边缘一致，无参差

#### Scenario: 类型切换
- **WHEN** 点击类型胶囊的 pick 按钮
- **THEN** 打开类型选择模态，当前类型高亮，切换后胶囊即时更新

### Requirement: 类型 pick 模态

类型选择模态 SHALL 分组展示：基础类型（6 个固定网格）与类型库（可滚动列表，条目含类型名 + kind 标 + 注释（截断省略）+ 模块）；支持搜索过滤（含模块名匹配）与模块筛选（全部/common/ui…）。打开时 SHALL 默认选中当前类型并高亮（基础类型 chip 高亮靠 `.chip.active`，具名类型行靠 `.fe-row.active`），footer 显示「将设为：当前选择」。**类型库数据 SHALL 按需加载**：从 schema/类型编辑直接打开（未先访问「类型库」页签）时自动补载 `/api/types` 与 `/api/types/modules`，不得因类型库未加载而空列表。「标记为数组类型」开关 SHALL 与选中类型联动：勾选后当前类型直接变为数组表达式（`元素[]`），无独立元素选择器；数组元素为具名 struct 时字段长度模式强制定长。最近使用列表为设计稿体验项，**暂未落地（待决策，见 design.md Open Questions）**。

#### Scenario: 搜索与模块筛选
- **WHEN** 在类型 pick 模态输入关键词或选择模块
- **THEN** 列表按搜索词与模块过滤，无结果时显示「未找到匹配的类型（关键词 · 模块）」空态

#### Scenario: 默认选中当前类型
- **WHEN** 打开类型 pick 模态（字段当前为具名类型如 ItemRarity 或基础类型如 float）
- **THEN** 对应具名类型行或基础类型 chip 处于选中高亮态，footer 显示「将设为：当前类型」

#### Scenario: 类型库未加载直接打开
- **WHEN** 全新会话未访问「类型库」页签，直接从编辑表点字段 ✎ 打开 pick
- **THEN** 类型库列表按需加载并正常显示（不因未预加载而空白）

#### Scenario: 标记数组
- **WHEN** 选中类型 DropRange 并勾选「标记为数组类型」
- **THEN** 胶囊显示 `DropRange[]`，若该字段是 vector 则长度模式强制为定长

### Requirement: 类型表达式语言

字段类型 SHALL 以统一表达式呈现并与 Excel 表头注解一致：基本类型（int32/string…）、具名类型（Rarity/DropRange，accent 强调且类型名即 link 可查看类型定义）、数组（`int32[]` / `DropRange[]`，C# 数组语法）。ref 字段的 Excel 表头注解为 `ref:ItemType`，enum 为类型名，vector 为 `元素[]`。

#### Scenario: 表达式与表头一致
- **WHEN** 字段 Tags 类型为 int32 数组、字段 Rarity 引用具名类型
- **THEN** 编辑器胶囊显示 `int32[]` / `Rarity`，生成表头注解同为 `int32[]` / `Rarity`

#### Scenario: 引用类型只读
- **WHEN** 字段引用具名类型（enum/struct）
- **THEN** 字段行只提供查看入口（类型名 link），内联新建/编辑类型不出现——新建/编辑入口在类型库页签（R8.4 的「+ 新建/编辑↗」不在字段行）

### Requirement: 状态 tags（只读镜像）

字段行 SHALL 在字段名后显示只读状态 tags：🔒主键（gold）、🔒CodeName（accent）、🌐i18n、🖥server_only、🗂按品类（group_key）、🔗ref 表名；属性类 tag SHALL 由字段详情区（⚙ 展开）的 checkbox / ref 下拉状态驱动显隐（只显示已开启项），tag 本身不可交互。i18n ⇄ server_only SHALL 互斥（勾一个自动禁用另一个）；i18n 仅 string 可标记（类型非 string 时禁用置灰）。

#### Scenario: tag 显隐联动
- **WHEN** 策划在 ⚙ 展开区勾选 server_only 或取消 i18n
- **THEN** 行级对应 tag 即时出现/消失，互斥约束同步生效

### Requirement: 字段详情展开区

⚙ 展开「字段详情」SHALL 统一展示：类型专属结构（enum/struct 引用只读预览（chips/子字段 + 查看类型入口）、vector 元素 + 长度模式（变长/定长，元素为具名 struct 时定长强制，定长输入 SHALL 为正整数）、通用属性行（i18n / server_only / 按品类查询 / ref 表名下拉 / 注释输入）。`separator` SHALL 不展示、不可编辑（固定隐藏，默认 ","）。

#### Scenario: struct 引用只读预览
- **WHEN** 展开引用类型字段（如 Rarity）的详情
- **THEN** 显示引用类型的值/子字段只读预览与类型查看入口，无内联编辑（编辑在类型库）

#### Scenario: vector 定长校验
- **WHEN** vector 字段选择定长模式并输入非正整数
- **THEN** 保存被阻止并提示定长须为正整数

#### Scenario: separator 不展示
- **WHEN** 查看 vector 字段详情
- **THEN** 界面不出现 separator 输入项（固定隐藏）

### Requirement: 字段名 inline edit 与空名占位

普通字段名 SHALL 点击即编辑（输入框，失焦/回车保存），Id/CodeName 锁定不可编辑；提交空名 SHALL 显示「未命名字段」灰色占位并保持可点击（可再次进入编辑，不丢失编辑入口），同时该行标为校验错误。

#### Scenario: 空名后再编辑
- **WHEN** 新增字段后未填名字失焦，稍后点击占位
- **THEN** 重新进入编辑态，可补填字段名

### Requirement: 类型模态导航栈（纯 Vue 响应式）

类型查看/编辑模态 SHALL 在嵌套 struct 下钻时使用单模态内导航栈 + 面包屑（每层独立 view/edit/create 模式，编辑态下钻返回后保持）；「取消」在非底层只回退一层（链保留、父层编辑态不丢），**单层编辑态下取消与保存都回到该类型的只读查看态（重载最新）**，查看态才可关闭；「保存类型」保存当前层后按上述规则回退，create（新建）保存后关闭。导航栈 SHALL 完全由 Vue 响应式状态驱动（`typeNav.routes[]+index` 单一数据源 + `typeSnapshots` 草稿快照），**不写浏览器历史、不监听 popstate**（2026-08-31 修订，弃用 History 状态机：popstate 与响应式叠加在多态来回跳转时触发死循环）。模态 SHALL 无右上角 ✕ 按钮，关闭/取消统一在 footer（view 态 `[关闭, 编辑]`、edit 态 `[取消, 保存类型]`），Esc 走 `closeTopModal` 统一关闭。

#### Scenario: 嵌套下钻与取消
- **WHEN** 编辑 DropRange 时下钻查看嵌套类型 DamageRange，然后点取消
- **THEN** 回到 DropRange 编辑态且链保留；再次下钻截断旧前进分支

#### Scenario: 单层编辑保存/取消回只读查看
- **WHEN** 从类型库查看态进入编辑，然后点「取消」或「保存类型」
- **THEN** 回到该类型的只读查看态并重载最新数据（模态不关闭）

#### Scenario: 关闭后 Back 不影响面板
- **WHEN** 关闭类型模态（footer「关闭」/ Esc）后按浏览器返回键
- **THEN** 模态保持关闭，不重新打开（模态不写浏览器历史，无复活问题）

### Requirement: 模态焦点管理

类型模态 SHALL 管理焦点：打开时移入模态内首个可聚焦元素，下钻进入新层时焦点移入新层（面包屑区或标题），关闭/返回时焦点恢复到触发元素（来源按钮）。编辑器各模态（编辑表/类型/删除确认/类型 pick）SHALL 遵循同一焦点管理。

#### Scenario: 打开聚焦
- **WHEN** 打开类型 pick 模态
- **THEN** 焦点移入搜索框（首个可聚焦元素）

#### Scenario: 关闭恢复焦点
- **WHEN** 关闭类型模态
- **THEN** 焦点恢复到打开前触发的按钮/链接元素

### Requirement: Excel 列规则与表头注解（R9.3 + R9.4）

bool 字段的 Excel 列 SHALL 提供 ✓/✗ 下拉（默认不填 = false，0/1 也识别，`vector<bool>` 同支持）；code_name 列 SHALL 有唯一性校验（COUNTIF 自定义公式，导出时校验重复）；表头注解 SHALL 统一为 `ref:表名` / 具名类型名 / `元素[]`（与编辑器类型表达式一致），bool 注解保持 `bool`（不提示 ✓/✗）。

#### Scenario: bool 列下拉
- **WHEN** 生成含 bool 字段的 Excel 模板
- **THEN** bool 列提供 ✓/✗ 下拉，空填视为 false，0/1 可识别

#### Scenario: code_name 唯一性
- **WHEN** 生成含 CodeName 字段的 Excel 模板或导出
- **THEN** 该列带唯一性校验（COUNTIF），重复值被标出

#### Scenario: 表头注解统一
- **WHEN** 生成含 ref / enum / vector 字段的 Excel 模板
- **THEN** 表头注解为 `ref:表名` / 类型名 / `元素[]`

### Requirement: 编辑器交互与显示约束（R9.5 确认项）

下拉 SHALL 使用自定义浮层下拉（白底圆角卡片、阴影、hover 高亮、选中打勾，与面板风格一致，不用原生系统灰弹出层）；短标签（长度模式/属性名）SHALL 不折行（nowrap）；编辑表模态 SHALL 无「JSON 键」输入框（json_key 默认 `{表名}s`）。

#### Scenario: 自定义下拉
- **WHEN** 策划打开任意类型/引用下拉
- **THEN** 弹出浮层为面板风格自定义菜单，非浏览器原生灰框

#### Scenario: 无 JSON 键输入
- **WHEN** 打开编辑表模态
- **THEN** 元信息区只有表名，无 JSON 键输入框

### Requirement: 空态与设计语言一致性

编辑器各列表 SHALL 提供空态（表格列表/类型库列表/类型 pick 搜索无结果），空态与列表形态同构并提供行动引导。新增组件样式 SHALL 与既有 web 面板公共类逐字对齐（切页不跳变）；交互控件 SHALL 具备键盘焦点可见环（`:focus-visible`）与按压反馈（`:active`），模态显示 SHALL 有轻量过渡并在 `prefers-reduced-motion` 下禁用。

#### Scenario: 焦点可见
- **WHEN** 使用键盘 Tab 导航到图标按钮或列表行
- **THEN** 聚焦元素显示可见焦点环，鼠标操作不显示

#### Scenario: 空态引导
- **WHEN** 类型库无任何类型
- **THEN** 类型库页签显示「暂无类型」与「新建类型」引导按钮
