## Context

动机见 proposal.md - Why。当前工具已有清晰的用例层：`ct/app/`（workspace / options / events / export / validate / template / status / i18n）与事件原语（`ProgressReporter` / `CancelToken`），CLI 只是薄壳。技术栈已调研定稿（见 `tool/docs/research/flask-vue-stack.md`）：Flask 纯 JSON API + Vue 3 无构建（本地托管 `vue.global.prod.js`）。界面高保真原型在 `tool/docs/design/panel-mockup.html`，已定稿并入库。

## Goals / Non-Goals

**Goals:**
- 复用 `ct/app/` 用例层，面板不复制业务逻辑；CLI 与面板共享同一套行为与产物。
- 无前端构建链：浏览器打开即用，Vue 以本地文件方式加载，零 npm。
- 本地单人使用：启动一个进程、一个端口，无鉴权、无排队。
- 导出异步执行，进度可查询、可取消，关闭页面前有提示。

**Non-Goals:**
- 不做提交/推送（策划导出完自行提交）。
- 不做多用户排队或共享服务（本地运行的东西，不涉及排队）。
- 不改变 CLI、导出产物格式、schema 语义。
- 面板不做指定表 / 指定语言导出（固定全量；CLI 保留该能力，后续按需再加）。

## Decisions

### 1. 单进程 Flask：静态托管 + JSON API
用 `ct panel`（Typer 子命令）启动一个 Flask 进程，同时托管前端静态文件与 `/api/*` JSON 接口，避免跨域和双服务管理。

备选：FastAPI（依赖更重，无收益）、pywebview 桌面壳（用户已否决）、前后端分端口（需处理 CORS，无收益）。选定单进程 Flask。

### 2. API 薄封装用例层
每个端点只做参数解析 + 调用 `ct/app/` 用例 + 结果渲染，例如：
- `GET /api/workspace` → `Workspace` + config 摘要 + `ct status` 报告
- `POST /api/export` → 启动导出（`ExportOptions` + `CancelToken`），`GET /api/export/progress` 轮询
- `POST /api/export/cancel` → 取消当前导出（复用取消时不写 `state.json` 的语义）
- `GET /api/i18n/tables` / `GET /api/i18n/entries` / `POST /api/i18n/entry`（读/写 lang 文件，校验后落盘）
- `POST /api/i18n/sync` / `POST /api/i18n/compact` / `GET /api/i18n/status`（复用 sync / compact / status 用例）
- `GET /api/schemas` / `POST /api/schemas`（新增）/ `PUT /api/schemas`（编辑，含保留数据重建模板）/ `DELETE /api/schemas`
- `GET /api/logs` / `GET /api/history`

备选：在 web 层重写校验与导出逻辑 → 双实现必然漂移，拒绝。

### 3. 导出异步执行 + 轮询进度
Flask 请求内用后台线程跑导出管道，`ProgressReporter` 把步骤事件写入内存中的任务状态；前端每 ~500ms 轮询 `GET /api/export/progress`。同一时间只允许一个导出任务（互斥），再点导出返回“已有任务进行中”。

备选：SSE 推送（Werkzeug 开发服务器下长连接不稳定，且轮询对单人本地足够）。选定轮询。

### 4. 关闭页面提示与取消
前端注册 `beforeunload`：导出进行中提示“导出仍在进行”；确认离开后浏览器无法保证请求送达，因此页面内另提供“取消导出”按钮调用 cancel 端点。强杀浏览器场景：后台任务自然跑完并正常写 `state.json`（产物完整，无损坏风险）。

### 5. Vue 3 无构建架构
`web/static/vendor/vue.global.prod.js` 随仓库入库（首次从官方 CDN 下载固定版本），页面用 `createApp` + 模板字符串组织组件；共享组件（modal / cmd-bar / badge / 空态）写成少量全局组件，状态用单个 `reactive` store。规模控制在单页工具可维护范围。

### 6. 设计系统按原型落地
以 `panel-mockup.html` 为准：色板（深林绿 + 金主键）、命令栏规则（左上下文 / 右操作区、主操作固定右下角）、弹窗组件、空态与错误横幅，全部转成 CSS 变量与共享组件，不引入第三方 UI 库。

### 7. 历史记录
新增 `cache/panel_history.json` 保存最近 5 次导出摘要（时间、范围、结果、耗时），面板历史页读取；不依赖 git。

### 8. 启动方式与并发保护
`ct panel` 复用项目 venv（AGENTS.md 安装流程），启动时关闭 Werkzeug reloader（避免双进程）；写 schema / lang / 模板的操作加简单互斥，避免与导出任务并发写文件。

## Risks / Trade-offs

- [Werkzeug 开发服务器并发弱] → 本地单人使用足够；需要时再换 waitress，不影响 API 层。
- [后台线程与取消竞态] → 复用 `CancelToken` 语义：取消后不再写 `state.json`；导出结果以最终产物为准。
- [无构建前端难组织] → 单页工具、组件数量少，用模板字符串 + 少量全局组件控制复杂度；若页面膨胀再引入构建。
- [直接写 schema/lang 文件可能格式漂移] → 一律复用用例层的写入/校验函数，不经手字符串拼装。
- [多人各改一份 gd 造成的合并冲突] → 面板只管本地操作，提交流程不在范围内（既有工作方式，非本变更引入）。

## Migration Plan

无既有面板需要迁移。交付方式：`pip install -e .` 后 `ct panel --port 8000`，浏览器打开即用；CLI 保持可用，可随时回退。

## Open Questions

- 默认端口与是否自动打开浏览器：先默认 8000 并尝试 `webbrowser.open`，失败则打印地址；后续可按团队习惯调整。
- 面板是否需要锁定工作区路径（跨 gd 目录启动）：先支持 `--root` 透传，沿用 CLI 约定，不引入额外状态。
