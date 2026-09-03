# DeepSeek Harness 左侧导航与资源树设计调研

> 日期：2026-08-31
> 目标：判断 ct Schema Editor 的资源区能否采用左侧折叠/展开，并提炼 DeepSeek Harness 可复用的设计思想
> 来源规则：只引用 DeepSeek 官方发布页、官方仓库、仓库源码与仓库内 README
> 源码基线：`deepseek-ai/deepseek-harness@0a53fb55bea101816fa226bb964ae2bed71c343b`（2026-08-30）

## 1. 结论

可以做，而且建议做，但需要区分两种不同的“折叠”：

1. **整个资源栏折叠成窄轨道**：借鉴 DeepSeek Harness 的 `280px → 56px` 侧栏。折叠后不是留下空白条，也不是把完整资源树藏到视口外，而是替换成少量稳定、可操作的入口。
2. **资源分组在树内展开/收起**：借鉴它的 Workspace → Session 层级。分组展开状态按稳定资源 ID 保存，当前选中资源所在分组应自动展开。

对 ct 推荐的结果是：

```text
桌面宽屏
模块轨 56 | 资源栏 264–360 | 主编辑区 | 属性区

桌面资源栏折叠
模块轨 56 | 资源快捷轨 48–56 | 主编辑区 | 属性区

中屏
模块轨 56 | 主编辑区 | 属性区
             ↑ 资源按钮打开临时选择层

手机
资源页 → Schema 页 → 属性页
```

