## 1. 后端骨架与基础设施

- [ ] 1.1 新增 `ct panel` 命令（Typer）：加载 Workspace，启动 Flask（静态 + API），关闭 reloader，支持 `--root` / `--port` 透传
- [ ] 1.2 建立 `ct/web/` 模块：统一响应包装 `{ok, data|error}`，异常统一转可读错误（复用 `ValidationIssue.render`）
- [ ] 1.3 前端静态目录与本地托管：下载固定版本 `vue.global.prod.js` 入库，Flask 托管 `web/static/`
- [ ] 1.4 单任务互斥：同一时间只允许一个导出任务；schema/lang/模板写操作与导出互斥

## 2. 工作区与状态 API

- [ ] 2.1 `GET /api/workspace`：返回工作区路径、config 摘要、`ct status` 报告（数据变更 / 模板漂移 / 未跟踪 / 缺失）
- [ ] 2.2 工作区缺失 / `config/global.yaml` 缺失时返回明确错误与修复指引

## 3. 导出

- [ ] 3.1 `POST /api/export`：构造 `ExportOptions`（全量 + 强制重建 flag）与 `CancelToken`，后台线程执行导出管道
- [ ] 3.2 `GET /api/export/progress`：返回当前步骤、状态、错误摘要；`POST /api/export/cancel` 取消任务
- [ ] 3.3 导出完成后写入 `cache/panel_history.json`（最近 5 次：时间、范围、结果、耗时）
- [ ] 3.4 验证取消语义：取消后不写 `state.json`，与 CLI 行为一致

## 4. 翻译 API

- [ ] 4.1 `GET /api/i18n/tables` 与 `GET /api/i18n/entries`：按表 / 语言 / 状态筛选，状态机计算与 CLI 一致
- [ ] 4.2 `POST /api/i18n/entry`：写 `text` + `confirmed`，落盘对应 `i18n/{lang}/{table}.json`
- [ ] 4.3 `POST /api/i18n/sync`（当前表所有语言）与 `POST /api/i18n/compact`（orphan 物理清理）
- [ ] 4.4 `GET /api/i18n/status`：按语言 / 表返回 translated / missing / stale 计数与进度

## 5. 表格管理 API

- [ ] 5.1 `GET /api/schemas`：列表（含模板状态）与详情（字段定义、主键、文件路径）
- [ ] 5.2 `POST /api/schemas`：新增（写 schema YAML + 生成 Excel 模板）
- [ ] 5.3 `PUT /api/schemas`：编辑（schema 校验 + 保留数据重建模板，update-header 语义）
- [ ] 5.4 `DELETE /api/schemas`：删除 schema 与模板（弹窗确认后调用）

## 6. 日志与历史 API

- [ ] 6.1 日志采集：操作过程中按模块（导出 / 校验 / i18n / 模板 / 系统）采集，`GET /api/logs?module=` 返回
- [ ] 6.2 `GET /api/history`：读取 `cache/panel_history.json`

## 7. 前端页面

- [ ] 7.1 全局框架：顶栏 + 页签导航 + 全局错误横幅 + 单一 reactive store + hash 路由
- [ ] 7.2 导出页：命令栏（强制重建 + 开始导出）、7 步进度面板、取消按钮、`beforeunload` 关闭提示
- [ ] 7.3 翻译页：表选择弹窗、语言/状态筛选、行内编辑（长文本两行预览 + 点击展开对照）、同步全部语言、清理无主条目、全部表进度弹窗
- [ ] 7.4 表格管理页：列表（搜索 + 模板状态筛选）、详情 / 新增 / 编辑 / 删除弹窗、模板漂移联动重建
- [ ] 7.5 日志页（模块筛选、自动滚动）与历史页（最近 5 次）

## 8. 集成与测试

- [ ] 8.1 pytest 覆盖 API 层：workspace / export / i18n / schemas / logs / history 的正常与错误路径
- [ ] 8.2 前端手工验收：对照 `panel-mockup.html` 逐页核对交互与空态/错误态
- [ ] 8.3 使用文档：`tool/docs` 增加面板启动与使用说明（Windows / macOS）
- [ ] 8.4 全量回归：pytest 全绿，CLI 行为与产物不变
