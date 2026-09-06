# Design: responsive-shell-dialogs

## Context

参照 proposal.md —— 目标是把 `ct/docs/design/responsive-app-shell.html`（单一 HTML 高保真原型，无构建）补全为可演示的弹窗表面，并对齐真实面板的隐式草稿模型。原型已具备 `openMask` 模态骨架（焦点陷阱/Escape/还焦/inert）、抽屉开合、内联 `<svg>` symbol 图标系统。**基线：原型当前为 723 行（提交 ecc3b09），已含 i18n 全屏译文编辑器（`.dialog.dlg-wide` 880px + `openFullEditor` + 失焦即存 + `.src-more` 展开按钮）——本 change 以该版本为基线，弹窗宽度 class 变体沿用其 `.dlg-*` 命名先例。**真实面板 `ct/src/ct/web/static/js/modules/{schema,i18n}.js` 是行为参照：schema 删除/添加直接入草稿 + 行内 plan、i18n 有 picker/progress/compact 弹窗、有 quick-open 调色板。

## Goals / Non-Goals

**Goals**
- 全部弹窗复用同一 `openMask` 骨架，新增内容用 HTML 模板字符串注入
- 草稿表面统一为「状态条 + 审查并应用弹窗」，删除「加入草稿」步骤
- 弹窗变体与真实面板可对应（danger 确认、picker、palette 均有真实参照）

**Non-Goals**
- 不改真实面板 `ct/src/ct/web/static/`（对齐是后续独立 change）
- 不做真实数据/持久化：草稿状态、索引列表、引用关系均为 mock 状态
- 不做虚拟列表渲染（真实 quick-open 的 windowed 渲染留给真实实现）

## Decisions

### DEC1: P5 变更计划 = 模态弹窗（非内联）
真实面板把 plan 内联渲染在编辑器底部；但原型状态条钉在页底，内联区会落在屏幕底部、难以阅读。且草稿是**工作区级**提交时刻，值得一个覆盖屏幕的决策面。→ 640px 模态弹窗；撤销/重做仍留在状态条内联（高频微操不进弹窗）。备选（内联）已否决。**弹窗内容来源**：D1 删除资源弹窗左置三级「查看影响」→ 打开 P5（可选入口，主路径是状态条「审查并应用」）；P5 底部一行小字 hint「计划有效期 2 小时，过期需重新生成」。

### DEC2: 隐式草稿模型
真实面板无「加入草稿」按钮——删除/添加点击即 `pushCommand` 入草稿，草稿只是默认态。原型沿用：D1/D2/F1 主按钮直接「删除/添加字段」，命令入草稿后状态条出现。避免用户多理解一个「草稿」中间态。

### DEC3: 反向引用 = 弹窗内 blocker + 禁用主按钮
真实面板做法是行内报错「无法删除：仍被引用…」并拒绝入草稿。原型用弹窗演示两种状态（无引用可删 / 有引用 blocker 禁用），比行内报错更可演示，且不弱化安全（同样不提供级联删除）。

### DEC4: 弹窗变体宽度表
| 变体 | 宽度 | 初始焦点 | 对应 |
|---|---|---|---|
| danger 确认（D1） | min(560px,100vw-40px) | 取消 | schema delete |
| danger 确认小号（D2） | min(420px,92vw) | 取消 | schema delete field |
| 表单（F1） | min(560px,100vw-40px) | 字段名 | schema add field |
| 类型选择器（F2） | min(420px,92vw) | 搜索框 | schema type-picker |
| 变更计划（P5） | min(640px,100vw-40px) | 取消 | schema review-plan |
| picker（P1） | min(560px,100vw-40px) | 搜索框 | i18n table picker |
| 静态（I1/I2） | min(560px,100vw-40px) | 关闭 | 原型新增 |
| 调色板（Q1） | min(480px,92vw) | 搜索框 | schema quick-open |

宽度用 **class 变体**实现，命名沿用原型现有 `.dialog.dlg-wide`（880px，i18n 全屏编辑器已用）的 `.dlg-*` 前缀：`.dialog.dlg-sm{width:min(420px,92vw)}`、`.dialog.dlg-plan{width:min(640px,100vw-40px)}`、`.dialog.dlg-palette{width:min(480px,92vw)}`；默认 `.dialog` 即标准 560。不用内联 `max-width` 覆盖——`.dialog` 的 `width:min(560px,…)` 会被 max-width 直接压小，无法精确复现各变体的 `min(…,92vw)` 组合（如 Q1 在 375px 屏应 345px，max-width 只能得到 335px）。

