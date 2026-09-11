## Context

真实面板前端为 Vue3 无构建扁平结构（`ct/src/ct/web/static/`：`js/core/*` + `js/modules/*` + `styles/*.css`，原生 ESM import，无打包步骤）。现状：`app-shell.js` 渲染「顶栏 + 图标活动栏 + pages + taskbar」；`core/projection.js` 四档投影（1360/960/600）；`modules/schema.js` 1022 行，内含资源→主区→属性页面栈（`history.pushState`/`popstate`）、零散弹窗（快速打开、类型选择器）与 `prompt()` 交互；`core/draft-store.js` 提供 IndexedDB 草稿持久化；模块间用 document 级 CustomEvent（`ct:module`、`ct:schema-resource-toggle`）通信。

对齐基准为定稿原型 `ct/docs/design/responsive-app-shell.html`（1127 行，内联 CSS/JS，e2e 50/50）：侧栏式壳层（≥740 常驻 / <740 汉堡抽屉 + 顶栏）、pane 900 一刀切抽屉、`openMask` 弹窗栈、壳层 draftbar、全屏译文编辑器。原型评审报告（`responsive-app-shell-review.md`）记录的全部修复（含「撤销归零后重做可达」）视为已验收行为。

约束：保持无构建（扁平 static、原生 ESM）；后端 `ct/src/ct/web/*.py` API 不变；浏览器测试为 pytest + Playwright（`ct/tests/web/`）。

## Goals / Non-Goals

**Goals:**
- 壳层、pane 投影、弹窗体系、草稿条、快捷键与原型行为一致
- 弹窗骨架收敛为单一共享契约，存量弹窗全部迁移
- `prompt()` 全部替换为表单弹窗
- 三处主规格（design-system / workbench / web-panel）与本 change delta 一致

**Non-Goals:**
- 不引入前端构建工具或框架层抽象（保持现有 Vue3 挂载 + 原生 JS 模块模式）
- 不改后端 API、CLI、导出管线
- 不做原型之外的移动端增强（无底部导航、无 PWA）
- 不重写资源列表虚拟列表与 fuzzy scorer（仅消费方变化）

## Decisions

**D1. 弹窗栈收敛到 `js/core/dialog.js`（单例层级栈）**
API：`openDialog({ variant: "sm"|"std"|"plan"|"palette", title, body, actions, initialFocus, onClose })` 返回句柄 `{ close, el }`。栈负责：Esc 关最上层、焦点陷阱（过滤 `:not([disabled])`）、标题 id 计数器（`dlg-title-N`）、关闭还焦触发元素、背景点击关闭、对下层内容与 main 应用 inert。宽度变体落 `components.css`（`.ct-dlg-sm/.ct-dlg-plan/.ct-dlg-palette`）。
备选：各模块继续自管弹窗——否决，设计系统规格明确「不得为每个页面复制变体 CSS 和状态逻辑」，且原型评审中 C1/C2 类缺陷证明集中治理有效。

**D2. 壳层重写 `app-shell.js`：侧栏 + 窄屏顶栏 + draftbar 宿主**
`renderShell()` 输出：sidebar（品牌、模块导航、底部「导出文档/帮助/关于」）+ pages + taskbar + draftbar（main 底部，跨模块）。`<740` 由 CSS 显示顶栏（汉堡 + 品牌标记 + 工作区根目录名——原型在窄屏隐藏品牌文字与完整路径，仅保留 logo 与根目录名），汉堡抽屉与 pane 抽屉共用「层」概念：shell 维护 sidebar 抽屉开关，Esc 退栈序由 dialog 栈 > sidebar 抽屉 > pane 抽屉 > 列菜单统一仲裁（dialog 栈最高）。侧栏条目行为与原型一致：再次点击当前 Schema 条目切换资源 pane 开合。模块头按原型落位：Schema 模块头放「删除资源」（danger-ghost，桌面）与「属性」（窄屏开属性抽屉）。
移除：`renderTopbar`（桌面）、健康摘要、`ct-activity-bar` 图标导航、`<600` 底部导航 CSS。
备选：保留常驻顶栏放健康信息——否决，已拍板完全按原型。

**D3. `core/projection.js` 改两断点状态机**
`PROJECTIONS = ["docked", "pane-drawer", "shell-drawer"]`（≥900 停靠 / 740–899 pane 抽屉 / <740 全抽屉 + 顶栏），`subscribeProjection` 保留。pane 停靠态**默认折叠**（首屏编辑器满宽），由编辑器头部「资源面板」按钮与属性活动 Tab 开合；resize 跨断点**只收不展**：≥900→<900 收起双 pane、≥1200→900-1199 收起属性 pane、<740→≥740 关侧栏抽屉，任何方向不自动展开（原型 resize 处理器行为）。`schema.js` 内所有 `window.innerWidth` 阈值判断（`<960`、`>=1360`）改为消费投影状态；移除 `applyView` 的页面栈语义（`pushState`/`popstate`/`history.back` 调用删除），视图切换 = 停靠态 pane 显隐 / 窄屏抽屉开关。
备选：保留四档仅改阈值——否决，规格已废三档语义，保留只会留下死分支。

**D4. `schema.js` 轻拆：新增 `modules/schema-dialogs.js`**
`schema.js` 保留状态机、资源列表、编辑器/检查器渲染、草稿命令流；`schema-dialogs.js` 承接删除资源/字段（D1/D2）、添加字段（F1+F2）、变更计划（P5）、改名、枚举新增值弹窗，全部基于 `core/dialog.js`。纯搬移 + 新增，不做逻辑重构。现有类型选择器提取为可嵌套复用函数供 F1 内嵌。

