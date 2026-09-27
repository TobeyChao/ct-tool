## Context

动机见 proposal.md。以下为本次规划时的源码观察，不等于运行验收：

- 本地 main 为 `8dc7b81`，当前分支为 `feat/native-workbench-cutover`；`ct/` 相对 main 仅文档变化，Web 代码可直接作为迁移基线。工作树存在其他任务的未提交改动，实施必须重新读取并记录采纳版本。
- Flask 入口为 `ct/src/ct/web/app.py`，Schema API 为 `schema_workspace_api.py`；后者仍包含命令重放、守卫与发布编排。前端位于 `ct/src/ct/web/static/`，现有 API 以 `{ok,data}` / `{ok:false,error,...}` 封装。
- `native/crates/ct-app/` 已有主要用例，worker methods 是 stdio DTO 适配。`workspace.snapshot` 只有计数/恢复状态，`workspace.status` 合并 missing/changed；`schema.candidate` 没有完整资源，`schema.save` 只回 revision，不能直接替代现有 Web API。
- Web 草稿为 IndexedDB `ct-drafts` / `ct-draft-v2`，key 为工作区路径；Web 命令用 `type`，worker 用 `kind`。候选预检存在只发 commands 的路径，需要补上基线和代次。既有 native hash 对照测试为守卫接续提供基础，但仍需浏览器端实测。
- Web 历史为配置 cache_dir 下 `panel_history.json`，native 为 `history.json` / `desktop-history/1`。两侧采用 `.ct/export.lock`、`.ct/export-publication.json` 与 `canonical-cache/1`，格式同名尚不足以证明恢复兼容。
- native `ct panel` 当前只是退出码 1 的迁移提示。原生发行流程已有无 Python 自检，但没有 Web 自检。S/M/L 与部分 golden 生成脚本仍使用 Python；浏览器验收仍用 pytest + Python Playwright。

## Goals / Non-Goals

**Goals:**

- 一个原生 `ct` 可执行程序提供 CLI、stdio worker 和本地 HTTP 面板；生产运行不要求 Python、Node、Flutter 或前端开发服务器。
- 以 main Web 的业务、交互、布局和故障处理为验收对象，复用本分支 Rust 内核；跨入口业务只存在于 canonical Rust 用例。
- 开发与验收链的必要脚本同样去 Python，保留可追溯的静态证据与可再生夹具。

**Non-Goals:**

- 不实现双内核、WASM、云服务、多人编辑、前端框架重写，也不新增 Web 部署页面。
- 不改变 Flutter 产品方向；不复制 worker NDJSON 方法作为新的浏览器公共协议。
- 不承诺跨浏览器 origin 自动搬运 IndexedDB、不自动修复未知历史事务、不批量清理无关实验目录。

## Decisions

### 1. Rust HTTP 服务直接使用 ct-app

新增 `native/crates/ct-web/`，负责路由、静态资源、HTTP DTO 和服务生命周期。`ct-cli` 的 panel 子命令进入该服务。耗时同步用例在有界后台执行器运行，不占用 HTTP 接收/取消处理线程；同一工作区的写互斥仍由 ct-storage 的跨进程锁兜底。

从 worker 抽取确有复用价值的任务登记、取消令牌与事件模型到传输无关模块（可放 ct-app 或小型公共 crate），stdout 信封、seq 和连接状态留在 worker。HTTP 不依赖 worker 的 stdio session；两种传输均调用同一业务用例。变更共享代码时维持 worker v1 和 Flutter 契约测试。

选择理由：最终只有一个内核，HTTP 直接调用省去额外进程与二次编码。保留 Flask 不满足零 Python；Rust HTTP 转发子进程可作为原型但不作为最终架构；在 HTTP 层重放领域规则会形成第二条业务链路。

### 2. 静态资源独立，HTTP 契约优先兼容

现有静态资源迁至 `web/static/`，浏览器测试与包锁放 `web/`；先不改布局与模块组织。发行时嵌入资源，开发模式允许显式资源目录；不存在源码目录时发行包仍完整可用。保留 `/`、`/static/index.html`、`/static/...` 与现有 hash 导航，避免书签失效。

默认 `127.0.0.1:8000`，保留 `--root`、`--host`、`--port`、`--no-browser`，端口冲突报错而非悄悄换端口。浏览器只在实际监听成功后打开。绑定、启动失败非零退出；配置/schema 异常在已启动壳层显示可操作诊断，不让健康 API 假报成功。含未完成事务时先展示恢复状态，禁止加载半套资源。

