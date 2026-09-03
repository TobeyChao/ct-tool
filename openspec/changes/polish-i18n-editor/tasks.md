## 1. 弹窗关闭修复

- [x] 1.1 将 `data-close` / `data-confirm-compact` 的判定从 `btn.dataset.close` 改为 `"close" in btn.dataset`（`confirmCompact` 同理），并让 `closeAllDialogs()` 调用 `render()`；浏览器实测选表/进度/清理三弹窗均可通过按钮、背景、Esc 关闭且无残留遮罩
- [x] 1.2 在 `tests/web/test_module_pages_browser.py` 新增进度弹窗打开→关闭（按钮 + 背景）的断言，验证关闭后 `.ct-dialog-mask` 不存在

## 2. 长文本两态编辑

- [x] 2.1 在 `i18n.js` 引入 `state.editingKey`，长条目渲染为 `trans-preview`（两行截断、点击展开）+ `is-area` textarea（blur 收起、保留草稿）；短条目保持单行 input；原文列 `src-text` 在编辑时加 `.expanded`
- [x] 2.2 在 `components.css` 移植 legacy 的 `trans-preview` / `src-text` / `trans-cell` / `src-cell` / `is-area` 样式并适配当前 design token；Playwright 实测长条目点击展开为 textarea、blur 收回到两行预览

## 3. 带 hash 刷新空白修复

- [x] 3.1 将 `module-registry.js::currentModule()` 正则改为 `/#\/([a-z0-9]+)/`；Playwright 验证直连 `#/i18n` 与刷新后条目表正常渲染

## 4. 选择翻译表弹窗重设计

- [x] 4.1 重写 `renderPickModal`：仅列 `has_i18n` 的表、搜索输入（自动聚焦、复用 fuzzy）、胶囊状态筛选（全部/有缺失/有待审/已译完，按 `/api/i18n/status` 按表计数聚合）、无匹配空态、footer 键盘提示
- [x] 4.2 弹窗内键盘（↑/↓/Enter/Esc）delegated 处理并 `preventDefault` 防止与全局冲突；Playwright 验证搜索过滤、状态筛选、空态、键盘选定与 Esc 关闭
- [x] 4.3 在 `tests/web/test_module_pages_browser.py` 新增选表弹窗测试：仅显示含 i18n 的表、搜索收窄、无匹配空态出现

## 5. 条目表样式统一

- [x] 5.1 `.ct-row-ops` 改为左对齐；`.ct-data th` 保持左对齐（含“操作”列）；原文/译文两列统一 `min-width` 等宽；保存按钮等宽 + stale 态 accent 实底；Playwright 断言按钮与“操作”表头左缘对齐、原文/译文列宽相等

## 6. 验证收尾

- [x] 6.1 运行 `cd ct && pytest tests/web/` 全绿（含既有 i18n/模块/baseline 测试），并 `git diff --check` 干净
- [x] 6.2 `openspec validate polish-i18n-editor --strict` 通过，更新任务勾选状态
