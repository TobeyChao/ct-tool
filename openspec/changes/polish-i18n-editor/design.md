## Context

参见 proposal.md — Why。翻译页签（`ct/src/ct/web/static/js/modules/i18n.js`，canonical-only 改版后的新实现）有四处回归 + 一处样式问题，均在纯前端。后端 `/api/i18n/status` 已按语言 × 表返回计数（`tables.{table}.{missing,stale,translated,total}`），`/api/i18n/tables` 返回 `has_i18n/field_count/i18n_count`，前端可直接消费，无需后端改动。

## Goals / Non-Goals

**Goals**
- 弹窗（选表/进度/清理）可可靠关闭（按钮、背景、Esc），不残留遮罩。
- 长文本条目恢复“两行预览 → 点击展开 textarea → 失焦收起”，满足 web-panel spec 已有需求。
- `#/i18n` 直连/刷新后模块正常挂载。
- “选择翻译表”成为可搜索、可状态筛选、仅含 i18n 表的选择器。
- 条目表全部左对齐、原文/译文等宽、保存按钮等宽 + stale accent、垂直居中。

**Non-Goals**
- 不改后端 API 与数据模型。
- 不做翻译条目分页/虚拟化（当前表规模小）。
- 不引入图标库或新依赖（保持无构建、扁平静态分发）。

## Decisions

### D1：弹窗关闭守卫用属性存在性判断
裸 `data-close` / `data-confirm-compact` 属性产生 `dataset.close === ""`（falsy），`if (btn.dataset.close)` 永不成立。改为 `"close" in btn.dataset` / `"confirmCompact" in btn.dataset`（同时覆盖空字符串与显式值）。背景点击路径统一走 `closeAllDialogs() → render()`，保证状态与 DOM 一致。
- 备选：给属性显式赋值（`data-close="1"`）——改动面更大且易漏，弃用。

### D2：长文本两态用单一 `editingKey` 状态
恢复 legacy 的 `trans-preview`（两行截断、`-webkit-line-clamp: 2`、点击进入编辑）+ `is-area` textarea（blur 收起）模式，`state.editingKey` 记录当前编辑条目 key；原文列 `src-text` 在 `editingKey === key` 时加 `.expanded` 展开。草稿仍在 `state.drafts`（delegated `input` 监听已存在），blur 只收起视图不丢草稿，显式“保存”按钮落盘。
- 备选：行内常驻 textarea（现状）——无法扫读，弃用。
- 备选：自动高度 textarea——增加复杂度，两态已满足，弃用。

### D3：选表弹窗改为可搜索列表 + 胶囊筛选
`renderPickModal` 重写为：搜索输入（自动聚焦）→ 胶囊状态筛选行（全部/有缺失/有待审/已译完）→ 竖排行列表（仅 `has_i18n` 的表，行含表名 + `· N 字段 · i18n M` + 聚合状态标签）→ 空态 → footer 键盘提示（`↑↓ 选择 · ↵ 确定 · Esc 关闭`）。搜索复用现有 `fuzzy.js`（与 Quick Open 一致）；状态筛选按 `/api/i18n/status` 的按表计数聚合。键盘在弹窗内 delegated 处理（↑/↓/Enter/Esc）。
- 备选：保留胶囊换行——表多时无法检索，弃用。
- 备选：radio 分段按钮——用户明确要胶囊，弃用。

### D4：条目表全左对齐 + 原文/译文等宽
`.ct-data th` 保持左对齐（含“操作”表头），`.ct-row-ops` 从 `text-align: right` 改为 `text-align: left`；原文/译文两列统一 `min-width`（如 240px）保证等宽视觉；保存按钮 `min-width` 等宽（`保存` 与 `确认并保存` 同宽），stale 态按钮加 accent 实底类；`td { vertical-align: middle }` 已保证行内垂直居中（含长文高行）。

### D5：`currentModule()` 正则修正
`/#\/([a-z]+)/` → `/#\/([a-z0-9]+)/`，使 `#/i18n` 解析为 `i18n` 而非 `i`。路由核心 `core/router.js` 用 `split` 解析、不受影响；仅 module-registry 的初始挂载路径有此正则。

## Risks / Trade-offs

- [长文本两态依赖 `-webkit-line-clamp` 预览] → 仅影响预览截断，编辑态/保存不受影响；Chrome/Edge 均支持，与既有 `src-text` 用法一致。
- [选表弹窗键盘与全局 Quick Open 快捷键冲突] → 弹窗打开时（`pickTable` 为真）先消费 keydown 并 `preventDefault`，不冒泡到全局。
- [状态筛选依赖 `/api/i18n/status` 按表计数形状] → 形状已确认（`tables.{table}.{missing,stale,...}`）；若后端字段变化，聚合函数集中在一处便于调整。

## Migration Plan

纯前端改动，随静态文件即时生效（面板无构建、按请求读盘）。无数据迁移；回滚即还原 i18n.js / components.css / module-registry.js。

## Open Questions

无。