### DEC5: Q1 快速打开入口 = rhead ⌕ + 全局 ⌘P
真实面板的 quick-open 在常驻 workspace 头部；原型等价常驻区是 rhead（编辑器列恒可见），故在 `#res-toggle` 左侧加 `#quick-open` ibtn。注册全局 `Cmd/Ctrl+P`（防浏览器默认打印）。窄屏不 gate（蓝牙键盘移动端可用）。

### DEC6: 草稿状态条 = Schema 页 flex 底部行
`#page-schema` 已是 `display:flex;flex-direction:column`，mhead + wb(flex:1)。新增 `draftbar` 作 `flex:0 0 auto` 最后一行，仅在有命令时显示（`hidden` 切换 + 淡入）。持久化警告态切换为 warn 底色。撤销/重做按钮随命令数 disabled。**成功态**：应用成功后 draftbar 槽位短暂切换为 accent 底「已应用：Item · Quest」+ 3s 自动消失，再隐藏——即 spec/task 的「原位（编辑器内）显示已应用摘要」落地位置。

### DEC9: P6 放弃草稿二次确认
「放弃草稿」是清空全部未应用命令的不可逆动作，打开小号弹窗（`.dialog.dlg-sm`）：「放弃 N 条未应用变更？此操作不可撤销 [取消] [放弃]」，danger-ghost 触发，初始焦点在「取消」；确认后命令清空、状态条消失。**嵌套顺序**：P6 由 P5 的「放弃草稿」打开，是 P5 之上的新弹窗层——Escape 与遮罩点击必须先关 P6，再按一次才关 P5（顶层优先）。

### DEC7: 图标资产
新增 `<symbol id="i-search">`（放大镜）供 Q1 与搜索框统一；无需引入新图标库。

### DEC8: 低宽度/矮视口适配（缺口修复）
宽度已由各变体的 `min(…, 100vw-40px / 92vw)` 兜底；垂直与排布是缺口，修复如下（已按调研核实）：
- `.dialog` 改 `display:flex;flex-direction:column` + `max-height:calc(100svh - 32px)`；`.dbody` 改 `flex:1 1 auto;min-height:0;max-height:none`（`min-height:0` 是嵌套滚动容器成立的关键，flex 默认 `min-height:auto` 会撑开不滚）——解决横屏矮窗 340px > 320px 的裁切
- `.mask` 加 `overflow-y:auto` **且** `.dialog` 加 `margin:auto`：网格 `place-items:center` 在元素高于容器时顶部溢出不可滚动是已知缺陷（margin:auto 既居中又保证可滚达全部内容）
- 高度单位用 `svh`（优于 `dvh`）：iOS Safari 地址栏、Android 软键盘弹起时 dvh 会跳动，svh 恒保证可见区内适配；Chrome 108+/FF 101+/Safari 15.4+ 均支持
- `.dfoot` 允许 `flex-wrap:wrap`（≤3 键窄屏换行不溢出）
- `draftbar` 允许 `flex-wrap:wrap` + 文本 `min-width:0` 可省略
- F1 角色单选、P1 行内容允许换行
- 立场：保持居中模态，不做底部抽屉改造（符合「窄屏不穿帮」原则）

## Risks / Trade-offs

- [弹窗与抽屉 z-index 竞争（P5/mask=80 > 侧栏抽屉=70 > 面板抽屉=50）] → 已在现有规范内，无新竞争；Escape 按浮层栈关最上层——**现有全局处理 `document.querySelector('.mask')` 取的是文档序第一个 mask（=最底层），须改为 `querySelectorAll('.mask')` 取末位**（当前单弹窗不触发，P5→P6 嵌套时会把 P5 先关掉；见 DEC9 嵌套顺序）
- [`openMask` 内 HTML 模板字符串较长，XSS 面] → 原型 mock 数据均为内部常量，无外部输入注入；真实实现时须 escape
- [P5 弹窗偏离真实面板内联布局] → 有意为之（DEC1），spec 与真实面板对齐留待后续 change，spec 已按弹窗行为撰写
- [移动端小号弹窗在 <740 无顶栏时遮罩贴顶] → `.mask` 居中于视口，与侧栏抽屉（z=70）不冲突，已在断点验证范围

## Migration Plan

- 纯原型单文件改动；无需部署/回滚（文件可随时 git 还原）
- 实施顺序：样式与 symbol → 草稿状态条 → 弹窗组（D1/D2→F1/F2→P5→P1→I1/I2→Q1）→ 接线项 → Playwright 全量验证
- 后续：把 spec 需求对到真实面板时，以本 change 的弹窗/状态条为视觉基准

## Open Questions

- 快速打开是否要虚拟列表：原型用全量 mock（≤9 行），真实实现再按 windowed 渲染——已推迟
- I3 导出文档真实 URL：原型阶段无 URL，仅标记外部链接——已推迟
