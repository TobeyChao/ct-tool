## Why

canonical-only 改版后，翻译页签（i18n 编辑器）出现多处回归：进度弹窗无法关闭、长文本退化为固定 textarea（丢掉了 spec 要求的“两行预览 + 展开对照”）、带 hash 刷新后整页空白，且“选择翻译表”的胶囊列表无法检索、混入无 i18n 的表、保存按钮与“操作”表头错位。

## What Changes

- **修复弹窗关闭**：`data-close`/`data-confirm-compact` 裸属性导致的 falsy 判定失效（关闭/取消/确认清理全部失效），以及点击背景只重置状态不重渲染。
- **恢复长文本两态编辑**：长条目（原文或译文 > 40 字符）以两行截断预览呈现，点击进入编辑时展开为 textarea、失焦收起；短条目保持单行输入。满足 `web-panel` 已有需求“长文本展开对照”。
- **修复带 hash 刷新空白**：模块注册器 `currentModule()` 的正则 `[a-z]+` 不匹配含数字的 `i18n`，导致 `#/i18n` 直连/刷新后模块不挂载。
- **重设计“选择翻译表”弹窗**：仅列出含 i18n 字段的表；新增名称搜索（自动聚焦）+ 胶囊状态筛选（全部 / 有缺失 / 有待审 / 已译完）+ 无匹配空态 + 键盘导航（↑↓/Enter/Esc）+ 页脚键盘提示。
- **条目表样式统一**：全部左对齐（含“操作”表头与按钮）、原文/译文两列等宽、保存按钮等宽且 stale 态用 accent 强调、按钮行内垂直居中。

## Capabilities

### New Capabilities
<!-- 无新增能力 -->

### Modified Capabilities

- **web-panel**：新增“翻译表选择器”需求（仅列含 i18n 字段的表、支持名称搜索与状态胶囊筛选、无匹配空态）；长文本两行预览/展开与弹窗可关闭为已有需求，本次为回归修复，不新增需求条目。

## Impact

- `ct/src/ct/web/static/js/module-registry.js`：`currentModule()` 正则修正（1 行）。
- `ct/src/ct/web/static/js/modules/i18n.js`：弹窗守卫、背景关闭重渲染、长文本两态（`state.editingKey`）、选表弹窗（搜索/筛选/空态/键盘/footer）、条目表样式类。
- `ct/src/ct/web/static/styles/components.css`：新增 `ct-picker` 系列、`trans-preview`/`src-text`/`is-area`（移植 legacy 并适配 token）、操作列左对齐与等宽。
- 后端无改动；`/api/i18n/status` 与 `/api/i18n/tables` 已提供按表计数，前端聚合即可。
