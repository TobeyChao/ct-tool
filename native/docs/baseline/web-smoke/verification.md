# main 原生 Web 实施验证（2026-09-28，macOS arm64）

范围：从 `2d7dfc9` 引入 native，main Web 基线 `8dc7b81`，提案提交 `55e3822`。
保留 main Flutter 启动壳。此记录是阶段验收，**不是 G1/G2/G3 全部通过**。
未操作真实 `gd/`；所有测试工作区由测试临时创建。

| 检查 | 实际结果 | 原始记录 |
|---|---|---|
| `cargo test --manifest-path native/Cargo.toml --workspace --no-fail-fast` | 最新 76 个目标合计 319 passed，0 failed，0 ignored；包括 worker、JSON/FBS/Binary/Accessor golden、Excel、Schema、锁、恢复与历史接续 | cargo-workspace-2026-09-29.txt（原阶段记录 cargo-workspace-latest.txt） |
| HTTP 专项：`cargo test ... -p ct-cli --test panel` | 最新 21 个真实进程 HTTP 测试通过（含 8 个冻结恢复现场、7 种非法资源输入、CLI 锁争用和历史故障） | cargo-workspace-latest.txt（原阶段记录 native-http.txt） |
| Python journal 冻结对照及真实 HTTP 恢复 | 8 个旧发布器实际崩溃/恢复现场：内容、纳秒 mtime、幂等；损坏配置先恢复、缺备份保留材料 | journal-recovery.txt |
| `cargo test ... -p ct-app panel_tasks` | 4 项任务/日志测试通过 | panel-tasks.txt |
| `npm run test:http --prefix web` | 最新 39 项真实 HTTP 测试通过，含 12 组冻结 Flask 契约、YAML 字节摘要、完整 23 项静态资源、工作区/资源查询、模板失败原文件不变、翻译大表/单条保存及 sync/compact、SIGINT/stdin EOF 忙碌关闭、3 个 codename 索引场景 | node-http-2026-09-29.txt |
| JS Playwright | 最新 115 项通过：真实原生 panel 下的五模块、Schema 创建/编辑/草稿、导出任务、翻译、日志、历史、错误布局、壳层焦点与 18 组视口缩放；没有因 Python 缺席跳过 | browser-2026-09-29.txt、[36 张视口截图](screenshots/README.md) |
| `flutter test` | 13 项通过（启动/停止/重启、设置与偏好迁移） | flutter-test-2026-09-29.txt |
| `flutter analyze` | No issues found | flutter-analyze-2026-09-29.txt |
| `xtask dist` | release 构建；隔离 PATH 真跑 CLI、worker、panel 资源/HTTP/EOF 退出 | runtime-check.txt |
| macOS launcher 构建与打包 | 完整 Flutter release 构建、嵌入单原生二进制、无解释器负载检查、签名和 DMG 生成通过；最终仅刷新内嵌 runtime | macos-build.txt、macos-package-final.txt |
| `.app` 内实际二进制的 Node HTTP 验收 | 17 项通过 | packaged-http.txt |
| `ct panel` 启动参数与故障诊断 | 20 项真实进程 HTTP 测试通过（含默认 8000、显式地址、中文空格路径、浏览器打开、冲突与非法参数） | panel-startup.txt |
| 工作区缺失/损坏配置的浏览器诊断 | 全套 JS Playwright 22 项通过；导出不会在加载失败时假报就绪，修复后可恢复 | browser-startup.txt |
| 历史接续与本轮全链回归 | 双旧来源、稳定去重、最近五条/裁剪不复活、原子写失败警告、HTTP 锁、worker history.list 可读 | cargo-workspace-latest.txt、node-http-latest.txt、browser-latest.txt |
| 旧 Web 静态迁移 | 23 个文件清单、15 个逐字节相同、8 个已说明的适配；新增两项分别是弹窗延迟回调修复和日志注释。`--live-old` 对旧树 SHA 真读通过；旧 Flask 与原生 panel 同一临时工作区 1280×900 首屏关键 DOM、文案和尺寸一致，均无页面错误 | ../web-static-render-compare.json、static-assets-2026-09-29.txt、node-http-2026-09-29.txt |
| 工作区/资源查询与自定义目录 | 旧 Flask 冻结的 4 个 Table/Record/Enum 资源、反向引用与完整 revision 逐项匹配；missing/changed/drifted 分开，GET 不写账本；模板账本同批发布，故障整批回滚 | ../web-resource-query-python.json、../web-resource-query.md、node-http-latest.txt |
| 候选与结构校验 | 完整命令历史的 cursor/redo 只应用有效前缀，编辑代次回显；资源、净差异和 hash 与直接前缀一致；错误位置、过期基线与损坏 Excel 下无读取/写入均经真实 HTTP 验证 | node-http-latest.txt、../web-http-python.json |
| Schema 保存回执 | Table 改名同步跨表 ref，written/deleted/unchanged、notes 与新快照匹配；Excel、翻译、账本字节与纳秒 mtime 未动，净零草稿不写 journal，目标路径冲突整批拒绝；浏览器保存 409 后刷新仍保留命令/cursor/旧基线 | node-http-latest.txt、browser-latest.txt |
| Schema 前端预检和保存 | 候选与保存请求发完整命令、原基线和 cursor；按钮/键盘撤销重做、迟到候选放弃、外部变更后禁用保存、成功保存但模板状态查询失败时不重发保存 | browser-latest.txt |
| 大整数与错误契约 | 真实 HTTP 测安全整数边界、u64::MAX/i64::MIN 的 `$int` 十进制编码；浏览器 API/历史显示无舍入；400/404/409/500 均带正确结构化响应，500 发布暂存故障不改 YAML。超范围历史表数仅为传输夹具，不是有效业务数据 | node-http-latest.txt、browser-latest.txt |
| 后台任务与取消边界 | HTTP 业务槽位为 0 时控制/状态接口仍响应；worker 取消和事件队列 11 项通过；导出发布前取消不写产物，发布边界后请求保留成功终态。Cargo 全工作区最新 311 项、Node HTTP 30 项通过 | cargo-workspace-latest.txt、worker-cancel-protocol.txt、node-http-latest.txt |
| 导出任务浏览器接续 | 五步进度按序上报，发布边界不倒退；校验 issues 进入失败详情。100 表临时工作区真测多标签页/刷新、第二次启动 409 与取消不记账；增量 mtime、forced、失败关闭后刷新、丢失响应及实际 HTTP 超时均有浏览器验收 | cargo-workspace-latest.txt、browser-latest.txt、browser-export-double-start.txt |
| 独立模板生成与漂移刷新 | 保存 Schema 后仍不生成 Excel；显式生成使用已保存字段，未知表 404。批量缺模板在浏览器中逐表串行生成以避开工作区锁冲突；漂移确认说明仅迁移数据区，附加工作表不保留。缺 manifest、损坏工作簿、删除有数据字段及无法转换类型均拒绝并保持原文件与账本。原生模板核心 8 项、HTTP 2 项、浏览器 3 项通过 | template-flow.txt、node-http-latest.txt、browser-latest.txt |
| 翻译条目与大表 | 2502 条真实 HTTP 查询和完整汇总；四态重算、长文本保存、清空译文、无效 key 拒绝且其他语言文件不变。浏览器仅展示含 i18n 表，验证筛选、无主状态中文显示、全屏编辑保存/取消 | node-http-latest.txt、browser-latest.txt |
| 翻译同步与清理 | 真实 Excel 经 HTTP sync 更新 source/语言骨架，指定表/语言和非法范围验证；compact 预览无写入、取消保留，确认后仅删除 orphan。其他文件字节不变，sync/entry/compact 都有 i18n 日志；浏览器列表与汇总刷新 | node-http-latest.txt、browser-latest.txt |
| 日志页过滤与轮询 | 模板/i18n 真实日志分模块/级别/搜索筛选；新日志在页面保持打开时出现一次，无变化轮询不替换阅读视口；顶部位置与跳到底部验证。原生 2000 项环形缓冲及级别归一化、导出失败问题独立终态查询保留见 Cargo/导出任务验收 | cargo-workspace-latest.txt、browser-latest.txt |
| 安全关闭与重启 | SIGINT 和 stdin EOF 在 81 表导出已接受后触发，进程正常退出，验证两语言全表 JSON/FBS/C#/Lua/Binary、成功账本与历史完整；重启同一工作区实例 ID 变化且旧历史可读。浏览器对重启前丢失响应仍显示待核实，不重发 POST。发布前/边界取消及四阶段故障恢复用 Rust 20 项复验 | shutdown-http.txt、shutdown-cargo.txt、browser-latest.txt |
| 跨入口工作区锁 | 真实 panel 子进程、CLI、worker 的同根读写争用返回 busy；Schema/模板/i18n/export 均在锁内。第二个 panel 根可独立生成模板。pending journal 且 Schema 损坏时 CLI status 不给状态结论，worker status 只报待恢复，其他磁盘读取拒绝，不混读资源；全 Cargo 工作区本轮通过 | 本轮 `cargo test --workspace`；CLI 15、panel 21、worker desktop_state 10 项 |
| 旧账本与缓存接续 | 旧 Python `save_state` 静态产物在自定义中文空格 cache/output 路径下由 native 导出接续，保留未触及的旧表/Bundle/hash；默认增量命中且 mtime 不变，校验失败不推进账本。forced、损坏/版本变更缓存、有效/无效译文变化与缺损产物修复均复验 | `../../../fixtures/cache/README.md`、`../../../fixtures/cache/python-state.json`；`cache_artifacts` 11、`incremental_matrix` 8 项 |
| Schema/资源/保存 API 迁移 | 旧三个 Python API 测试文件 27/27 场景均有原生 HTTP 锚点；新增 codename 索引删除/改名不变式 3 项。无 Excel 保存、外部改动、路径冲突和发布故障仍由现有 HTTP 回归覆盖 | `web/tests/codename-invariant.test.mjs`、本轮 Node HTTP 39/39、`npm run check:parity --prefix web` |
| Schema、五模块与壳层浏览器迁移 | 旧 146 个 Web 场景均已有原生验收锚点；Schema 创建/编辑、五模块真实链路、错误通知、日志、历史、Unicode 模糊搜索与焦点均经过浏览器回归。旧 Python logger 名称映射由原生写入模块类别的 Rust 测试接替；Web 筛选按钮与五类名称逐项相同 | browser-2026-09-29.txt、`web/tests/shell-projection.spec.mjs`、`web/tests/logs.spec.mjs`、`native/crates/ct-app/src/panel_tasks.rs` |
| 资源列表与视口性能 | 100/1000/10000 项的首屏、筛选、深滚动、Quick Open 和虚拟窗口通过旧门槛：首屏 <5s、筛选 <2s、DOM <8000、可见行 <100；本机 10000 项测得首屏 167ms、筛选 19ms、299 DOM 节点/31 行。六视口 × 三缩放的 export/schema 截图共 36 张；无全局横滚，投影、嵌套弹窗 inert/焦点与 reduced motion 均通过 | resource-benchmark-2026-09-29.txt、browser-matrix-2026-09-29.txt、[截图索引](screenshots/README.md) |
| 发布版面板同机性能 | 临时相同工作区配对：原生/旧 Python 启动中位 6/254ms、候选 1/2ms、forced 导出 24/27ms、1000 条翻译响应 4/4ms；响应内容归一化 SHA 相同。debug 构建的 27/5ms 翻译响应差距在发布版消失；默认基准只启动原生面板 | [配对原始报告](panel-performance-macos-2026-09-29.json)、[无 Python 运行报告](panel-performance-native-only-macos-2026-09-29.json)、`web/tools/measure-panel.mjs` |
| 独立 C# 读取端 | 原生 `ct export --all` 在临时副本生成 5 个 C# Accessor、12 份 JSON 与三语言 Binary；.NET 10 的独立读取器逐字段校验 127 值，含 CodeName 索引、稀疏 i18n 切换和 12 类标量，0 不一致。输入夹具冻结在 `native/fixtures/accessor_verify/`，正式脚本不使用 Python | accessor-native-2026-09-29.txt、`test-proj/ExportAccessorVerify/prepare-native.mjs` |

