# 模态导航栈架构（Modal Stack Architecture）

> 日期：2026-08-29；2026-08-31 修订（放弃浏览器 History，改纯 Vue 响应式）
> 状态：已实施（app.js 落地；2026-08-31 从「History 状态机」重构为「纯 Vue 响应式」）
> 关联：`schema-editor-mockup.html`（设计稿）、需求清单 R8 决策 9（类型模态导航栈）
> 背景：struct 可嵌套（FlatBuffers struct 含嵌套 struct），类型查看/编辑模态内需「进入子类型」再返回。不能使用嵌套模态叠加（UX 反模式）。

## 1. 问题与决策

### 1.1 为什么不用嵌套模态叠加

调研结论（业界共识，[The Case Against Nested Modals](https://smart-interface-design-patterns.com/articles/the-case-against-nested-modals/)）：

- 嵌套模态的 Back/Esc 行为不一致，用户无法预测返回层级
- 每层模态遮住下层，用户丢失「我从哪来」的上下文
- 小屏溢出、焦点管理混乱、关闭顺序脆弱

替代方案（已选）：**单模态内导航栈 + 面包屑层级回溯**（Hackolade schema 工具标准做法——"breadcrumb at the top allows to selectively go back up in the hierarchy"）。

### 1.2 技术选型参考

| 参考 | 借鉴点 |
|---|---|
| [React Navigation StackRouter](https://reactnavigation.org/docs/navigation-state/) | `routes[] + index` 状态模型（非纯 push/pop）；每 route 带 key/name/params；reset 截断语义 |
| [WICG Navigation API](https://github.com/WICG/navigation-api) | 应用级导航与浏览器 history 集成；每个 history 条目可携带应用状态；物理返回键逐级回溯 |
| [@kolirt/vue-modal](https://github.com/kolirt/vue-modal) | 命令式打开（任意函数可开、可 await）；模态组隔离；级联保留状态 |
| [HeadlessUI Dialog](https://headlessui.com/vue/dialog) | 焦点管理：打开移入、Tab 循环、关闭恢复 |

### 1.3 适用边界

本架构服务于**模态内的层级导航**（类型 A → 嵌套类型 B → 嵌套类型 C）。跨模态跳转（编辑表 → 查看类型）仍是独立模态叠放（不同元素、天然可回退），不属于本栈。

## 2. 状态模型（单一数据源）

仿 React Navigation：导航状态是**纯数据对象**，渲染完全由它派生，杜绝散落的 `hidden = true/false` 操作。

```js
// 导航状态
{
  routes: [
    { key: "type-Rarity-view", name: "Rarity",   mode: "view",  params: {} },
    { key: "type-DropRange-view", name: "DropRange", mode: "view", params: {} },
  ],
  index: 1,          // 当前聚焦层
}
```

- `routes`：历史层级（栈），每项一条 route
- `index`：当前层下标（光标模型，支持「返回后重新前进」）
- `route.key`：稳定标识（跨渲染用）
- `route.name`：类型名（或未来的其他资源名）
- `route.mode`：`view` | `edit` | `create`（每层独立，编辑态下钻返回后保持）
- `route.params`：层参数（未来承载草稿、滚动位置等每层私有状态）

## 3. 命令式 API

```js
openTypeModal(mode, name)   // 根层打开（从类型库/编辑表进入）：重置导航状态（routes=[根层], index=0）
pushTypeView(name)          // 下钻（嵌套 struct 查看）：截断旧前进分支后 push 新 route
goCrumb(i)                  // 面包屑点击：_restoreRoute(i) 回退到第 i 层并恢复该层草稿快照
goBackType()                // 返回上一层：_restoreRoute(index - 1)（恢复父层快照，不丢编辑态）
cancelTypeModal()           // 取消：非底层回退一层（链保留）；底层若在编辑态 → 退出编辑回只读查看；查看态才关闭
saveType()                  // 保存当前层 → 单层编辑回只读查看（重载最新）；嵌套层回退一层；create 保存后关闭
closeTypeModal()            // 关闭整个模态：清空导航状态（无浏览器历史参与）
```

**取消/保存的层级语义**（用户确认 2026-08-29，2026-08-31 落地修订）：
- 「取消」**不是**关闭整个模态——在嵌套链中间点取消，只回退一层，链保留，父层编辑态不丢
- 「保存类型」保存当前层后回退一层；父层若在编辑中则保持编辑态（草稿不丢）
- **单层（根层）编辑态下，取消与保存都回到该类型的只读查看态**（而非关闭整个模态）——2026-08-31 用户要求「保存/取消应回到上一级只读查看界面」的统一语义
- **关闭整个模态**：view 态 footer 的「关闭」按钮，或 Esc（closeTopModal 统一处理）；**各模态无 ✕ 右上角按钮**（2026-08-31 全部移除，统一 footer 取消/关闭）

未来泛化（同构扩展）：

```js
openModal(group, component, params)  // 仿 @kolirt/vue-modal：任意模态命令式打开，返回 Promise
```

## 4. 浏览器 History 同步（已弃用，改纯响应式）

> **2026-08-31 弃用 History 状态机**：早期按评审 P1 实现「仅前进 pushState，回退/关闭用 history.back()/go() + popstate 恢复」。
> 实测在多态间来回跳转（编辑 → 下钻 → 返回 → 再编辑）时，popstate 反复触发恢复，与响应式渲染叠加导致**死循环**（模态关不掉/回跳异常）。
> 结论：类型模态的层级导航**完全由 Vue 响应式状态驱动**（`typeNav.routes[] + index` 单一数据源），**不写浏览器历史、不监听 popstate**。
> 浏览器物理返回键不参与模态内导航（模态内层级只通过 UI 按钮/面包屑操作），关闭模态也不会污染浏览器历史。

**状态机规则**（纯响应式，无浏览器历史）：

1. **打开根模态**（openTypeModal）：`typeNav = { routes: [root], index: 0 }`
2. **下钻**（pushTypeView）：`routes.push(child)` + `index = 最后`（截断旧前进分支）
3. **取消 / 保存后返回父层**：`index--`（`_restoreRoute(index-1)`，恢复父层草稿快照）
4. **面包屑点击**（goCrumb(i)）：`_restoreRoute(i)` 直接回退多层
5. **关闭整个模态**（closeTypeModal）：`typeNav = { routes: [], index: -1 }`

**草稿保留**：`typeSnapshots`（route.index → typeDraft 快照）——编辑态下钻/返回时保留未保存改动，`_restoreRoute(i)` 恢复对应层快照或重新加载。

```js
// 打开根模态（纯响应式，无 history）
function openTypeModal(mode, name) {
  TYPE_NAV = { routes: [{ name, mode }], index: 0 };
  // ...加载类型详情入 typeDraft
}
function goBackType() {
  if (TYPE_NAV.index > 0) restoreRoute(TYPE_NAV.index - 1);   // 纯状态操作
}
function closeTypeModal() {
  TYPE_NAV = { routes: [], index: -1 };                        // 清空即关闭
}
```

**历史教训（为什么放弃 History 状态机）**：

- 「每次操作都 pushState」→ 历史只增不减、关闭模态后浏览器 Back 复活已关闭模态（评审 P1 曾修订为「仅前进 push，回退/关闭用 back」）
- 修订后（pushState/back/go + popstate）→ 多态间来回跳转触发 popstate 反复恢复，与响应式叠加形成死循环
- 最终方案：类型模态完全脱离浏览器历史，纯响应式单一数据源，杜绝以上两类问题

行为序列（2026-08-31 CDP 真实操作验证）：

| 操作 | 状态变化 | 模态 |
|---|---|---|
| openTypeModal('view','DropRange') | routes=[DropRange(view)], index=0 | 开（只读查看） |
| 编辑 → 下钻 pushTypeView('DamageRange') | routes=[DropRange(edit), DamageRange(view)], index=1 | 开（面包屑显示） |
| 取消（非底层） | index=0（恢复 DropRange 编辑快照） | 开（回 DropRange 编辑态） |
| 保存（根层编辑态） | mode=edit→view + 重载最新 | 开（回只读查看态） |
| 关闭（view 态「关闭」/ Esc） | routes=[], index=-1 | 关 |
| 编辑表（从表详情进入）取消/保存 | detailModal 恢复 | 关编辑表 → 回表详情 |

## 5. 渲染（状态 → UI）

设计稿原为 `renderTypeModal()` 纯函数（读 `TYPE_NAV` → 写 DOM）；**最终实现为 Vue 响应式渲染**（Vue 模板由 `typeNav.routes[]+index` 派生，无需手写 DOM 更新）。每层模式独立处理：

- `view`：只读查看区
- `edit`：编辑表单（保留该层编辑态，返回时仍编辑）
- `create`：新建表单（默认 enum）

面包屑由 `routes` 派生（深度 > 1 显示）：`类型库 / A / 嵌套:B`，每级可点 → `goCrumb(i)`。

## 6. 焦点管理（实施时落实）

- 打开模态：焦点移入模态首个可聚焦元素
- 下钻：焦点进入新层（面包屑区或标题）
- 关闭/返回：焦点恢复到触发元素（来源按钮）

## 7. 与现有代码的关系

- **mockup**（`schema-editor-mockup.html`）：演示原型，曾实现 History 同步；实施时以响应式实现为准
- **最终实现**（`app.js` + `index.html`，Vue 3 全局脚本）：`typeNav.routes[]+index` 存 Vue data，渲染走响应式；**不再同步浏览器 History**（popstate/pushState 相关代码已删除，2026-08-31）

## 8. 验收标准

- [x] 类型查看/编辑模态内，嵌套 struct「查看↗」下钻后，面包屑逐级可返回
- [x] 每层保留独立模式：编辑态下钻返回后仍在编辑态
- [x] 嵌套链中间点「取消」只回退一层（链保留、父层编辑态不丢），底层编辑态「取消」退出编辑回只读查看态，查看态才关闭
- [x] 「保存类型」单层编辑回只读查看态（重载最新）；「关闭」在 view 态 footer，Esc 走 closeTopModal 统一关闭
- [x] 各模态无右上角 ✕ 按钮，取消/关闭统一在 footer（2026-08-31 全部移除）
- [x] 关闭模态后浏览器 Back/Forward 不影响面板（模态不写浏览器历史，无复活问题）
- [x] 编辑表从只读查看（表详情）进入时，取消/保存回到表详情；直接编辑则关闭
- [x] 关闭模态后焦点恢复到触发元素
- [x] 状态模型单一数据源：`typeNav.routes[]+index` 渲染，无散落的 hidden 切换
