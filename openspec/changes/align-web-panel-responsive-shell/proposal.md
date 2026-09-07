## Why

响应式高保真原型 `ct/docs/design/responsive-app-shell.html` 已定稿（评审报告全部修复，e2e 50/50 通过），归档 change `2026-09-06-responsive-shell-dialogs` 当时明确「真实面板对齐为后续独立 change」。真实面板（`ct/src/ct/web/static/`）与原型存在两level差距：**壳层架构分歧**（原型为侧栏式 + 900 一刀切抽屉投影，真实面板为顶栏 + 图标活动栏 + 三档投影 + 底部导航）与**表面缺口**（添加字段/删除确认/变更计划等弹窗、壳层草稿条、统一 Dialog 契约、⌘Z 快捷键、关于/帮助、全屏译文编辑器）。此外归档 change 中面向真实面板的 delta 规格从未同步到主规格。经讨论拍板：**完全按原型实现，不保留手机底部导航，不全局保留工作区路径与健康摘要，pane 投影采纳原型 900 一刀切**。

## What Changes

- **壳层重写（BREAKING 交互模型）**：
  - 桌面 ≥740：无顶栏，纯侧栏（logo + 模块文字导航 + 底部「导出文档 / 帮助与反馈 / 关于」）；不展示全局工作区路径与健康摘要
  - <740：顶栏出现（汉堡 + 品牌标记 + 工作区根目录名），侧栏变汉堡抽屉（backdrop + Esc 退栈）；**不做底部导航**（移除现有底部导航实现）
  - 壳层 draftbar：main 底部常驻状态条，跨模块可见（N 条未应用变更 · 撤销/重做 · 审查并应用；持久化失败警告态；应用成功短暂显示「已应用」清单；归零后重做仍可达）
- **pane 投影改 900 一刀切**：≥900 资源/属性 pane 以可折叠列停靠且**默认折叠**（首屏编辑器满宽，经编辑器头部「资源面板」按钮与属性活动 Tab 开合）；<900 一律抽屉化（transform 滑出 + backdrop + 关起即 inert）；窗口 resize 跨断点**只收不展**（≥900→<900 收双 pane、≥1200→900-1199 收属性 pane，不自动展开）；Esc 退栈序 dialog > 侧栏抽屉 > 面板抽屉 > 列菜单；移除现有「资源→主区→属性」页面栈（history.pushState/popstate）与 1360/960/600 三档投影
- **字段表窄屏形态**：<900 转字段卡片分组（表头隐藏，名称+操作/类型/Excel/角色分区，操作常显）；≥900 保持表格（容器内横滚 + 操作列固定宽）
- **统一 Dialog 契约**：新增 `js/core/dialog.js` 弹窗栈管理器（焦点陷阱过滤 disabled、唯一标题 id、Esc 逐层退栈、关闭还焦触发元素、背景点击关闭、inert 管理、宽度变体 sm/标准/plan/palette）；现有零散弹窗（类型选择器、i18n 选择表/进度/清理确认、快速打开）迁移到该契约
- **弹窗表面补齐（原型定稿交互）**：
  - D1 删除资源 / D2 删除字段：danger 确认，动态反向引用 blocker 列表（不提供级联删除），初始焦点在「取消」；D1 另提供「查看影响」以预览模式打开变更计划弹窗（命令未入草稿、应用/放弃禁用）；替换现状「✕ 直接删 / 被引用行内报错」
  - F1 添加字段：名称 + 角色单选互斥（无/I18N/仅服务端）+ F2 类型选择器内嵌回填 + vector 修饰符（定长/变长形态、Record 定长需 excel_columns、ref 不可 vector）+ Code 代号字段（固定名/一表至多一个）+ 只读强制约束提示；主键 `Id` 不通过添加字段指派
  - P5 变更计划弹窗（640px）：风险徽标 + 按产物影响清单 + 阻塞项（位置/样例值）+ 计划有效期提示（2 小时）；blocked 禁用应用；应用成功草稿条显示「已应用」清单；「放弃草稿」小号确认并连关计划弹窗
  - 改名字段 / 枚举新增值：表单弹窗替换浏览器 `prompt()`
  - I1 关于 / I2 帮助与反馈：标准静态弹窗；I3 导出文档为外部链接不弹窗
  - i18n 全屏译文编辑器：行内编辑保留（失焦保存），译文框右下角全屏角标打开大弹窗（原文只读对照 + 大 textarea），保存写回并联动状态徽标；原文列两行截断配「展开/收起」尾标；「列」显隐菜单（原文/译文/状态/操作）跨切表重放
