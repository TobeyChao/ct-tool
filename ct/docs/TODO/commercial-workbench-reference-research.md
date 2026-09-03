# ct Schema Editor 商业化工作台参考调研

> 日期：2026-08-31
> 目标：为左右侧栏选择一套完整范式，替换当前“展开 / 折叠 / 隐藏 / 覆盖层”叠加的补丁式实现
> 主参考：JupyterLab Workbench
> 源码基线：`jupyterlab/jupyterlab@9312e29b7bbc95ef905b96afe00c93361943f2f6`

## 1. 结论

新版不再拼接 DeepSeek Harness、普通 Drawer 和自定义 hide 动画，统一采用 **JupyterLab 的双 Activity Bar + Side Area 模型**。

核心规则只有一条：

> 左右内容区可以收起，但左右 Activity Bar 永久保留；点击活动 Tab 收起内容，再次点击同一个 Tab 恢复内容。

映射到 ct：

```text
展开
┌────────┬──────────┬────────────────────┬──────────┬──────┐
│ 左工具条 │ 资源内容区 │ Schema 主编辑区      │ 属性内容区 │ 右工具条 │
│  56px  │  242px   │     minmax(0,1fr) │  300px   │ 40px │
└────────┴──────────┴────────────────────┴──────────┴──────┘

两侧收起
┌────────┬────────────────────────────────────────┬──────┐
│ 左工具条 │ Schema 主编辑区                          │ 右工具条 │
│  56px  │                                        │ 40px │
└────────┴────────────────────────────────────────┴──────┘
```

因此新版只有 `open / collapsed-to-activity-bar`，没有 `hidden`：

- 左侧资源内容收起后，现有深色模块工具条仍在，`SC` 就是恢复入口；
- 右侧属性内容收起后，右侧 40px 属性工具条仍在，属性 Tab 就是恢复入口；
- 不存在“折叠后再隐藏”，也不存在从展开宽度补播隐藏动画；
- 不使用 `translateX()` 把整栏移出屏幕；
- 不再需要临时添加的顶栏“属性”恢复按钮。

## 2. 为什么选 JupyterLab，而不是继续以 DeepSeek Harness 为主

### 2.1 它从一开始就是对称的左右工作台