也就是说，**DeepSeek Harness 的 rail 适合补强 ct 的桌面布局，不适合替换已经确定的移动端页面栈**。它当前的源码没有把三栏真正重排为移动页面，而是缩为侧栏轨道、关闭详情栏、让中间栏吸收剩余宽度；手动展开窄屏侧栏时仍会挤压中间内容。这是明确的桌面优先模型，不是“同时支持 PC 与手机”的完整答案。[列宽求解器](https://github.com/deepseek-ai/deepseek-harness/blob/0a53fb55bea101816fa226bb964ae2bed71c343b/packages/client/ui-layout/src/client/columns.ts#L19-L39) [窄屏展开逻辑](https://github.com/deepseek-ai/deepseek-harness/blob/0a53fb55bea101816fa226bb964ae2bed71c343b/packages/client/ui-layout/src/client/AppFrame.tsx#L140-L152)

## 2. 用户所指项目的定位

最可能且唯一应作为设计依据的项目是：

- 官方仓库：[deepseek-ai/deepseek-harness](https://github.com/deepseek-ai/deepseek-harness)
- DeepSeek 官方发布页：[DeepSeek Harness developer preview](https://www.deepseek.com/harness/en/)
- 官方文档：[DeepSeek Harness docs](https://deepseek-harness.github.io/deepseek-harness/)

证据链：

- DeepSeek 官方发布页的 “View on GitHub” 直接指向 `github.com/deepseek-ai/deepseek-harness`。
- 仓库 README 明确称其为 DeepSeek AI 开发的开源 agent harness，并把官方文档指向 `deepseek-harness.github.io/deepseek-harness`。[官方 README](https://github.com/deepseek-ai/deepseek-harness/blob/0a53fb55bea101816fa226bb964ae2bed71c343b/README.md#L1-L12)
- 搜索中存在社区汇总、桌面封装和本地化 fork，但它们不是 DeepSeek 第一方项目，不能用来判断官方 Web UI 的真实设计。

仓库仍标注为 **developer preview**，并明确提醒会有破坏性变化。因此适合借鉴思想，不适合把当前组件契约或具体像素当成长期稳定标准。[官方发布页](https://www.deepseek.com/harness/en/) [仓库开发预览说明](https://github.com/deepseek-ai/deepseek-harness/blob/0a53fb55bea101816fa226bb964ae2bed71c343b/README.md#L10-L15)

## 3. 它的左侧栏实际上怎样工作

### 3.1 三栏框架不是多个绝对定位抽屉，而是一个连续 Grid

`AppFrame` 始终使用三列 Grid：`sidebar | minmax(0, 1fr) | details`。三列宽度由一个纯函数集中求解，侧栏和详情栏的拖动也只改变宽度偏好；主内容使用 `minmax(0, 1fr)`，因此不会因内部最小内容宽度把整页撑出视口。[AppFrame Grid](https://github.com/deepseek-ai/deepseek-harness/blob/0a53fb55bea101816fa226bb964ae2bed71c343b/packages/client/ui-layout/src/client/AppFrame.tsx#L175-L215)

固定几何参数是：

| 区域 | 默认 | 最小 | 最大 | 关闭后 |
|---|---:|---:|---:|---:|
| 左侧栏 | `280px` | `264px` | `420px` | `56px` rail |
| 中间栏 | — | 目标 `640px` | — | 吸收剩余空间 |
| 右详情栏 | `360px` | `300px` | `520px` | `0px` |

来源：[官方 `columns.ts`](https://github.com/deepseek-ai/deepseek-harness/blob/0a53fb55bea101816fa226bb964ae2bed71c343b/packages/client/ui-layout/src/client/columns.ts#L19-L39)

空间不足时的让步顺序也写成了纯函数：

1. 三栏按偏好宽度显示；
2. 先缩右侧详情栏到最小值；
3. 仍放不下就把右详情栏派生为 `0px`；
4. 左侧栏不继续退让，中间栏最终吸收缺口。

重要的是，**自动关闭只改变这次布局的求解结果，不覆盖用户的偏好值**，所以窗口放宽后详情栏能够自动恢复。[列宽让步链](https://github.com/deepseek-ai/deepseek-harness/blob/0a53fb55bea101816fa226bb964ae2bed71c343b/packages/client/ui-layout/src/client/columns.ts#L52-L76)

### 3.2 折叠后保留的是可用 rail，不是“露出一点原侧栏”

侧栏关闭后宽度固定为 `56px`，内部是 `36×36px` 控件，左右各约 `10px`。它保留品牌/展开入口、新建会话、搜索、添加工作区和底部设置等少量高频操作；完整工作区树不会压缩成不可读文字。[rail 几何](https://github.com/deepseek-ai/deepseek-harness/blob/0a53fb55bea101816fa226bb964ae2bed71c343b/packages/client/ui-sidebar/src/client/SidebarRoot.module.css#L22-L30) [rail 内容渲染](https://github.com/deepseek-ai/deepseek-harness/blob/0a53fb55bea101816fa226bb964ae2bed71c343b/packages/client/ui-workspace/src/client/rows/WorkspaceBrowser.tsx#L1070-L1204)

值得注意的细节：

- 展开时右上角是明确的 panel-collapse 图标，并有 `aria-label` 和延迟 tooltip；折叠时品牌图标本身成为展开入口，hover 才换成 panel 图标。[切换按钮](https://github.com/deepseek-ai/deepseek-harness/blob/0a53fb55bea101816fa226bb964ae2bed71c343b/packages/client/ui-sidebar/src/client/SidebarRoot.tsx#L140-L188)
- rail 中的搜索不是失效图标；点击后先展开侧栏，再等待 `300ms` 滑动结束后聚焦输入框，避免同步 focus 触发布局卡顿。[展开时搜索](https://github.com/deepseek-ai/deepseek-harness/blob/0a53fb55bea101816fa226bb964ae2bed71c343b/packages/client/ui-workspace/src/client/rows/WorkspaceBrowser.tsx#L31-L41) [rail 搜索触发](https://github.com/deepseek-ai/deepseek-harness/blob/0a53fb55bea101816fa226bb964ae2bed71c343b/packages/client/ui-workspace/src/client/rows/WorkspaceBrowser.tsx#L1183-L1199)
- 折叠时没有 resize handle；展开时才提供 8px 隐形拖动热区，拖动期间暂停列宽过渡，避免边界脱离鼠标。[拖动句柄](https://github.com/deepseek-ai/deepseek-harness/blob/0a53fb55bea101816fa226bb964ae2bed71c343b/packages/client/ui-layout/src/client/AppFrame.tsx#L156-L172) [句柄显示条件](https://github.com/deepseek-ai/deepseek-harness/blob/0a53fb55bea101816fa226bb964ae2bed71c343b/packages/client/ui-layout/src/client/AppFrame.tsx#L213-L215)

### 3.3 折叠动效避免中途重排

它没有让文字、按钮和树节点随着列宽逐帧挤压。收起时先冻结展开内容的实际宽度，整块淡出并由外层列裁切；约 `150ms` 后才卸载宽内容、切换为 rail 布局。展开内容重新挂载时再淡入。这样避免了常见的图标跳位、文字逐字换行和表面抖动。[状态与冻结宽度](https://github.com/deepseek-ai/deepseek-harness/blob/0a53fb55bea101816fa226bb964ae2bed71c343b/packages/client/ui-sidebar/src/client/SidebarRoot.tsx#L60-L79) [动效 CSS](https://github.com/deepseek-ai/deepseek-harness/blob/0a53fb55bea101816fa226bb964ae2bed71c343b/packages/client/ui-sidebar/src/client/SidebarRoot.module.css#L41-L85)

它也支持 `prefers-reduced-motion: reduce`，会关闭这些过渡和动画。[reduced motion](https://github.com/deepseek-ai/deepseek-harness/blob/0a53fb55bea101816fa226bb964ae2bed71c343b/packages/client/ui-sidebar/src/client/SidebarRoot.module.css#L348-L358)

### 3.4 侧栏内部是可折叠资源树，而不是平铺大列表

Workspace 行本身使用 `role="treeitem"` 和 `aria-expanded`；整行点击负责展开/收起。默认显示文件夹图标，hover 时在同一图标槽中换成 chevron；展开时 chevron 旋转 90°。这样没有因为状态图标变化而挤动标题。[Workspace tree row](https://github.com/deepseek-ai/deepseek-harness/blob/0a53fb55bea101816fa226bb964ae2bed71c343b/packages/client/ui-workspace/src/client/rows/Rows.tsx#L100-L155) [图标槽和旋转](https://github.com/deepseek-ai/deepseek-harness/blob/0a53fb55bea101816fa226bb964ae2bed71c343b/packages/client/ui-workspace/src/client/rows/Rows.module.css#L83-L119)

树有两级收纳：

- 第一层：Workspace 整组展开/收起；
- 第二层：一个已展开 Workspace 默认只显示 5 条普通 Session，剩余条目通过“显示更多/收起”控制，不让一个大组吞掉整个导航栏。[五条上限](https://github.com/deepseek-ai/deepseek-harness/blob/0a53fb55bea101816fa226bb964ae2bed71c343b/packages/client/ui-workspace/src/client/rows/WorkspaceBrowser.tsx#L40-L55) [组内溢出控制](https://github.com/deepseek-ai/deepseek-harness/blob/0a53fb55bea101816fa226bb964ae2bed71c343b/packages/client/ui-workspace/src/client/rows/WorkspaceBrowser.tsx#L528-L582)

当前 Session 所在 Workspace 在尚无明确用户选择时会自动展开；组内切换不会重复改写展开状态。[自动展开当前组](https://github.com/deepseek-ai/deepseek-harness/blob/0a53fb55bea101816fa226bb964ae2bed71c343b/packages/client/ui-workspace/src/client/rows/WorkspaceBrowser.tsx#L278-L297)

### 3.5 状态分层比动效更值得借鉴

DeepSeek Harness 没有把所有 UI 状态塞进一个 `sidebarOpen` 布尔值：

- 布局 store 保存左/右栏宽度偏好、是否处于窄屏，以及窄屏临时展开 override；
- 列宽求解器根据容器实际宽度得到本次渲染结果；
- Workspace 浏览 store 单独保存分组模式、排序、各 Workspace 展开状态和顺序；
- 折叠动画的 `settled`、hover、搜索框展开等短生命周期状态留在组件内部。

这使“窗口自动收起侧栏”不会改掉原栏宽，“侧栏收起”也不会丢掉资源树展开状态。[布局 store](https://github.com/deepseek-ai/deepseek-harness/blob/0a53fb55bea101816fa226bb964ae2bed71c343b/packages/client/ui-layout/src/client/stores.ts#L16-L68) [Workspace 浏览 store](https://github.com/deepseek-ai/deepseek-harness/blob/0a53fb55bea101816fa226bb964ae2bed71c343b/packages/client/ui-workspace/src/client/stores.ts#L12-L78)

它还明确选择了不同的持久化边界：panel 几何是临时的、刷新后恢复默认；Workspace 分组展开与顺序则写入 `localStorage`。这是一个有意识的产品判断，而不是技术偶然。[布局 README 的限制](https://github.com/deepseek-ai/deepseek-harness/blob/0a53fb55bea101816fa226bb964ae2bed71c343b/packages/client/ui-layout/README.md#L70-L78) [Workspace store 持久化键](https://github.com/deepseek-ai/deepseek-harness/blob/0a53fb55bea101816fa226bb964ae2bed71c343b/packages/client/ui-workspace/src/client/stores.ts#L51-L65)

## 4. 适合借鉴到 ct 的设计

### 4.1 桌面增加“资源快捷轨”

在 `wide` 布局下允许资源栏在 `264–360px` 与 `52–56px` rail 之间切换。rail 不显示被截断的资源名称，只保留：

- 顶部：展开资源栏；
- 中部：搜索、全部资源、最近资源、当前资源所属分组；
- 底部：新增资源或导入操作；
- 图标必须有 tooltip、`aria-label` 和键盘焦点态。

ct 已有独立的模块导航轨，因此不能照抄 DeepSeek 的品牌/设置 rail。两个轨道必须视觉分层：模块轨使用深色品牌底；资源 rail 使用内容侧栏底色和右分隔线，防止看起来像重复导航。

### 4.2 资源列表改成真正的分组树

建议资源树分组：

```text
▾ Tables
    Item
    ItemType
    Quest
    UIConfig
▸ Records
▸ Enums
```

规则：

- 分组整行可点击，图标位固定，使用 `aria-expanded`；
- 当前选中资源有持续高亮；当前分组即使被收起，也应在组标题上保留选中指示或自动重新展开；
- 展开状态以 `workspace + resourceKind` 稳定键保存，不能按 DOM 序号保存；
- 资源数量不多时不需要套用“每组只显示 5 个”；当单组超过约 12–20 项时，再提供“显示其余 N 项”或搜索过滤；
- `Tables / Records / Enums` 的展开状态应该持久化，但“搜索展开、hover 菜单、拖动标记”不持久化。

### 4.3 采用纯布局求解，不让 media query 到处改状态

建议将 ct 的 pane 几何集中为：

```text
preferredResourceWidth
resourceCollapsedByUser
resourceAutoCollapsed
detailsPreferredWidth
layoutMode
```

`resolvedResourceWidth` 与 `visiblePanes` 是派生值。窗口从宽变窄时，不要写回用户的桌面偏好；放宽后自动恢复。资源选择、字段选择、页签和草稿仍由业务 store 管理，完全不依赖 pane 是否挂载。

### 4.4 动效只做“冻结 + 交叉淡化”

整个折叠控制在约 `180–240ms`：

- 外层 Grid track 改宽；
- 展开内容固定原宽后淡出，由父容器 `overflow: hidden` 裁切；
- rail 图标在后半段淡入；
- 展开反向执行；
- `prefers-reduced-motion` 关闭动画。

不要对树中文字逐项设置位移，也不要用 `transform: translateX(-110%)` 把一整栏藏在视口外。后者正是容易在浏览器缩放、栏宽变化后留下白条的做法。

### 4.5 保留细微但有效的桌面品质

- 行标题 `min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap`；完整路径或名称通过 hover/focus card 查看。
- 列表保留 scrollbar gutter，滚动条显隐不改变行宽；是否像 DeepSeek 那样在 pointer 离开后隐藏滚动条，可以后续再评估，不是首版必需。
- 行尾操作在 hover/focus 时显示；但选中、菜单打开时必须固定显示相关状态，不能一移开鼠标就丢失上下文。
- 展开按钮使用同一固定图标槽，避免 folder/chevron 交换造成文字横向跳动。
- 对拖拽调宽使用 Pointer Events、pointer capture 与 requestAnimationFrame 节流；拖动期间关闭 transition。

## 5. 不适合照搬的部分

### 5.1 它不是移动端布局范例

源码只有一个 `1024px` 自动收栏阈值。窄于它时默认显示 `56px` rail；用户再次展开，侧栏仍以内联列占据 `264–420px`，中间栏被压缩。右详情栏在空间不足时直接派生为 `0px`，没有移动端属性页、返回栈、drawer scrim 或底部导航。[窄屏断点](https://github.com/deepseek-ai/deepseek-harness/blob/0a53fb55bea101816fa226bb964ae2bed71c343b/packages/client/ui-layout/src/client/columns.ts#L28-L39) [窄屏 override](https://github.com/deepseek-ai/deepseek-harness/blob/0a53fb55bea101816fa226bb964ae2bed71c343b/packages/client/ui-layout/src/client/stores.ts#L54-L66)

因此 ct 必须继续使用已经确定的：

- `960–1359px` 主编辑区 + 属性区，资源为临时选择层；
- `<960px` 资源 → Schema → 属性页面栈；
- `<600px` 底部模块导航。

不要因为新增桌面 rail，又退回“所有尺寸都是三栏，只是更窄”的方案。

### 5.2 hover 专属提示不适合触屏

DeepSeek Workspace 行默认显示文件夹，只有 hover 才换成 chevron；行尾菜单和新增按钮也主要在 hover 时出现。整行点击仍然能展开，所以功能没有完全丢失，但触摸用户很难预判行为。[hover 图标交换](https://github.com/deepseek-ai/deepseek-harness/blob/0a53fb55bea101816fa226bb964ae2bed71c343b/packages/client/ui-workspace/src/client/rows/Rows.module.css#L101-L119)

ct 的资源组必须始终显示 chevron；关键新增/更多操作在触屏尺寸要常驻或进入明确的 `…` 菜单，不能依赖 hover 才可发现。

### 5.3 不直接采用“布局几何刷新即丢失”

DeepSeek 明确把布局几何做成 transient，刷新后恢复默认，关闭再打开也回默认宽度。对聊天型应用合理，但 Schema Editor 是长时间专业工具，用户反复调整资源栏和检查器的概率更高。[布局 store 行为](https://github.com/deepseek-ai/deepseek-harness/blob/0a53fb55bea101816fa226bb964ae2bed71c343b/packages/client/ui-layout/src/client/stores.ts#L38-L68) [官方 README](https://github.com/deepseek-ai/deepseek-harness/blob/0a53fb55bea101816fa226bb964ae2bed71c343b/packages/client/ui-layout/README.md#L12-L28)

ct 更适合：

- 保存用户显式调整的桌面栏宽和折叠偏好；
- 自动折叠结果不持久化；
- `wide` 与 `medium` 分别保存栏宽，不把宽屏尺寸硬套到中屏；
- 提供“恢复默认布局”。

### 5.4 不套用聊天产品的组内五条规则

DeepSeek 每个 Workspace 只先展示 5 个 Session，适合大量、按时间增长的会话。ct 的 Table/Record/Enum 是结构资产，需要快速定位和完整认知；数据量中小时应完整展示。只有某类资源明显过多时，才应该通过搜索、虚拟列表或显式“其余 N 项”控制密度。

### 5.5 不复制插件框架本身

DeepSeek Harness 将 UI 也做成 slot/plugin 组合，这与其“everything is a plugin”产品架构一致。[官方发布页](https://www.deepseek.com/harness/en/) 对 ct 当前无构建 Vue Web Panel 而言，引入同等级插件系统会显著增加状态、生命周期和测试复杂度。应复用 **边界清晰的组件职责**，而不是复制 Cordis/slot 基础设施。

## 6. 对当前 Schema Editor 原型的明确修改建议

### 6.1 宽屏

- 在资源栏标题区增加收起按钮；默认资源栏约 `272px`，允许拖到 `240–360px`。
- 收起后保留 `52px` 资源 rail；主编辑区立即获得释放的宽度，属性区和当前字段不变。
- rail 的“资源”入口点击展开栏；搜索入口点击展开并自动聚焦搜索框。
- `Tables / Records / Enums` 改为可折叠分组；当前原型已有的资源行继续使用。

### 6.2 中屏和窄屏

- `960–1359px` 不显示资源 rail，避免“模块轨 + 资源轨 + 两栏”继续占用横向空间；保留现有临时资源选择层。
- `<960px` 不出现 rail，也不保留隐藏资源栏 DOM；继续使用资源页面栈。
- 窗口跨越断点只改变投影。回到宽屏时恢复用户桌面资源栏偏好、分组展开状态、当前资源和字段。

### 6.3 推荐状态模型

```text
layoutPreferences
  wide.resourceWidth
  wide.resourceCollapsed
  wide.inspectorWidth
  medium.inspectorWidth

resourceTreeView
  expandedGroups: { tables, records, enums }
  query
  recentResourceIds

editorContext
  resourceId
  resourceTab
  fieldPath
  workspaceDraft
  navigationStack
```

其中 `query` 可选择只在本次会话保留；`expandedGroups`、栏宽和显式折叠偏好持久化；`autoCollapsed`、hover、动画 settled、scrim 打开状态不持久化。

## 7. 验收清单

| 场景 | 预期 |
|---|---|
| 宽屏收起资源栏 | 资源栏变成固定窄轨，无白条、无残留文字、无页面横向滚动 |
| 宽屏重新展开 | 恢复原宽；资源分组、当前资源、字段、页签和草稿不变 |
| 点击 rail 搜索 | 先展开资源栏，再聚焦搜索框；动画期间不抖动 |
| 拖动资源栏宽度 | 边界紧跟指针；限制在约 `240–360px`；主区表格保持对齐 |
| `Tables / Records / Enums` 收起展开 | `aria-expanded` 正确；键盘 Enter/Space 可操作；状态按稳定 ID 保存 |
| 当前资源位于已收起组 | 重新进入资源栏时自动展开，或组标题提供清晰当前项提示 |
| `1360 ↔ 1359` | rail/资源栏让位给中屏临时选择层，业务状态不变 |
| `960 ↔ 959` | 进入页面栈，不出现窄轨，不存在隐藏栏可被 Tab 聚焦 |
| `390px` 触屏 | chevron 与关键操作不依赖 hover；触控目标至少约 `40×40px` |
| 浏览器缩放 100/125/150% | 无半截 rail、露边和表头/行错位 |
| reduced motion | 折叠展开无位移动画，但状态切换和焦点仍正确 |

## 8. 最终取舍

DeepSeek Harness 给 ct 的最佳启发不是某种特定绿色/蓝色视觉，也不是把手机继续压成三栏，而是以下四点：

1. **桌面关闭侧栏后留下一个真正有用的 rail。**
2. **把资源树展开状态与 pane 几何、业务选择分开管理。**
3. **用纯列宽求解和派生状态保证窗口恢复，而不是在多个 media query 中互相写状态。**
4. **折叠时冻结旧内容并交叉淡化，避免中途重排。**

因此下一版原型可以增加“桌面资源栏折叠 + Tables/Records/Enums 分组展开”，同时严格保留上一轮已确定的中屏临时资源层和移动端页面栈。这是吸收 DeepSeek Harness 优点、又不继承其移动端局限的做法。
