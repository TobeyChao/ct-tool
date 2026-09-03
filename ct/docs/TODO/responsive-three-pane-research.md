# Schema Editor 跨桌面与移动端三栏适配调研

> 日期：2026-08-31
> 范围：`资源列表 → 主编辑区 → 字段属性/辅助详情` 这一类三层工作流
> 来源规则：只使用官方设计规范、官方文档和开源项目官方仓库/源码。

## 1. 结论先行

当前原型在 `801–1180px` 把资源树和检查器都改成互斥抽屉，这个方向只解决了“放不下”，没有解决三块内容的语义差异。成熟方案更一致的做法是：

1. **资源列表是导航层，主编辑区是内容层，检查器是工具/支持层。** 三者不能因为视觉上都像侧栏，就共用同一种抽屉行为。
2. **宽屏并排、中屏保留最常一起工作的两栏、窄屏改为页面栈。** GNOME `NavigationSplitView`、KDE `PageRow`、Android Material 3 的 list-detail navigator 和 SAP FCL 都在空间不足时把层级内容顺序化，而不是把桌面三栏全部留在画布外等待覆盖。
3. **覆盖层只留给短暂选择或工具面板。** GNOME 明确区分了窄屏下变成导航页栈的 `NavigationSplitView`，以及窄屏下覆盖内容的 `OverlaySplitView`；GitLab 也区分了持久工作区 panel 与短生命周期 drawer。
4. **状态必须独立于当前布局。** 当前资源、字段、页签、草稿和导航历史不能存在“某个可见 DOM 行”里。窗口缩放只是同一状态的不同投影，不能触发选中丢失或回到资源首页。
5. **表格不能统一用一种移动端降级。** 需要跨行比较的数据保留表格并局部横向滚动；每行可以独立理解、且操作不能被藏到视口外的数据改为行分组。GitLab 的表格规范正是按这两类任务决策。

因此，本项目不建议继续修补“左右双抽屉版桌面三栏”。建议改为一个明确的自适应状态机：

```text
宽屏：资源列表 | 主编辑区 | 属性检查器
中屏：主编辑区 | 属性检查器       + 临时资源选择层
窄屏：资源列表 → 主编辑区 → 属性页（页面栈、可返回）
手机：同一页面栈 + 底部模块导航，不保留桌面模块竖栏
```

## 2. 第一方项目与规范证据

### 2.1 GNOME Libadwaita：导航侧栏与工具侧栏必须采用不同降级方式

Libadwaita 是 GNOME 为桌面和移动窗口共同提供的自适应 UI 库。它的官方自适应布局文档提供了两个外观相似、窄屏语义不同的组件：

- `AdwNavigationSplitView` 折叠后变成 `AdwNavigationView`：侧栏是根页面，内容是子页面；激活侧栏项目后进入内容页，标题栏自动提供返回按钮。
- `AdwOverlaySplitView` 折叠后才把侧栏覆盖在内容之上，适合工具侧栏或临时辅助内容。
- 三栏通过嵌套两个 split view 实现。官方例子在 `860sp` 先折叠外层、`500sp` 再折叠内层：只折叠外层时仍可保留两栏；两层都折叠后一次只显示一页。