Browser：`@playwright/test` 1.55.1；默认 Chromium 下载在本机 Node 26.8.2 环境卡在完成阶段，已停止该下载。
实际使用已安装的 Chromium headless shell 1234（通过 `CT_CHROMIUM_EXECUTABLE` 指定），不是默认下载版本。
CI 使用 Node 22 及锁定 Playwright 的 Chromium，尚未远端运行。截图为 reduced-motion 下的本次原生界面，不是全视口 golden 差异验收。

## 完成边界

- `web-parity.json` 的 146 个旧场景均有实际替代锚点，参数化视口矩阵也已复验。HTTP/草稿/历史与 journal 原始样例见 `web-http-python.json`、`web-http-contract.md` 和 `native/fixtures/journals/`。
- G1 本机通过：146/146 旧场景映射无缺项，Playwright 115/115、真实 HTTP 39/39、资源性能三档和同机配对测量通过；正式测试路径没有因 Python 缺席跳过的场景。旧 Python 只在显式 `--live-python` 的对照测量中启动。
- G2 本机通过：Cargo 全工作区 319/319、Flutter 13/13 与 analyze、原生导出后的独立 .NET 读取端 127 字段值一致。运行环境为 macOS arm64，rustc/cargo 1.98.1、Flutter 3.47.0、.NET 10.0.201、Node 26.8.2。首次 Cargo 日志写入源码树导致指纹可重复测试误报；改为 `/tmp` 收集后全量复验通过。
- G3 未通过：S/M/L、部分 golden/独立读取端再生仍有 Python；Windows/Linux 包与运行验收未在本次实际执行。
- 因上述门槛未齐，未删除 `ct/`、旧 Python CI 或必要的 Python 夹具脚本，也未同步/归档未完成的 OpenSpec。
- 原分支 Flutter 工作台测试来源保存在 `compat-matrix.json` 的 historicalNativeTests；没有将那些结果计作 main Web 的验收。