JupyterLab 官方界面文档同时定义左、右 Sidebar，并把切换列明确命名为 Activity Bar。官方交互是：通过菜单或再次点击活动 sidebar tab 折叠/展开。[官方界面文档](https://jupyterlab.readthedocs.io/en/stable/user/interface.html#left-and-right-sidebar)

源码中左、右分别由同一个 `SideBarHandler` 管理，不是两套临时实现；`collapseLeft()` / `collapseRight()` 和 `expandLeft()` / `expandRight()` 完全对称。[官方 `shell.ts`](https://github.com/jupyterlab/jupyterlab/blob/9312e29b7bbc95ef905b96afe00c93361943f2f6/packages/application/src/shell.ts#L1132-L1192)

JupyterLab 还为左右侧分别编写了“收起后内容不可见”和“重新展开最近使用项”的测试。这说明恢复入口和最近上下文是组件契约，不是视觉补丁。[官方测试](https://github.com/jupyterlab/jupyterlab/blob/9312e29b7bbc95ef905b96afe00c93361943f2f6/packages/application/test/shell.spec.ts#L351-L437)

### 2.2 收起的定义非常清楚

它的 SideBar 使用可取消选中的垂直 `TabBar`。在 side 模式下：

- 点击当前 Tab 会取消选择；
- 内容 `StackedPanel` 收起；
- Activity Bar 仍是固定窄条；
- `expand()` 恢复最近使用的 Tab，没有最近项时才选择第一项。

源码注释直接写明：点击活动 Tab 收起 Area，但 Activity Bar 保持为细条。[`SideBarHandler`](https://github.com/jupyterlab/jupyterlab/blob/9312e29b7bbc95ef905b96afe00c93361943f2f6/packages/application/src/shell.ts#L2194-L2401)

这正好解决当前原型的两个缺陷：

1. 左侧不会再经历“完整栏 → 窄轨 → 再 hide”的双阶段状态；
2. 右侧恢复入口是永久 Activity Bar，不需要等内容栏存在才能找到按钮。

### 2.3 尺寸和视觉职责也是系统化的

官方样式把垂直 Activity Bar 固定为 `32px + border`，图标固定 20px；内容区有独立最小宽度，并由 SplitPanel 控制。Tab strip 与内容 pane 是两个兄弟区域，不是把完整内容强行压成图标。[官方 `sidepanel.css`](https://github.com/jupyterlab/jupyterlab/blob/9312e29b7bbc95ef905b96afe00c93361943f2f6/packages/application/style/sidepanel.css#L8-L175)

ct 不必复制 32px；为了触控、中文 tooltip 和现有 56px 模块栏，建议使用：

- 左 Activity Bar：现有 56px；
- 左资源内容：默认 242px；
- 右属性内容：默认 300px；
- 右 Activity Bar：40px；
- Activity Bar 图标触控目标：36–40px；
- 用户调宽只改变内容区宽度，不改变 Activity Bar 宽度。

### 2.4 状态恢复是工作区能力，不是 localStorage 小补丁

JupyterLab Workspace 保存应用区域、Tabs 和面板开关状态；`SideBarHandler.dehydrate()` / `rehydrate()` 明确保存 `collapsed`、当前 Widget、顺序和内部展开状态。[官方 Workspace 文档](https://jupyterlab.readthedocs.io/en/stable/user/workspaces.html) [`dehydrate / rehydrate`](https://github.com/jupyterlab/jupyterlab/blob/9312e29b7bbc95ef905b96afe00c93361943f2f6/packages/application/src/shell.ts#L2435-L2535)

ct 应保存领域状态，而不是保存 DOM 动画状态：

```text
left.activeTool       = resources | null
left.lastTool         = resources
left.contentWidth     = 242

right.activeTool      = field-properties | null
right.lastTool        = field-properties
right.contentWidth    = 300

editor.resourceId
editor.tab
editor.fieldPath
editor.workspaceDraft
```

不保存：

```text
isAnimating
isHidden
overlayOpen
translateOffset
settledWidth
```

## 3. 明确不采用 JupyterLab 的哪一部分

JupyterLab 还提供高级的 `hide()`，允许用户连 Activity Bar 一起隐藏。这是 IDE 的 View 菜单能力，源码也把它单独存为 `_isHiddenByUser`。[官方源码](https://github.com/jupyterlab/jupyterlab/blob/9312e29b7bbc95ef905b96afe00c93361943f2f6/packages/application/src/shell.ts#L2540-L2618)

**ct 第一版明确不提供这项能力。**

原因：

- ct 左右 Activity Bar 已经只有 56px / 40px，继续隐藏收益很低；
- 隐藏 Activity Bar 会再次制造独立恢复入口；
- 当前页面只有一个主要工作区，不需要 IDE 的“演示模式 / 禅模式 / 隐藏所有工具窗口”；
- 用户已经明确指出“折叠后再隐藏”造成错误动画和状态混乱。

我们采用 JupyterLab 的正常 Sidebar 交互，不采用其高级 View 菜单隐藏能力。

## 4. 其他候选为什么不作为主参考

### 4.1 DeepSeek Harness：局部优秀，但不是完整答案

它的 `280px → 56px rail`、状态分层和无重排折叠值得参考，但左右不对称，窄屏仍可能让侧栏内联挤压中心区。此前已经在[专项调研](./deepseek-harness-ui-research.md)中确认。它适合解释“rail 应是什么”，不适合继续作为 ct 整体 Workbench 的主骨架。

### 4.2 VS Code：商业成熟，但其恢复入口不符合当前目标

VS Code 完整定义 Primary / Secondary Side Bar，并允许通过 Layout Controls、命令和菜单切换可见性。[官方 Custom Layout](https://code.visualstudio.com/docs/configure/custom-layout) [官方 Sidebar UX 指南](https://code.visualstudio.com/api/ux-guidelines/sidebars)

它适合大型 IDE，但“Activity Bar、Primary Sidebar、Secondary Sidebar、Panel、Layout Controls”层级更多；Secondary Sidebar 的恢复入口依赖全局布局控制，不像 JupyterLab 那样天然在右侧保留对称 Activity Bar。照搬会让 ct 再次引入额外全局控制。

### 4.3 Directus：领域接近，但侧栏不是统一双侧组件

Directus Data Studio 与 ct 同属结构化数据管理工具，适合参考字段文案、表单密度和数据模型概念。[官方仓库](https://github.com/directus/directus) [官方扩展布局文档](https://directus.com/docs/guides/extensions/overview)

但它的主导航、Collection 内容、Drawer / Preview sidebar 承担不同导航层级，不是一套左右对称的 Activity Bar 状态机。作为视觉或字段编辑参考可以，不能作为本次 pane architecture 的主参考。

### 4.4 Supabase Studio：领域接近，但折叠侧栏本身仍有响应式缺陷记录

Supabase Studio 是成熟的数据工作台，但官方仓库已有 collapsed sidebar 在特定分辨率丢失入口的缺陷记录。[官方 issue](https://github.com/supabase/supabase/issues/36282)

它不适合作为当前“折叠后所有入口必须稳定”的唯一基准。

## 5. ct 的最终桌面交互模型

### 5.1 左侧

现有深色模块栏直接作为 Left Activity Bar，不再额外创建第二条 56px 资源 rail。

- 首次进入 Schema：`SC` 活动，资源内容区展开；
- 再次点击活动的 `SC`：资源内容区收起，`SC` 仍留在原位；
- 再次点击 `SC`：恢复资源内容区、滚动位置、搜索条件和当前分组；
- 点击 Export / i18n / Logs / History：切换模块，不触发“侧栏隐藏动画”；
- `Tables / Records / Enums` 是资源内容内部的折叠组，与 Side Area 是否展开无关。

### 5.2 右侧

增加固定 Right Activity Bar，第一版只有一个“字段属性”Tab。

- 选中字段时可以自动激活属性 Tab；
- 点击活动属性 Tab：属性内容区收起，右侧 40px Tab 保留；
- 再次点击：恢复最近字段的属性内容；
- 属性内容区标题里的关闭按钮与右侧活动 Tab 执行同一命令；
- 不再在顶栏临时显示“属性”恢复按钮。

当未来加入校验问题、依赖或生成预览时，它们可以成为 Right Activity Bar 的第二、第三个 Tab，不需要再造新 Drawer。

### 5.3 动效

主参考的稳定性比装饰性动画更重要。第一版建议：

- 删除所有侧栏 `translateX()`；
- 删除 hide 动画及动画专用布尔值；
- Pane 展开/收起先采用即时 Split/Grid 状态切换；
- 只保留 Activity Tab 的 hover、pressed 和 active indicator；
- 如果浏览器回归确认稳定，再增加单一的 `120ms` grid-track 宽度过渡；
- 不对内容文字、树节点和表单做位移或逐项淡化；
- `prefers-reduced-motion` 下始终即时切换。

商业工具不需要为了“看起来有动画”牺牲可预测性。JupyterLab 的官方 SidePanel 样式本身也没有依赖滑出视口的 transform 动画。

## 6. 响应式仍使用同一状态模型

JupyterLab 支持 `single-document` 模式，并且最新 Workbench 允许 Activity Bar 从侧面改到 top / bottom、以横向 Tabs 呈现。[官方 Simple Interface 文档](https://jupyterlab.readthedocs.io/en/stable/user/interface.html#tabs-and-simple-interface-mode) [官方 Activity Bar Position](https://jupyterlab.readthedocs.io/en/latest/user/interface_customization.html#activity-bar-position)

ct 据此采用一个模型、三种投影：

| 宽度 | 投影 |
|---|---|
| `≥1360px` | 左右 Activity Bar 常驻；左右内容区可同时展开 |
| `960–1359px` | 左右 Activity Bar 常驻；最多展开一个辅助内容区，打开另一侧时收起当前侧 |
| `<960px` | 进入 single-document 页面栈：资源 / 编辑 / 属性；侧面 Tabs 转成页面级入口，不保留隐藏 Drawer |
| `<600px` | 模块入口移到底部，资源 / 编辑 / 属性仍是页面栈 |

中屏不再使用资源 Overlay 和 scrim，也不再把资源栏 `translateX(-100%)`。空间不足时是确定性的“单辅助区”，不是自动 hide：

```text
open left  => left.activeTool = resources, right.activeTool = null
open right => right.activeTool = field-properties, left.activeTool = null
```

回到宽屏时可以恢复用户最近的左右偏好，但当前资源、字段、页签和草稿始终不变。

## 7. 实施要求

这次不在现有原型上继续添加条件，应重写 pane architecture：

1. 删除 `resourceCollapsed + navigator.open + overlayOpen + inspectorCollapsed` 组合；
2. 删除 pane 的 `translateX`、scrim 和顶栏临时恢复按钮；
3. 建立统一 `SideArea`，左右共享 open / collapse / restore 契约；
4. 左侧复用现有模块 Activity Bar，右侧新增固定 Activity Bar；
5. 内容区宽度和活动工具进入统一 layout store；
6. 响应式只是 store 的投影，不回写桌面偏好；
7. 先完成无动画版本的状态与焦点验收，再考虑 120ms 宽度过渡；
8. 通过后再重做截图和 OpenSpec，不保留当前补丁实现作为生产基础。

## 8. 验收清单

| 场景 | 预期 |
|---|---|
| 点击活动 `SC` | 资源内容收起，左工具条与 `SC` 永久可见 |
| 再次点击 `SC` | 恢复资源内容、分组、搜索和滚动位置 |
| 点击右侧活动属性 Tab | 属性内容收起，右 Activity Bar 永久可见 |
| 再次点击属性 Tab | 恢复当前字段属性，不依赖顶栏临时按钮 |
| 左侧收起后切换模块 | 不补播任何展开态动画 |
| 中屏打开另一侧 | 当前辅助区同步收起，中心区不低于最小可用宽度 |
| `<960px` | 使用页面栈，无隐藏 Drawer、无屏外可聚焦内容 |
| 快速连续点击 | 状态只在 `tool id / null` 间切换，不出现中间 animation state |
| 刷新 | 恢复左右工具、宽度和编辑上下文 |
| 键盘 | Activity Tab 有明确焦点；Enter/Space 可切换；收起内容不可聚焦 |
| reduced motion | 行为完整且即时，无 transform 残留 |

## 9. 最终判断

JupyterLab 给 ct 的不是一组可以继续拼装的细节，而是一套完整 Workbench 语法：

```text
Activity Bar 永久存在
        +
Active Tool 决定内容区是否展开
        +
左右共享同一个 SideArea 契约
        +
Workspace 保存领域状态
```

这套模型足以替换当前所有隐藏补丁。下一版原型应从布局骨架重做，而不是修正现有左右动画。