证据：[Libadwaita Adaptive Layouts：Split Views、Navigation Sidebars、Overlay Sidebars 与 Triple Pane Layouts](https://gnome.pages.gitlab.gnome.org/libadwaita/doc/1.5/adaptive-layouts.html#split-views)，[官方仓库中的同一设计文档](https://github.com/GNOME/libadwaita/blob/main/doc/adaptive-layouts.md)

**可借鉴：**资源树使用 navigation 语义；属性区使用 utility pane 语义；极窄时两者都进入页面层级而不是同时变成覆盖抽屉。

**不直接照搬：**`sp` 阈值和 GTK 控件尺寸不等于 Web 的 CSS px；本项目应按各栏最小可用宽度计算断点。

### 2.2 SAP OpenUI5 FlexibleColumnLayout：成熟的 3/2/1 栏状态机

OpenUI5 的 `FlexibleColumnLayout` 是开源的 list-detail-detail 三栏实现。源码直接规定：

- 浏览器宽度 `≥1280px` 最多显示 3 栏；
- `960–1279px` 最多显示 2 栏；
- `<960px` 最多显示 1 栏；
- 三栏内部各自是导航容器，应用只声明当前 layout/route，由控件根据可用空间决定最大可见栏数；
- 用户调整过的栏宽会按 layout 保存并在再次进入时恢复；SAP Fiori Elements 还会按应用和设备类型保存栏宽个性化设置；
- 路由的 target 是页面数组，同一个 URL 状态可以对应一栏、两栏或三栏展示，而不是为每个断点复制页面。

证据：[OpenUI5 `FlexibleColumnLayout.js` 的三栏、栏宽持久化与响应式说明](https://github.com/SAP/openui5/blob/master/src/sap.f/src/sap/f/FlexibleColumnLayout.js#L69-L103)，[源码中的 1280/960 阈值](https://github.com/SAP/openui5/blob/master/src/sap.f/src/sap/f/FlexibleColumnLayout.js#L220-L248)，[SAP 官方路由与栏宽保存说明](https://github.com/SAP-docs/sapui5/blob/main/docs/06_SAP_Fiori_Elements/enabling-the-flexible-column-layout-e762257.md#saving-column-resize-information)

**可借鉴：**把“当前路径”和“可见栏数”分开；桌面允许拖动栏宽并按布局档位保存；缩窄时保留当前最深工作上下文。

**不直接照搬：**ct 还有约 `56px` 模块栏，检查器也包含较宽表单，因此 3 栏阈值应高于 SAP 的 `1280px`，不能机械复制比例。

### 2.3 Android Material 3 Adaptive：选择、历史和 back 属于导航状态，不属于布局

AndroidX 的 `ThreePaneScaffoldNavigator` 把窗口变化、当前 destination、destination history、`navigateTo()` 和 `navigateBack()` 放在同一个导航器中；窗口配置变化会自动更新 scaffold directive。官方 list-detail 示例把选中项放在 `rememberSaveable` 状态中，点击列表项后导航到 Detail；只有 list 与 detail 同时可见时，列表才展示桌面式持续选中态。

证据：[AndroidX `ThreePaneScaffoldNavigator` 接口与历史感知导航](https://github.com/androidx/androidx/blob/androidx-main/compose/material3/adaptive/adaptive-navigation/src/commonMain/kotlin/androidx/compose/material3/adaptive/navigation/ThreePaneScaffoldNavigator.kt#L51-L132)，[官方 ListDetail 示例的可保存选择、back 与 Detail 导航](https://github.com/android/user-interface-samples/blob/main/CanonicalLayouts/list-detail-compose/app/src/main/java/com/example/listdetailcompose/ui/ListDetailSample.kt#L95-L155)，[Android 官方 list-detail 指南](https://developer.android.com/develop/adaptive-apps/guides/list-detail)

**可借鉴：**资源/字段 ID、导航历史、草稿状态与 pane 是否可见解耦；窄屏返回遵循 `属性 → 字段列表 → 资源列表`，放宽后由同一状态恢复并排。

**不直接照搬：**这是 Compose API，不应把 Android 的组件或 dp 断点移植到 Web；应移植状态模型。

### 2.4 KDE Kirigami：同一个页面模型，有空间时并排、没空间时 push/pop

Kirigami 的官方说明把 `PageRow` 定义为一组可并排的页面：单页可以占满窗口，也可以在空间足够时与其他页同时显示；页面通过 `push()`、`pop()`、`goBack()` 管理。它没有为桌面和移动端维护两套内容组件。

证据：[KDE Kirigami：Page rows and page stacks](https://develop.kde.org/docs/getting-started/kirigami/components-pagerow_pagestack/)，[Kirigami ApplicationWindow：尽可能并排列出可容纳的页面](https://api.kde.org/qml-org-kde-kirigami-applicationwindow.html)

**可借鉴：**Schema、字段属性和 Change Plan 都应是可路由页面；桌面三栏只是这些页面的并排呈现。

**不直接照搬：**Kirigami 没有替本项目决定“检查器是持续编辑还是临时详情”，这一点仍需按 ct 的任务频率设计。

### 2.5 GitLab Pajamas：panel/drawer 分工，以及表格的两种小屏策略

GitLab 的布局规范把 panel 定义为工作区的结构性区域，把 drawer 定义为短生命周期的覆盖或推挤表面；小屏上的 panel 可以覆盖主内容，但它仍是当前工作流的 panel，不应在语义和焦点管理上当成普通 drawer。GitLab 同时建议：应用 chrome 的大变化使用 media query，panel 内部内容变化使用 container query。

GitLab 的表格规范给出两种响应式选择：

- 如果需要跨行比较，保留表格并让表格容器横向滚动；
- 如果一行可以独立理解，或行操作可能滚出视口，则把每行转换为带自身标签的内容组。

证据：[GitLab Layout：Panels vs. drawers、responsive presentation 与 media/container queries](https://design.gitlab.com/product-foundations/layout#panel-based-layout)，[GitLab Table：Responsiveness](https://design.gitlab.com/components/table#responsiveness)，[GitLab Layout：动态 panel 的焦点进入与关闭后焦点恢复](https://design.gitlab.com/product-foundations/layout#focus-management)

**可借鉴：**不要靠一个全局 viewport 断点决定字段行内部所有细节；主编辑区变窄时用 container query。任何覆盖 panel 打开后移入焦点，关闭后恢复触发按钮。

**不直接照搬：**GitLab 允许小屏 panel 覆盖内容，但 ct 的字段属性是长表单、可能持续编辑；手机上用完整属性页比长时间覆盖更稳妥。

### 2.6 VS Code：适合作为桌面工作台参照，不适合作为移动端参照

VS Code 支持 Primary/Secondary Side Bar、隐藏/显示、拖拽布局、最大化活动编辑组，并会跨会话记住 views/panels 的位置。这些是桌面高密度工具的成熟行为。

证据：[VS Code Custom Layout](https://code.visualstudio.com/docs/configure/custom-layout)

**可借鉴：**桌面栏可调宽、可折叠，记住用户布局；主编辑区应能临时最大化。

**不适用：**VS Code 官方桌面工作台并不是移动端响应式参考，不能据此把窄屏做成缩小版 IDE。

### 2.7 Ionic Split Pane：可作为简单双栏开关，不足以承载三层编辑状态

Ionic 的 split pane 面向同一应用同时发布到浏览器、手机和平板：默认大于 `992px` 展开，小于阈值隐藏菜单；`when` 可使用任意媒体查询。

证据：[Ionic `ion-split-pane` 官方文档](https://ionicframework.com/docs/api/split-pane#setting-breakpoints)

**可借鉴：**断点应该可配置且由媒体查询驱动，不应散落在多个组件中。

**不适用：**它只解决“菜单 + 内容”双栏显隐，没有字段属性第三层、历史恢复和复杂草稿状态，不能作为 Schema Editor 的完整答案。

## 3. 对 ct 的语义划分

| 区域 | 语义 | 宽屏 | 中屏 | 窄屏/手机 |
|---|---|---|---|---|
| 模块导航 | 全局导航 | 左侧窄栏 | 左侧窄栏 | `<600px` 改底部导航 |
| 资源列表 | 导航 pane | 持久显示 | 按钮打开临时资源选择层 | 页面栈根页 |
| 主编辑区 | primary content | 持久显示 | 持久显示 | 页面栈内容页 |
| 字段属性 | utility/support pane | 持久显示 | 与主编辑区并排 | 页面栈属性页 |
| Change Plan | task page | 主区全屏/最大化 | 主区全屏 | 独立全屏页 |
| 简短确认/选择 | dialog/sheet | modal | modal | dialog 或 bottom sheet |

关键判断：在 Schema 日常编辑中，“字段表 + 字段属性”比“资源列表 + 字段表”更常同时使用，因此中屏应保留前两者，把资源列表收成临时选择入口。不能只因资源列表在左边，就默认永远保留左栏。

## 4. 推荐断点与行为矩阵

断点不是按设备名称猜测，而是从最小可用宽度反推：

```text
模块栏 56 + 资源列表 248–280 + 主编辑区至少 640
+ 检查器 320–360 + 分隔线/安全余量 ≈ 1320–1360px
```

建议第一版使用以下 CSS px 阈值，再通过真实内容和浏览器缩放测试校准：

| 布局档位 | 视口宽度 | 可见结构 | 打开资源 | 打开字段属性 | 返回/关闭 |
|---|---:|---|---|---|---|
| `wide` | `≥1360` | 模块栏 + 资源 + 主区 + 检查器 | 已常驻 | 已常驻；可折叠/调宽 | 不改变路由，只切可见性 |
| `medium` | `960–1359` | 模块栏 + 主区 + 检查器 | 单一覆盖选择层；选中即关闭 | 常驻，可调宽至 300–360 | Esc/点 scrim 只关闭资源层 |
| `compact` | `600–959` | 模块栏 + 单页面 | 路由到资源页 | 路由到属性页 | 浏览器/应用 back：属性 → 主区 → 资源 |
| `phone` | `<600` | 单页面 + 底部模块导航 | 路由到资源页 | 全屏属性页 | 顶栏返回 + 系统 back |

补充规则：

- 断点以 **CSS viewport/container 宽度** 判断，不根据 User-Agent；浏览器缩放自然会触发布局切换。
- `medium` 只允许一个覆盖层。资源选择层打开时不得再打开 modal inspector；检查器本身已在布局内。
- `<960px` 不把资源树或检查器留在 `transform: translateX(...)` 的视口外；它们应真正变成路由页并从当前布局树移除。这可以直接消除“关闭后仍露出一条”和隐藏控件仍可获得焦点的问题。
- 由窄变宽时，不回到默认首页。若当前路径是 `Item / Fields / Rewards`，宽屏恢复为资源树选中 Item、字段表选中 Rewards、右栏显示 Rewards。
- 由宽变窄时，保留用户正在操作的最深页面：焦点在属性表单则显示属性页；否则显示主编辑页。不能因断点变化自动弹出资源列表。
- 用户自定义栏宽按 `wide`、`medium` 两个档位分别保存，并设置硬最小值；不要把宽屏的 420px 检查器宽度直接带到 1024px 窗口。
- 低高度（例如 `720×460`）时，各 pane 独立纵向滚动；顶栏和 Workspace Draft 主操作不能覆盖表格最后一行。

## 5. 路由与状态模型

建议让 URL/应用状态表达工作上下文，布局控制器只决定这些页面是并排还是串行：

```text
#/schema/resources
#/schema/Item?tab=fields
#/schema/Item/fields/Rewards?panel=properties
#/schema/changes/review
```

最小状态应包括：

```text
resourceId        当前 Table / Record / Enum 的稳定 ID
resourceTab       fields / indexes / dependencies / values
selectionPath     例如 Item.Rewards；使用稳定路径，不用行号
navigationStack   resources → resource → field-properties
workspaceDraft    独立于 pane 生命周期的变更集
panePreferences   wide/medium 各自的显隐与栏宽
scrollPositions   按 resourceId + tab 保存主区位置
```

状态规则：

1. 改变断点只改变 `visiblePanes`，不修改 `resourceId`、`selectionPath` 或草稿。
2. 从属性页返回主区后，字段行仍保持选中并滚回可见位置。
3. 从主区返回资源页后，当前资源仍高亮；重新进入时恢复原页签和滚动位置。
4. 删除/重命名选中字段后，用迁移后的稳定路径更新 selection；目标消失时回退到所属资源，而不是任意选中第一行。
5. 覆盖层关闭后恢复打开按钮焦点；路由进入新页后焦点进入页标题或第一个错误字段。
6. 不可见 pane 使用条件渲染或 `hidden/inert`，不能只靠负位移隐藏。

## 6. 字段表和其他表格的小屏策略

不能把所有表都简单改成横向滚动。

| 内容 | `≥960px` | `600–959px` | `<600px` | 原因 |
|---|---|---|---|---|
| 字段结构列表 | 完整列：字段、类型、Excel、角色、操作 | 保留字段、类型、角色；Excel/次操作进入行详情 | 每字段一个紧凑分组：名称+类型首行，角色/变更次行；点击进属性页 | 单字段可独立编辑，操作不能滚出屏幕 |
| 查询索引 | 完整表格 | 表格容器横向滚动，字段列 sticky | 同左，必要时进入索引详情页 | 需要跨行比较组合字段、唯一性和名称 |
| 依赖/影响矩阵 | 完整表格或图 | 局部横向滚动 | 先给摘要列表，详情单独查看 | 关系比较比单行卡片更重要 |
| Change Plan 变更清单 | 分组列表 + diff | 同结构压缩 | 按资源/操作分组的纵向列表 | 审查动作和风险必须始终可见 |
| 代码/YAML diff | 自身滚动 | 自身横向滚动 | 自身横向滚动 | 不应软换行破坏语义 |

字段结构移动端分组仍要保留语义化列表/按钮与明确 label，不应伪装成一个残缺的 `<table>`。需要比较的表格则保留 `<table>`、`<th scope="col">` 和同一个滚动容器中的表头/表体。

## 7. 当前原型需要调整的地方

现有设计系统中的以下规则应在正式 OpenSpec 中替换：

```text
旧：801–1180px，资源树和检查器改为互斥抽屉
新：960–1359px，主编辑区 + 检查器并排，资源列表为唯一临时选择层

旧：720–800px，仍保留桌面字段表并局部横向滚动
新：<960px 进入页面栈；字段列表按内容类型选择两列简表或行分组
```

这不是单纯换两个 media query。需要先把 `resourceId / selectionPath / navigationStack / workspaceDraft` 从 DOM 和 drawer 开关中抽离，再让布局消费状态。否则继续修 CSS 仍会反复出现：

- 标题已经切换，主内容仍是上一个资源；
- 抽屉关闭但留下可见窄条；
- 隐藏属性区仍截获焦点；
- 收窄/放宽后字段选中和草稿丢失；
- 表头和数据行分别计算宽度而错位。

## 8. 实施顺序

1. 建立稳定的 route/store 状态，不改变视觉。
2. 把资源页、Schema 主编辑页、字段属性页、Change Plan 变成可独立渲染的页面单元。
3. 建立唯一 `AdaptiveWorkspace`，集中计算 `wide / medium / compact / phone`；组件内部只使用 container query。
4. 先实现 `wide` 与 `<960px` 页面栈，再增加 `medium` 的主区+检查器和资源选择层。
5. 最后实现栏宽拖动、按布局档位持久化、滚动恢复和过渡动效。
6. 将同一框架复用于 i18n 的“表列表 → 翻译表 → 条目属性”；其他模块不强制三栏。

不建议现在引入完整 SAPUI5、GTK 或 Compose 运行时。它们证明的是成熟的布局与状态模型；ct 当前是无构建 Vue Web Panel，迁移整套 UI 框架的成本远高于收益。可以复用的是经过验证的 **3/2/1 栏状态机、导航页栈、panel/drawer 语义和状态持久化原则**，而不是复制某个框架的视觉组件。

## 9. 验收矩阵

| 场景 | 预期 |
|---|---|
| `1600×900` | 三栏同时可见；资源/字段选择一致；栏宽可调整 |
| `1360×768 ↔ 1359×768` | 只改变 pane 组合，不改变资源、字段、页签、草稿 |
| `1280×720`、`1024×640` | 主区+检查器；资源选择层完全关闭时不占位、不露边、不入焦点 |
| `960×640 ↔ 959×640` | 从两栏进入页面栈；当前最深上下文仍可见 |
| `720×460` | 单页工作流可完整编辑；主操作不遮挡；无页面级横向滚动 |
| `600×800 ↔ 599×800` | 模块竖栏切换为底部导航，当前 Schema 路由不变 |
| `390×844` | 资源 → Schema → 属性可 push/back；系统返回顺序正确 |
| 浏览器缩放 `100% / 125% / 150%` | 依据 CSS 可用宽度自然切档，不出现半栏和空白条 |
| 旋转或连续拖动窗口 | 不重置 selection；不重复创建 draft；不同时出现两个 scrim |
| 键盘与读屏 | 新 pane/page 获得合理焦点；关闭覆盖层恢复触发点；隐藏 pane 不可 Tab 到达 |
| 字段表 | 同一档位内表头与内容共享列定义；只有表格容器可横向滚动 |

## 10. 最终建议

采用 **GNOME 的语义分工 + SAP 的 3/2/1 栏状态机 + Android/KDE 的页面栈与历史 + GitLab 的表格决策**：

- `≥1360px`：完整三栏；
- `960–1359px`：主编辑区与属性检查器两栏，资源选择为唯一临时层；
- `<960px`：不再使用左右双抽屉，改成可返回、可恢复的页面栈；
- `<600px`：模块导航移到底部，字段属性和 Change Plan 都是全屏任务页；
- 任何宽度变化都只改变布局投影，不改变业务状态。

这是对当前 Web Panel 最值得借鉴的核心思想：**不是让三个 DOM 盒子在所有尺寸下都存在，而是让同一个任务状态在 3 栏、2 栏和 1 栏之间无损重排。**