- **快捷键**：⌘Z / ⇧⌘Z 草稿撤销/重做（全局，草稿模块）；⌘P 快速打开保持
- **不搬项**：原型 mock 专属逻辑（导出页假数据联动）；src-more 按「两行预览 + 展开/收起」交互落实到 i18n 原文列（规格已有行为，原型给交互样式）

## Capabilities

### New Capabilities

- 无（不引入新能力路径；全部落进现有能力）

### Modified Capabilities

- `web-panel-design-system`：MODIFIED「Unified application shell」（侧栏式壳层 / 汉堡抽屉 / 移除底部导航 / 移除全局健康与工作区路径展示）；ADDED「Dialog variant contract」「Implicit workspace draft surfacing（含 ⌘Z/⇧⌘Z）」「Change plan review dialog」「External documentation link」「About and Help dialogs」（吸收归档 change 未同步 delta 并按原型修订 draftbar 位置与宽度变体）
- `schema-editor/workbench`：MODIFIED「Adaptive 3/2/1 pane projection」（改 900/740 两断点抽屉模型 + pane 默认折叠 + resize 只收不展，废弃三档投影与底部导航）；MODIFIED「Side area interaction states」（可折叠停靠默认收起 + 抽屉 overlay，废弃「不得 overlay/滑出屏」限制）；MODIFIED「Stable table layout and small-screen representation」（窄屏转字段卡片分组，废弃紧凑行分组表述）；MODIFIED「Global resource Quick Open」（全局可用 + 自动切模块 + Esc 先清查询）、「Schema workbench resource editing」（ref 引用链接跳转）；「Add-field role and constraint mutual exclusion」已存在，本次为落地实现
- `web-panel`：MODIFIED「面板服务与工作区」（工作区根目录名仅 <740 顶栏呈现，导出页呈现工作区身份）、「翻译管理与编辑」（原文展开尾标 + 全屏对照编辑 + 切表重放）；ADDED「翻译表列显隐」

## Impact

- `ct/src/ct/web/static/js/app-shell.js` — 壳层重写（侧栏 / 窄屏顶栏 / 汉堡抽屉 / draftbar 宿主 / 移除底部导航）
- `ct/src/ct/web/static/js/core/projection.js` — 四档投影改两断点模型；`js/core/dialog.js` 新增弹窗栈
- `ct/src/ct/web/static/js/modules/schema.js` — 视图模型重写（页面栈→抽屉）、prompt 替换、新弹窗接线；轻拆 `js/modules/schema-dialogs.js`
- `ct/src/ct/web/static/js/modules/i18n.js` — 全屏译文编辑器 + 弹窗契约迁移
- `ct/src/ct/web/static/styles/{layout,components}.css` — 侧栏/抽屉/断点/宽度变体/draftbar/danger 按钮样式
- 不触及 Python 后端（`ct/src/ct/web/*.py` API 无变化）；不触及 CLI/导出管线
- 验证：`ct/tests/web/` 浏览器测试矩阵扩展（弹窗、抽屉、draftbar、快捷键），按 workbench 视口矩阵（1600×900 / 1360×768 / 1280×720 / 960×640 / 720×460 / 390×844 及 100%/125%/150% 缩放）验收