保留主路径 API 和字段；新增服务版本/健康信息与显式恢复接口。HTTP 错误保持可定位 issues 和 conflict.kind，区分参数错误、404、409 busy/守卫冲突、500 内部故障。服务边界校验 Host/Origin、写请求 JSON 类型及体积，静态资源仅来自资源集合；不开放跨源写入或任意文件读取。显式非 loopback 绑定沿用本地可信网络工具定位，不在本次增加账号系统。

### 3. 接口差异由 Rust 用例结果补齐

| HTTP 面 | 复用来源与必要工作 |
|---|---|
| `/api/workspace` | config + canonical status，保留 root、语言、missing/changed/drifted，deploy.targets 为空 |
| `/api/schema-workspace` | Schema 快照、resourceId、完整 Table/Record/Enum、reverseRefs、schemaRevision |
| `/candidate`、`/validate` | 同一捕获基线的候选资源、issues、净差异、hash；validate 在这里是结构校验，不替换成读取 Excel 的全量 validate |
| `/save` | 复用 save_workspace，扩充用例回执以提供 written/deleted/unchanged、notes、isNoOp、净差异及新快照；不得为凑回执再次执行保存或读取 Excel |
| `/gen-template` | 复用 template plan/generate，保持已保存 Schema、显式生成、失败原文件不变 |
| `/export`、`/progress`、`/cancel` | 后台任务 + 五阶段事件，forced 映射完整重建，completion policy 为 export_only |
| `/api/i18n/*` | 完整条目与表/语言统计、四态、save/sync/compact；不要把 worker 默认分页上限当成总条目数 |
| `/api/tasks`、`/dismiss`、`/api/logs`、`/api/history` | 服务进程任务投影、日志缓冲、共享持久历史与 Web DTO 转换 |

前端兼容 Web 命令日志结构，HTTP 入口转换 type/kind；基线、完整历史和 cursor 必须由浏览器准确提交。候选响应绑定 draftGeneration，过时代次不回写。任何超过 JavaScript 精确范围的整数采用明确无损表示，不能在 HTTP 或 UI 转换中四舍五入。补充来源是 ct-app/领域结果，不是 Python，也不从错误中文文本逆向推断错误码。

### 4. 任务属于服务，断开页面不取消

Web 继续轮询，不为本次迁移引入 WebSocket/SSE。后台任务拥有稳定 ID；现有 export progress 契约作为当前/最近导出的兼容投影。任务和日志按服务实例归属，标签页刷新可重新附着；失败通知 dismiss 后同一服务内刷新不复活。服务重启后的任务不虚构终态，页面检测实例变化后重新读取工作区状态。

所有写入口统一参加工作区互斥，包括 Schema、模板、翻译与导出；不得只靠按钮禁用或仅锁 export。读请求使用一致快照或在发布窗口报告 busy/recovery-needed。日志与进度缓冲有界，问题与终态不可被丢弃。

显式取消是协作式请求：发布前可取消，进入发布边界后完成提交或回滚再给真实终态，已经成功提交不得伪装成“未执行”。服务关闭先停止接收新业务写入，再等待任务到安全边界。强制杀进程依靠 journal 恢复；浏览器 HTTP 超时不自动重放写请求。

### 5. 一次性接续，而非双内核长期兼容

- 草稿：默认 origin、路由、IndexedDB 名称/格式/key 保持连续；路径规范化变化提供已知旧 key 查找映射。恢复完整 commands/cursor 后向 Rust 重算候选；Schema 基线变更或未知格式保留原记录和查看入口，不能清空或把已撤销命令全部应用。不同 host/port/profile 的草稿无法自动访问，升级文档要求先在原地址保存，并明确此限制。
- 历史：继续使用 native `history.json`，兼容现有 entry 形状供 Flutter 消费。读取时合并合法旧 panel 条目，按规范化内容生成稳定来源标识去重并取最近五条；首次成功写历史时在锁内原子持久化合并结果及导入来源摘要，源 panel 文件保留。不得让被裁剪旧记录在后续读取中重新导入。坏格式保留并提示；历史失败作为警告，不撤销已提交的导出。
- 恢复：用来自当前 Python 发布器的冻结故障夹具验证 `export-publication/1` 的 prepared/backed_up/publishing/committed，覆盖替换、新增、删除和幂等性。未知旧 apply-journal 保留并阻止写入，提供人工处理指引；不调用 Python 修复。
- 缓存：保留成功账本含义并验证 native 可读旧状态；可丢弃计算缓存按版本失效重建。不能因工具切换删除业务文件或提前推进成功账本。

### 6. 功能对等必须有可运行的覆盖映射

建立 `native/docs/baseline/web-parity.md` 和机器可核查映射，记录固定 Web 基线、采用的 native 源码版本、旧场景、替代测试、允许差异与执行证据。以下是初始映射，不把源码已有实现当作已通过：

