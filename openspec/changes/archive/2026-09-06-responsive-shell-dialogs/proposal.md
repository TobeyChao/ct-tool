## Why

响应式高保真原型（`ct/docs/design/responsive-app-shell.html`）的交互大多是静态的：删除资源/字段、添加字段、类型链接、i18n 选择表、侧栏「关于/帮助」等按钮点击无任何可见行为；且 Schema 删除/添加按钮尚未接线到真实面板的隐式草稿模型（真实面板点击即入 Workspace Draft，无显式确认步骤）。原型是真实面板的高保真参照物，需补全弹窗表面并接线草稿交互，才能作为后续实现的对齐基准。

## What Changes

- 补全弹窗系统（复用 `openMask` 骨架）：
  - **D1 删除资源** / **D2 删除字段**：danger 确认；存在反向引用时显示 blocker 并禁用主按钮（不提供级联删除）
  - **F1 添加字段** + **F2 类型选择器**：字段表单（名称/类型/角色单选互斥/约束），类型选择器搜索+分组点选回填
  - **P5 变更计划**：审查并应用的主决策面（640px），风险徽标 + 影响列表 + 阻塞项 + 应用按钮（blocked 禁用），成功后原位显示已应用
  - **P1 选择表**（i18n）：照真实面板 picker（搜索 + 状态 pill + 计数 + 行选中回填）
  - **I1 关于** / **I2 帮助与反馈**：标准骨架静态弹窗
  - **Q1 快速打开 ⌘P**：rhead ⌕ + 全局快捷键，窄调色板，输入即滤 + ↑↓/Enter
- **隐式草稿模型**：Schema 删除/添加按钮现状为纯静态，接线为「点击即入草稿」（不设「加入草稿」显式步骤——原型本就无此按钮，真实面板也无）；新增**草稿状态条**（编辑器页底：N 条未应用变更 · 撤销/重做 · 审查并应用→P5；持久化失败时警告态）
- **I3 导出文档**：外部跳转，不弹窗（`title="外部文档"`）
- 新样式与资产：`.btn-danger`(+disabled)、`draftbar`、`i-search` 放大镜 symbol
- 非弹窗接线项：字段上移/下移、译文保存、重新导出、pills 过滤、资源/日志搜索、前往导出跳转

## Capabilities

### New Capabilities
- 无（不引入新能力路径；本次需求全部落进现有设计系统能力）

### Modified Capabilities
- `web-panel-design-system`：为共享设计系统补充对话组件变体契约（danger 确认 / 表单 / picker / 调色板）、隐式草稿栏表面（draft status bar）与快速打开调色板（⌘P）的需求；这些需求同时约束真实 Web Panel 的后续对齐。

## Impact

- 仅改动设计原型：`ct/docs/design/responsive-app-shell.html`（HTML/CSS/JS 单一文件，无构建；**基线为当前 723 行版本，含 i18n 全屏译文编辑器**）
- 不触及 `ct/src/ct/web/static/`（真实面板）与任何 Python 代码；真实面板对齐为后续独立 change
- 新增可见资产：`.btn-danger` 实心红按钮、`draftbar` 样式、`i-search` SVG symbol、`.dlg-sm/.dlg-plan/.dlg-palette` 弹窗宽度变体类（沿用现有 `.dlg-wide` 前缀）
- 验证：Playwright（`ct/.venv`）+ 截图像素检查