**D5. draftbar 数据流：CustomEvent 上报，shell 渲染**
schema 模块在 `pushCommand`/`undo`/`redo`/`applyPlan`/持久化失败处 `dispatchEvent(new CustomEvent("ct:draft", { detail: { pending, canUndo, canRedo, warn } }))`；shell 订阅并渲染 draftbar（含归零可重做态、警告态）；draftbar 按钮反向派发 `ct:draft-action`（undo/redo/review）由 schema 模块消费。
备选：草稿状态上移 shell——否决，草稿域归属 schema，shell 保持通用且不感知业务。

**D6. F1 添加字段：前端互斥预校验 + 后端兜底**
弹窗内角色单选（无/I18N/仅服务端）与类型联动：I18N 角色锁定 `string`（类型选择器仅列 string 并提示）、ref 不可勾 vector、vector<Record> 强制定长并要求 `excel_columns`（默认 3）、分隔符由工具内置不提供控件；**server 角色同样禁用 vector**（按原型交互；后端无此约束，禁用是前端保守对齐，不产生非法数据）；主键 `Id` 不出现；Code 代号勾选后锁定名称 `Code`、类型 `string`、角色重置为「无」并禁用 I18N/Server 选项（存在性检查用本地 resources 列表）；强制约束（ref 外键有效性、Code 索引非空唯一）以只读提示呈现、不进草稿命令。字段名行内校验：大写字母开头、不以 `_` 结尾。提交前调 `/api/schema-workspace/validate` 兜底。

**D7. i18n 全屏编辑器复用 wide 宽度变体**
进入前先提交行内编辑（原型行为）；弹窗标题含「主键 · 字段 · 当前语言」，原文只读对照 + 大 textarea（8 行起），保存走现有 `saveEntry`（`confirmed=true` + 状态联动已有逻辑）；取消/Esc/背景关闭不写回。原文列截断检测（两行 `-webkit-line-clamp` + scrollHeight 判定）在页面激活、行渲染、视口 resize 后重跑，被截断单元格挂「展开/收起」尾标。「列」显隐菜单四列（原文/译文/状态/操作），切换表与行更新后随状态过滤一并重放。

**D8. 检查器（属性 pane）保留可编辑表单**
原型属性 pane 为只读概览（footer「修改只进入 Workspace Draft」）——这是静态 mock 未实现编辑的表现，真实面板的 `set_property` 可编辑表单是既有超集且不与原型冲突；本次保留可编辑表单，仅对齐结构（phead + 属性分区 + pfoot）与开合交互（活动 Tab 两态、IDE 式激活态）。

**D9. 测试策略：增量扩展现有矩阵**
`test_shell_browser.py`（侧栏/汉堡/断点穿越/draftbar）、`test_schema_editor_browser.py`（四类弹窗、查看影响预览、⌘Z/⌘P、抽屉 Esc 退栈、ref 跳转）、`test_module_pages_browser.py`（i18n 全屏编辑器、原文展开、列显隐重放）；`test_matrix_browser.py` 断点参数改为 900/740 并补 1200 属性档穿越。原型 e2e（`responsive-app-shell_e2e.py`）中可迁移的断言（B 系列行为）改写为面板用例。

## Risks / Trade-offs

- [桌面首屏双 pane 默认折叠，首次使用者可能找不到资源列表] → 入口 IDE 式高亮 + ⌘P 全局可达 + 帮助弹窗说明；原型已验证该模型，已拍板按原型
- [移除页面栈后浏览器返回手势不再驱动 Schema 视图] → 已拍板接受；弹窗与抽屉提供显式关闭按钮，hash 路由保留模块级导航
- [740–899 区间 pane 全抽屉，宽屏用户信息密度下降] → 原型已验证该区间；抽屉打开即聚焦，关闭即满宽编辑
- [schema.js 拆分与视图模型重写引入回归] → 纯搬移优先、每任务跑全量 pytest；现有浏览器测试护航
- [存量弹窗迁移面广（类型选择器、i18n 三弹窗、快速打开）] → 分两批：新弹窗直接用 dialog.js，存量迁移独立任务，避免一次性大爆炸
- [桌面移除全局健康/工作区路径损失可见性] → 导出页徽标承接健康（真数据）；已拍板接受

## Alignment Notes（原型对齐判定记录）

- **Quick Open 空查询**：原型 mock 无使用历史、空查询显示全量列表；主规格「空查询显示最近打开资源」与归档 delta 一致，判定为 mock 简化而非设计意图，保留最近打开行为。
- **P5 风险徽标**：原型 mock 仅「安全/数据破坏」两态；真实面板接后端五种风险枚举（safe/data-dependent/destructive/incompatible/dependency-breaking），规格按后端枚举保留五种。
- **属性 pane 编辑能力**：原型为只读概览（mock 未实现编辑），真实面板可编辑表单为既有超集，保留（见 D8）。
- **server 角色 × vector**：原型禁用该组合，后端无此约束；按原型禁用（前端保守，不产生非法数据），不写入规格（见 D6）。

## Migration Plan

- 单分支按 tasks 阶段推进：弹窗契约 → 存量迁移 → Schema 弹窗 → 壳层/投影 → draftbar/快捷键 → i18n → 清理；每阶段 `pytest tests/web/` 全绿后进入下一阶段
- 规格同步在 archive 时由 delta 合并进主规格（web-panel-design-system、schema-editor/workbench、web-panel）
- 回滚：纯前端静态资源改动，回退 commit 即恢复；无数据迁移、无 API 变更

## Open Questions

- 无（断点 900/740、抽屉模型、不保留全局工作区信息、i18n 双层编辑均已拍板）