| 领域 | 现有测试起点 | 新验收 |
|---|---|---|
| API/资源/保存 | test_schema_workspace_api、test_add_resource_api、test_schema_save_api | Rust HTTP 真请求、YAML-only 文件快照、守卫、恢复与故障注入 |
| 编辑草稿 | test_schema_editor_browser、test_schema_create_browser | JS/TS Playwright 完整编辑、撤销重做、重命名/引用、刷新、冲突、保存中继续编辑 |
| 五模块 | test_module_pages_browser | 真实 native panel 下导出/模板/翻译/日志/历史链 |
| 任务/日志/历史 | test_tasks_projection、test_logs、test_history | 生命周期、通知关闭、取消/中断、历史迁移与失败警告 |
| 壳与布局 | test_shell_browser、test_matrix_browser、test_browser_baseline | 6 个既有视口 × 100/125/150%，焦点、inert、抽屉、弹窗与截图检查 |
| 静态与性能 | test_assets、test_fuzzy_browser、test_resource_benchmark | 模块加载、搜索、真实浏览器性能记录与 HTTP 负载边界 |

保留现有 CSS 投影阈值 900/740px；移植截图矩阵按实际 viewport/zoom 推导，不照搬夹具里过时 route 字符串。真实原生服务和临时工作区是验收路径；mock 只能用于单元测试。冻结 JSON/FBS/Binary/Accessor golden 与 Excel 语义基线；适用的独立 C# 读取端验收不可被服务测试替代。

### 7. 删除门槛覆盖运行、开发和再生链

Rust 构建/测试与发行、Node 浏览器测试、Flutter 回归均不得启动 Python。替代 `native/fixtures/*/generate.py`、template compare、S/M/L 生成与 Python 对照入口；保留静态 golden 来源说明与校验摘要。`ct-xtask fingerprint`、coverage matrix、bench 等从“找不到 ct 就跳过”迁到稳定原生测试清单及留档回归，禁止删代码顺便缩减验收。

`test-proj/` 逐项判断是否用于正式验收：仍被引用的准备/校验脚本必须迁移，历史实验保留记录。归档 OpenSpec 中的历史代码不作为活跃工具执行。迁走 `ct/docs/` 的有效文档并修复所有活跃引用（含 AGENTS/技能中的项目路径）后才移除旧工程；不手工清理其他任务的本地未跟踪资料或 venv。

## Risks / Trade-offs

- [Web API 依赖超出 worker DTO] → 直接扩充 app 结果，逐接口 fixture 对照，重点验证 schema validate 不读 Excel。
- [共享任务抽取影响 Flutter] → 传输信封留在原层；worker 协议、取消、分页和 Flutter 客户端测试作为回归门槛。
- [旧草稿和历史静默丢失] → 同源接续、未知格式保留、历史去重与一次性导入测试；地址变更限制写入迁移说明。
- [Rust 任务阻塞 HTTP] → 有界后台执行、取消响应并发测试，负载/大消息验证，不以改语言推断性能收益。
- [既有主规格与未归档 change 冲突] → 本提案明确恢复 panel，独立记录替代关系；实施期协调 rust-native-core 的删除任务，规格同步时先落其仍有效 delta，再应用本 change 的最终目录/安装规则，防止后归档覆盖新规则。
- [平台或游戏端环境缺失] → 证据标未运行且保留删除门槛未完成，不能用 strict 校验或现有文档结论代替实测。

## Migration Plan

1. 冻结版本、接口样例、浏览器行为和 golden 来源；记录当前差异与验收映射，Python 暂留作对照。
2. 提取静态资源并建立原生 panel 骨架；补齐查询、Schema 与任务能力，Web 功能逐模块接入。
3. 完成草稿、历史、事务接续及正常关闭/强杀恢复；跑真实浏览器和跨入口锁回归。
4. 迁移测试、夹具再生、文档和 CI；无旧 ct/ 的临时干净 checkout、无 Python 的受控环境完成全链验收，保留平台与产物证据。
5. G1（Web 全矩阵）、G2（产物/存储/CLI/worker/Flutter 回归）、G3（无 Python 构建测试再生发行，三平台 panel smoke）均通过才执行删除提交；删除后再验证干净 checkout。没有完成的原生前置验收保持未完成。
6. 同步规格与协调旧 change 任务，旧 Python 只在 Git 历史可恢复；本 change 不替其他 change 宣称整体验收或归档。

发布前保留上一份可用原生发行包和工作区备份。回滚采用替换发行包并按受支持 journal 安全恢复，必要时恢复备份；不把重新引入 Python 当成产品回退路径，也不自动将未知新事务交给旧版本处理。
