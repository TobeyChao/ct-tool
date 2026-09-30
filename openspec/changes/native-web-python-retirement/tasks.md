## 1. 固定对等基线与退役边界

- [x] 1.1 固定采用的 main Web 提交、native 提交及工作树差异，建立 native/docs/baseline/web-parity.md 与机器可核查场景映射；验证每个现有 Web 测试文件及有效场景有新验收目标、允许差异或明确历史说明。
- [x] 1.2 冻结 Web HTTP 成功/失败样例、草稿与历史样例、当前 Python 发布器各阶段 journal 故障夹具及产物摘要；验证样例可独立读取、来源版本和路径占位规则明确，不依赖真实 gd/。
- [ ] 1.3 建立 Python 依赖退役清单，覆盖 ct/、native/fixtures、bench/parity、CI、文档与 test-proj 中正式验收引用；验证每项标明替代位置或纯历史归档理由，不遗漏夹具再生链。
- [x] 1.4 协调 rust-native-core/native-flutter-workbench 的 panel 退役与 Python 删除决策，记录本 change 的接管范围、前置未验收项和规格同步顺序；验证不提前勾选旧任务、不覆盖并发实现。

## 2. 原生 Web 服务与静态资源

- [x] 2.1 将既有 HTML/CSS/JS 迁入 web/static，保留路由和模块组织，建立 Node 包锁与 JS/TS Playwright 入口；验证静态文件清单、模块加载及原页面初始渲染一致，迁移期对照仍可运行。
- [x] 2.2 新建 ct-web HTTP 服务并将静态资源嵌入原生发行构建，保留开发资源目录入口；验证 /、/static/index.html、模块资源和未知路径响应，脱离源码目录仍能加载。
- [x] 2.3 实现原生 ct panel 参数、就绪地址、浏览器打开与启动错误；用进程级测试验证默认/显式 root-host-port、no-browser、端口冲突、中文空格路径及可访问的非法工作区诊断。
- [x] 2.4 实现服务实例/版本信息、HTTP 错误封装、Host/Origin 和请求边界；用 HTTP 集成测试验证非法 JSON、超限、路径穿越、非允许来源写入被拒绝且服务继续可用。

## 3. 共享用例与 Schema Web 契约

- [x] 3.1 补齐工作区配置和 missing/changed/drifted、资源全集与反向引用查询；用冻结响应场景验证只读结果与自定义目录解析，未推进成功账本。
- [x] 3.2 将 Web 命令结构映射到 Rust 命令模型，补齐带 schemaRevision/cursor/draftGeneration 的候选与结构校验；验证候选资源、净差异、hash、非法命令位置、过期基线与不读取 Excel。
- [x] 3.3 扩充 Rust 保存用例回执并接入 HTTP save，保留双守卫、written/deleted/unchanged、notes、isNoOp 和新快照；用文件字节/mtime 快照验证仅 YAML 写入、零差异、改名引用与失败草稿保留。
- [x] 3.4 修改前端候选预检与保存请求以准确传递基线、完整命令和 cursor，处理迟到响应；用浏览器测试验证撤销重做、保存期间编辑不被清除、状态刷新失败不诱导重复保存。
- [x] 3.5 验证并完善大整数无损传输与错误码/冲突映射；用边界值及 400/404/409/500 契约场景确认没有舍入、错误文本解析或业务规则副本。

## 4. 任务、模板、导出与翻译

- [x] 4.1 抽取必要的传输无关任务/取消/事件能力，HTTP 采用有界后台执行并保留 worker 信封语义；验证 worker 协议测试、后台忙碌时状态与取消请求仍可响应。
- [x] 4.2 接入 export/progress/cancel 与全局 tasks/dismiss 投影；验证五阶段、forced、失败问题、刷新及多标签页重附着、关闭通知后不复活、HTTP 超时不自动重放。
- [x] 4.3 接入独立模板生成与漂移刷新；验证从已保存 Schema 生成、保留数据迁移、缺 manifest 拒绝、失败工作簿不变和未知表 404。
- [x] 4.4 接入 i18n 表列表、条目、按表/语言汇总与单条保存；验证仅列 i18n 表、四态、清空译文、长文本和超过分页上限仍可访问全部条目。
- [x] 4.5 接入 i18n sync/compact 与相应日志；验证表语言范围、dry-run、orphan 删除确认、其他翻译文件不变及成功后汇总刷新。
- [x] 4.6 完成日志模块/级别过滤与轮询；验证日志不重复、有界缓冲、问题终态不丢失，以及阅读位置和跳到底部行为。
- [x] 4.7 完成服务安全关闭、发布前/发布中取消和实例重启识别；用故障注入验证真实终态、无自动重放及 SIGINT/适用平台关闭事件后的完整文件集。

## 5. 数据接续与跨入口一致性

- [x] 5.1 实现同源 IndexedDB 草稿接续及已知路径 key 映射；用旧格式样例验证完整历史/cursor/redo、原生重算候选、基线冲突与未知格式保留查看、存储失败持续警告。
- [x] 5.2 实现 panel_history 到原生历史的合并、稳定去重、导入标记和锁内原子持久化；验证最近五条、重复启动不重复、裁剪不复活、旧源文件保留、损坏/写失败仅警告及 原生历史契约可读。
- [x] 5.3 接入显式恢复状态与入口，补齐当前 Python journal 冻结夹具的原生恢复；验证各阶段新增/替换/删除回滚、损坏配置先恢复、幂等和未知旧事务阻断。
- [x] 5.4 统一 Schema/模板/i18n/export 与 CLI/worker 的工作区写锁覆盖及读一致性；用跨进程争用测试验证 busy、发布窗口不读混合资源和不同工作区可独立运行。
- [x] 5.5 验证旧成功账本接续及计算缓存失效策略；用临时工作区证明增量、forced、缓存损坏、失败不记账、配置自定义路径与未变产物 mtime 契约。

## 6. 对等验收迁移

- [x] 6.1 将现有 Schema/资源/保存 API 场景迁为 Rust 真实 HTTP 验收；验证场景映射完整，覆盖无数据结构保存、外部变更、目标路径冲突和事务失败。
- [x] 6.2 将 Schema 创建/编辑浏览器场景迁至 JS/TS Playwright；验证 Table/Record/Enum、类型与索引、引用、净差异、快捷键、弹窗焦点及跨模块草稿。
- [x] 6.3 将五模块与任务/日志/历史浏览器场景迁至真实 native panel；验证从创建资源、保存、生成模板、导出到翻译与历史的完整链路，不以 mock 代替。
- [x] 6.4 迁移六个既有视口 × 100/125/150% 布局截图与壳层测试；验证 900/740px 投影、无全局横向滚动、inert、嵌套弹窗、焦点恢复及 reduced motion，留存可查看截图。
- [x] 6.5 迁移静态模块、搜索与资源性能场景，记录面板启动、候选请求、导出和大数据响应的同机前后测量；验证正确性与既有性能断言，记录新瓶颈，未达已有门槛须修复或明确修订验收。
- [x] 6.6 执行 G1 Web 功能对等门槛，将真实 HTTP 与浏览器执行结果回填场景映射；验证必要场景无缺项、无因 Python 缺席跳过，差异均符合本 change 的规格。
- [x] 6.7 执行 G2 原生回归门槛：Cargo、worker 契约、适用 Flutter 回归、JSON/FBS/Binary/Accessor golden、Excel 语义与必要独立读取端验证；记录命令/版本/平台，未运行项保持未完成。

## 7. 无 Python 开发与发行链

- [x] 7.1 将 S/M/L 基准生成迁至 Rust 并保留 r/r-full 入口；删除生成输出后验证各档可再生、规模/种子/语义契约和基准留档回归入口成立。
- [x] 7.2 替代 native/fixtures 中 Excel、Schema、fingerprints、binary、export、template 的必要 Python 生成/语义比较脚本；验证 golden 来源可追溯、独立断言保留，不由被测代码生成期望值来掩盖差异。
- [x] 7.3 将正式验收仍调用的 test-proj Python 准备/检查入口迁至 Rust/JS 或既有目标语言；用对应入口真跑验证，纯历史实验登记为非活跃且不批量删除资料。
- [x] 7.4 将 fingerprint、coverage matrix、bench 与 CLI 对照脚本收敛为原生清单及静态基线，退役 live-Python 必需路径；验证 ct/ 缺失时测试数量/必要场景不缩水、基线损坏明确失败。
- [x] 7.5 更新发行自检与 macOS CI，加入 panel 静态资源/HTTP/退出 smoke 及 Node 浏览器验收；验证正式流程不安装或调用 Python，发行包不含解释器或 Flask 负载。Windows 延后，Linux 不纳入支持。
- [ ] 7.6 迁移有效 ct/docs 文档并更新安装、开发、升级、基准说明及活跃路径引用；验证新命令可执行、链接有效，明确同源草稿限制、未知事务处理和旧同名 ct 冲突。
- [x] 7.7 执行 G3 干净环境门槛：临时 checkout 排除旧 ct/，受控环境无可执行 Python，完成构建、必要测试、夹具再生和 macOS 发行/panel/launcher smoke；留存环境与原始结果，任一必要缺项不得标通过。Windows 延后，Linux 不支持，不以其缺席缩减 macOS 场景。

- [x] 7.8 迁移 main launcher 的运行时发现与设置，删除 Python/venv 回退且保留工作区/端口/托盘/自启行为；验证内置和显式原生路径启动参数、旧偏好迁移、运行时缺失错误与无真实 gd 默认绑定。
- [x] 7.9 迁移 launcher 打包和安全停止流程为原生 panel；验证就绪后打开浏览器、忙碌时正常退出不强杀、进程重启无孤儿及 macOS 原生负载检查。Windows 发行验证延后。

## 8. 退役与收尾

- [ ] 8.1 在 G1/G2/G3 全部通过且原生相关前置验收有证据后，删除已替代的 Python 业务/HTTP/CLI、有效脚本与 pytest/安装/CI 入口；验证删除清单与覆盖映射逐项一致，保留静态留档和其他任务的本地资料。
- [ ] 8.2 删除后从干净 checkout 复验原生构建、HTTP/浏览器、必要夹具再生与发行自检，并检查活跃依赖无 Python；确认无悬空文档引用或靠本机旧产物才能运行的路径。
- [ ] 8.3 编写发行迁移与原生版本回滚记录，演练备份/恢复及旧未知 journal 拒绝；验证不依赖 Python 回退、不破坏用户工作区。
- [ ] 8.4 按实际验收同步本 change 的 delta specs 并协调旧 change 的范围记录，检查后续归档不会恢复 panel 退役或 Python 目录要求；运行 OpenSpec strict 校验，保留全部真实执行证据及剩余限制，不代替其他 change 归档。

## 当前执行记录

2026-09-28：在 main 实施。原分支检查点 `2d7dfc9`，提案提交 `55e3822`。原生 HTTP、Web 静态资源、Schema/任务/翻译/历史接入和 main launcher 原生启动已实现；已做本机回归和 macOS 打包，详见 `native/docs/baseline/web-smoke/verification.md`。多数任务仅完成部分实现/验证，维持未勾选；G1/G2/G3 尚未通过，Python 暂不删除。

本轮补充：同源草稿别名冲突的事务保护、旧基线/redo/未知格式查看与存储失败重试已验收；8 个实际 Python 发布器故障现场已冻结，原生恢复通过内容与纳秒 mtime 对照及真实 HTTP/浏览器入口验收。旧 change 的接管与同步顺序见 scope-handoff.md。当前 7/45 项完整验收，其他部分实施项不提前勾选；Rust 299、浏览器 20、Node HTTP 6、launcher 13 项通过，旧 Web 场景已承接 28/146。

2026-09-28 下一轮：已从 main 旧 Flask 真跑冻结 12 组 HTTP 成功/失败样例、保存前 YAML/保存后 SHA-256、旧浏览器 IndexedDB redo 草稿与旧历史读取样例；与先前 8 个 Python 发布 journal 故障现场合并满足 1.2，采集来源、源码 SHA 与占位规则见 `native/docs/baseline/web-http-contract.md`。原生 GET 工作区 revision 和完整资源 DTO 已按样例修正，保存回执仍保持 YAML-only。Schema 保存/状态/校验及任务新验收使旧场景映射达 41/146；G1/G2/G3 仍未通过。

2026-09-28 启动验收：`ct panel` 进程级新增默认当前目录/8000、显式地址、中文空格路径、非法参数、浏览器打开抑制与绑定失败不打开的测试；损坏或缺失配置的真实浏览器测试确认业务 API 为 400、导出入口禁用且修复后恢复。见 `native/docs/baseline/web-smoke/panel-startup.txt` 和 `browser-startup.txt`；2.3 完成。默认端口测试仅在本机 8000 可绑定时执行，本次实际通过。

2026-09-28 历史接续：旧 Web 历史按规范化业务字段生成稳定身份，双来源摘要随导入标记原子写入原生 history.json；合并先去重再保留最新五条，已裁剪来源不会复活，原始 panel_history.json 保留。同秒的两次原生导出仍记录两条。损坏/写失败仅记警告，HTTP 仍可读原生历史；Worker 的 `history.list` 真读导入条目。Cargo 全工作区 310 项、Node HTTP 17 项、Playwright 22 项通过；详见 web-smoke 验证记录。5.2 完成，旧 Web 映射 42/146。

2026-09-28 静态迁移：`web/static-manifest.json` 固定 main 旧 Web 全部 23 个文件 SHA，17 个文件逐字节相同、6 个适配文件逐项标明迁移原因；`node web/tools/check-static-assets.mjs --live-old` 真读旧树通过，默认检查不依赖 ct/。原生 HTTP 逐项提供 23 个文件并校验媒体类型/模块导入。相同临时工作区中旧 Flask 与原生面板的 1280×900 首屏导航、按钮、文案、布局尺寸和浏览器错误完全一致，冻结报告见 `native/docs/baseline/web-static-render-compare.json`，并由无 Python Playwright 测试持续核对。Node HTTP 19 项、Playwright 23 项通过；2.1 完成。

2026-09-28 查询与模板账本：用旧 Flask 临时工作区冻结自定义目录下 4 种资源/反向引用、完整 revision 与 missing/changed/drifted 各阶段响应；原生真实 HTTP 逐项完全匹配，见 `native/docs/baseline/web-resource-query-python.json`。修正模板生成只发布 Excel/manifest 未同步工作簿 hash 的差异，将账本纳入同一发布事务；只读查询不改 YAML 或账本，账本目标故障时整批回滚。Cargo 310、Node HTTP 21、Playwright 23 项通过；3.1 完成，4.3/5.5 的其余验收仍未完成。

2026-09-28 候选与结构校验：原生真实 HTTP 验证完整资源、净差异、hash、schemaRevision、draftGeneration 与 cursor 前缀/redo；错误命令定位、过期基线 409、不读取损坏 Excel、YAML 字节与 mtime 不变。非对象命令返回准确错误，validate 的失败回执补齐 `netDiff:null`。冻结 Flask 候选结果仍逐项对照；3.2 完成。

2026-09-28 保存回执：真实 HTTP 验证 Table 改名时跨表 ref 更新、YAML written/deleted/unchanged、notes 与刷新后的资源/反向引用；工作簿、翻译、账本字节及纳秒 mtime 不变。净零命令不写文件或 journal，目标路径冲突整批拒绝。真实浏览器在外部 YAML 修改导致保存 409 后保留完整命令、cursor、旧基线，刷新后仍可恢复。Node HTTP 28、Playwright 24 项通过；旧 Web 映射 43/146。3.3 完成。

2026-09-28 前端预检/保存：放弃草稿时推进编辑代次，迟到候选不再污染已清空的状态；候选同时校验服务端回显代次。真实浏览器验证完整命令历史与 cursor、按钮和键盘 undo/redo、外部变更后原基线不被暗中替换、保存期间继续编辑、状态刷新失败不重复保存。Node HTTP 28、Playwright 28 项通过；旧 Web 映射 46/146。3.4 完成。

2026-09-28 传输边界：独立于业务合法性的临时 history 夹具真测 ±2^53 边界及 u64::MAX/i64::MIN，HTTP 以 `$int` 十进制标签无损返回，浏览器 API 与历史表格显示原值；真实请求分别触发 400 非法命令、404 未知表、409 hash 冲突及 500 发布暂存故障，检查结构化字段与 YAML 未变。Node HTTP 30、Playwright 29 项通过；3.5 完成。超范围表数仅作传输压力夹具，不宣称合法导出表数可以超 u32。

2026-09-28 后台任务与取消边界：HTTP 业务槽位耗尽时 progress/tasks/logs/cancel/dismiss 仍返回 200；worker 控制、事件队列 11 项通过。共享取消令牌只在导出发布前检查点生效，发布前取消不生成产物，发布边界后的请求保留真实成功终态；移除 worker 对任意成功结果的取消覆写。Cargo 全工作区 310 项、Node HTTP 30 项通过；4.1 完成。4.2 的浏览器任务矩阵与 4.7 的关闭故障注入仍待验收。

2026-09-28 导出任务浏览器验收：修正 progress 在 Bundle 后倒退到 Accessor 的阶段顺序，五步后发布用独立边界显示；结构化校验问题转发到 Web 任务。真实 native panel 下通过 100 表临时工作区验证双标签页/刷新重附着、第二次 POST 409、显式取消不发布产物或推进账本；冻结夹具验证默认增量 mtime、forced、校验问题和关闭错误通知后刷新不复活。模拟“服务已接受但浏览器丢响应”与实际超时，POST 均只发送一次；无法核实则跨刷新保持待核实提示，恢复连接后只以 GET 重附着。Cargo 311、Node HTTP 30、Playwright 34 项通过；旧 Web 映射 51/146。4.2 完成，4.7 的关闭故障注入仍待验收。

2026-09-28 模板独立生成验收：导出页批量缺失/漂移模板改为逐表提交，避免工作区锁冲突；确认提示说明旧 manifest 迁移表格数据，附加工作表不保留。真实原生 HTTP 验证保存 Schema 后不生成 Excel、显式模板使用已保存字段、未知表 404、缺 manifest 和损坏工作簿不改原文件/账本；浏览器验证双表批量、漂移确认、创建表保存前不可生成以及刷新后入口保留。核心模板测试 8、Node HTTP 32、Playwright 37 项通过；旧 Web 映射 54/146。4.3 完成，G1/G2/G3 仍未通过。

2026-09-28 翻译条目验收：真实 HTTP 单次列出 2502 条（超过旧分页上限）并完整汇总；translated/stale/missing/orphan 四态、长文本和清空译文经保存复核，其他语言文件不变，未同步 key 拒绝。浏览器验证只列含 i18n 的表、筛选空状态、无主中文徽标、全屏编辑保存/取消。Node HTTP 33、Playwright 38 项通过；旧 Web 映射 58/146。4.4 完成。

2026-09-28 翻译同步与清理验收：真实 Excel 夹具经 HTTP sync 生成 source/语言骨架，表/语言范围及非法范围拒绝验证；compact dry-run 列明 orphan 而不写文件，取消保留，确认后仅删目标 key，其他翻译文件不变。sync/entry/compact 记录 i18n 日志，浏览器同步和清理后刷新列表/进度。Node HTTP 34、Playwright 39 项通过；旧 Web 映射 60/146。4.5 完成。

2026-09-28 日志页验收：真实服务写入模板成功/失败及 i18n 日志，浏览器验证模块、级别、搜索过滤，可见时增量更新且不重复、无新日志轮询不替换滚动视口、阅读位置和跳到底部。原生 Tasks 2000 项上限与级别归一化的 Rust 测试，以及导出失败 issues/终态接续测试继续通过。Node HTTP 34、Playwright 40 项通过；旧 Web 映射 68/146。4.6 完成。

2026-09-29 安全关闭验收：SIGINT 与 launcher 使用的 stdin EOF 都在 81 表导出已被服务接受后触发，进程正常退出；检查两语言全表 JSON、FBS、C#/Lua Accessor、Binary、成功账本和历史，重启实例 ID 更新且历史可读。真实浏览器在响应丢失并重启同地址服务后保持“结果待核实”、禁用再次导出且 POST 仅一次，用户显式核对后才可继续。Rust 导出边界取消 2 项及发布 prepared/backed_up/publishing/committed 故障恢复 10 项复验通过；Node HTTP 36、Playwright 41 项通过。4.7 完成，G1/G2/G3 仍未通过。

2026-09-29 跨入口读写锁验收：CLI `status` 与 worker `workspace.status` 在 pending journal 时先拒绝/标记恢复，worker 其他磁盘读取统一在持锁后检查恢复状态，避免加载混合 Schema；内存中的 tasks/logs 仍可查询。真实 panel 子进程与 CLI 在同一工作区竞争 Schema/模板/i18n/export 锁，返回 busy 且不生成文件；第二个 panel 工作区独立生成模板。Worker 契约验证 locked root busy、另一个 root 就绪、释放后原 root 就绪，及损坏 Schema + pending journal 时不读取资源。`cargo test --workspace` 全通过；CLI 15、panel 21、worker desktop_state 10 项通过。5.4 完成；G1/G2/G3 仍未通过。

2026-09-29 成功账本接续验收：使用旧 `ct` Python `save_state` 写出的静态账本夹具，在自定义中文空格 cache/output 路径的临时工作区中由原生导出接续；未触及的旧 Table、Bundle、Excel hash 哨兵原样保留，新 Item 与两语言记录加入。第二次增量命中计算缓存且不改产物字节/mtime，之后非法数据导出不改账本与产物。既有矩阵复验 forced 绕过、缓存损坏/版本升级重建、有效/无效译文变化、失败不记账与正式产物 mtime。`cache_artifacts` 11 项、`incremental_matrix` 8 项通过。5.5 完成；G1/G2/G3 仍未通过。

2026-09-29 Schema/资源/保存 API 映射验收：补迁旧 `test_schema_workspace_api.py` 的 3 个 codename 索引场景，通过真实原生 HTTP 验证删除后同名复用不继承旧索引、删除/改名 CodeName 未撤索引时被拦、显式先撤索引后合法。连同既有 add_resource、save、workspace 测试，3 个旧 API 文件的 27/27 场景已有实际锚点；无 Excel 保存、外部修改 409、目标路径冲突、发布 500、只改 YAML 及事务恢复均在真实 HTTP 覆盖。`npm run test:http --prefix web` 39/39，通过 `check:parity`，全局旧 Web 场景 71/146，75 个仍待迁移。6.1 完成，G1/G2/G3 仍未通过。

2026-09-29 编辑器浏览器迁移进展：新增并实际执行 14 个原生 panel Playwright 场景，覆盖头部/分组/空工作区创建入口、非法或重名及双击提交、Record/Enum 无模板入口、390px 键盘/焦点/宽度、草稿条保存/丢弃、IndexedDB 命令和撤销游标跨刷新，以及 Quick Open 跨类别筛选、最近项、跨工作区回退、双 Escape/焦点与键盘选择。完整浏览器套件 55/55 通过；旧场景映射 85/146，61 个待迁移。6.2 仍未完成，G1/G2/G3 仍未通过。

2026-09-29 编辑器浏览器迁移续进：新增并实际执行 11 个原生 panel Playwright 场景，覆盖资源列表跨类型模糊筛选及字符高亮、折叠组搜索临时展开与偏好恢复、计数/键盘选择/筛选持久化、字段弹窗无效命名及完整命令、I18N string/CodeName 锁定、主键操作锁定、只读 Inspector、具名 Enum 类型命令、Record 专属选项与 390px 字段卡片。完整浏览器套件 66/66 通过；旧场景映射 96/146，50 个待迁移。6.2 仍未完成，G1/G2/G3 仍未通过。

2026-09-29 编辑器浏览器迁移续进：再新增并执行 11 个原生 panel 场景，覆盖字段改名/调序/改类型/删除后仅报告原字段净删除，CodeName 索引卡片、草稿持久化、徽标和改名/删除的显式撤索引，Enum 值增改删、被引用 Record 删除保护、ref Table 跳转、开关索引净零仍可撤销，以及跨模块键盘 Quick Open。完整浏览器套件 77/77 通过，`check:parity` 计 107/146，39 个待迁移。6.2 未完成，G1/G2/G3 未通过。

2026-09-29 编辑器浏览器迁移续进：侧栏拖拽宽度和偏好跨刷新、删除 Table 后仅删除 YAML 且保留 Excel/导出 JSON、损坏 YAML 显示文件原因并在修复后恢复，新增 3 个真实浏览器场景。并发测试发现弹窗关闭后 80ms 计时器可能重新给旧弹窗加 `open`，现只对仍在栈内的弹窗执行；全套 Playwright 80/80 通过，映射 110/146、36 个待迁移。6.2 仍未完成，G1/G2/G3 未通过。

2026-09-29 Web 浏览器验收收口：Schema 的创建/保存状态、Unicode 模糊搜索、翻译窄屏/列显隐/失焦保存、导出错误布局与关闭失败提示、日志类别、壳层投影/焦点/嵌套弹窗和 18 组视口缩放均迁入原生 panel 验收。旧资源性能场景在 100/1000/10000 项下补齐首屏、筛选、深滚动和 Quick Open；10,000 项本机首屏 167ms、筛选 19ms、299 DOM 节点。`ct/` 中的视口矩阵夹具已复制到 `web/tests/fixtures/`，浏览器测试不依赖旧 Python 工程。Playwright 115/115、Node HTTP 39/39、静态旧树 23/23、原生日志类别/级别 Rust 测试通过；`check:parity --require-complete` 为 146/146、0 pending。导出/Schema 36 张截图及原始日志见 `native/docs/baseline/web-smoke/`。6.2、6.3、6.4 完成；6.5 仍缺面板启动、候选、导出及大数据响应的同机前后测量，故 6.6/G1 尚未正式通过。G2/G3 与 Python 删除仍未完成。

2026-09-29 G1 Web 门槛：发布版 `ct panel` 与旧 Flask 面板在同机临时工作区配对测量，首次启动后预热再取五次中位数；原生/旧面板启动 6/254ms、候选 1/2ms、三次 forced 导出中位 24/27ms、1000 条翻译 HTTP 响应 4/4ms，数据归一化 SHA 相同。debug 构建曾测得翻译响应 27/5ms，发布版复测证实是构建配置差异，未形成发行瓶颈。`npm run bench:panel --prefix web` 默认仅运行原生，`--live-python` 才启用历史参照；原始报告及无 Python 路径结果见 `native/docs/baseline/web-smoke/panel-performance-*.json`。连同 Playwright 115/115、Node HTTP 39/39、完整 18 组视口/36 张截图、资源性能三档和 146/146 映射，6.5/6.6 完成，G1 通过。G2/G3 尚未通过，因此 Python 工程仍保留。

2026-09-29 G2 原生回归：`cargo test --manifest-path native/Cargo.toml --workspace --no-fail-fast` 76 个目标合计 319 passed、0 failed/ignored；包含 worker 协议、JSON/FBS/Binary/C#/Lua golden、Excel 语义及发布恢复。首次把实时日志写进受测源码树，指纹可重复测试因文件增长失败；改写 `/tmp` 后同命令全通过，成功运行的原始日志已留档。`flutter test` 13/13 与 `flutter analyze` 无问题。复制旧小工作区到 `native/fixtures/accessor_verify/`，新增无 Python 的 `test-proj/ExportAccessorVerify/prepare-native.mjs`，用发布版原生 `ct export --all` 在临时副本生成 5 个 C# Accessor、12 份 JSON 和三语言 Binary，由独立 .NET 10 读取端复核 127 个字段值、CodeName、稀疏 i18n 切换和 12 标量，0 不一致。环境 macOS arm64、rustc/cargo 1.98.1、Flutter 3.47.0、.NET 10.0.201、Node 26.8.2。原始记录见 `native/docs/baseline/web-smoke/`；6.7/G2 通过。G3 尚未通过，Python 工程仍不得删除。

2026-09-30 G3 夹具迁移进展：S/M/L 改由 Rust xtask 直接生成，三档从空临时目录再生并由原生 ct validate 通过；S 重复生成摘要一致，5 样本本机新夹具基线及再次运行的五场景回归均通过。基准默认不自动拾取 Python，并校验夹具/留档输入摘要；旧 Python S/M/L 留档因分布不同不能冒充新基线。M/L 新性能留档与其他平台尚未完成，7.1/G3 保持未勾选。规模、摘要和命令见 `native/docs/baseline/bench-native-fixture-verification.md`。

2026-09-30 兼容夹具迁移：六类独立输入/期望值共 130 文件及七份历史来源文本已固定 SHA-256；Rust `xtask compat-fixtures` 先校验冻结材料，再从独立 OOXML 源重建六个 Excel 边界工作簿，两次空目录输出字节一致。Schema/hash/Binary/export/template 保留独立静态输入与期望，不以原生生成器覆写 golden。模板完整语义比较改由独立 XML/ZIP 读取器执行，旧 openpyxl 工作簿对照、故意改坏表头和源摘要损坏的负例均通过；无可执行 Python 的 PATH 下准备与比较入口通过。兼容包 188/188，全工作区 324/324，0 failed/ignored，OpenSpec strict 通过，三平台 CI 已加入再生检查但尚无三平台执行证据。7.2 完成，详见 `native/docs/baseline/compat-fixtures-verification.md`。M 档五样本原生基线及再次五样本运行的五场景全部 regression-pass；L/其他平台尚待完成，7.1/G3 维持未勾选。7.4 的 fingerprint 仍有 Python 版本探测，整体无 Python 门槛尚未通过。

2026-09-30 验收清单与对照收敛：main 85 文件/690 函数已独立冻结，补齐旧 native 84/687 清单之外的三项主分支检查；修复部署改大小写时保留 Unity GUID 的缺口。fingerprint 改为原生/Web 源码 + 完整历史清单，不再执行解释器或扫描 ct/；覆盖矩阵始终校验完整映射与原生锚点，无 ct 缺席提前返回。CLI 六场景改为只读冻结基线与摘要守卫，bench 缺失/损坏留档明确失败，首次采集必须显式 --record-baseline，恢复演练改为原生 + 独立 CLI 留档。无 ct/、无 Python PATH 的临时源码包离线全工作区 328/328、0 failed/ignored，六个 CLI 场景退出码/文本/11 产物摘要均一致；S 回归五场景通过，M 发布 prepared 阶段中断后 307 产物摘要/mtime 恢复且暂存清零。首次环境缺 cat/sleep 与源码包无 Git 元数据的断言问题均已修复、复验，失败记录保留。7.4 完成，证据见 native/docs/baseline/python-free-verification.md。L 首轮五样本已留档、所有峰值低于 7.5 GiB，独立复验进行中；7.1/G3/三平台门槛仍未完成，Python 不删除。

2026-09-30 独立读取准备与历史实验登记：test-proj 19 个 Python 脚本逐项审计，两条正式准备入口已由 Node + Rust 替代，17 条历史实验保留非活跃说明及来源摘要。旧标量只读历史产物的验收缺口已补齐：Rust 从冻结输入再生 Binary/C#，逐字节匹配 main 8dc7b81 参照，再由独立 C# 读取；32 文件摘要守卫、31 份 main 来源字节验证、九条 FNV 必需和固定 127 项检查防止静默缩水。临时源码包排除 ct/、无 Python PATH 下独立读取 127/127、0 不一致，离线 Cargo 全工作区 331/331、0 failed/ignored；缺 FNV、源摘要损坏、新未登记脚本和未知 golden 均拒绝。首轮暴露旧兼容清单误收未跟踪 pycache（130 实为 129 份版本化输入 + 本机缓存），已排除缓存、保留全部必要输入与场景并加回归；六个 Excel 再生入口及六范围指纹通过。原始记录见 native/docs/baseline/test-proj-verification.md。三平台 CI 加入该独立读取入口，尚无远端实测，7.3 完成，当前 35/45。

L 独立五样本复验已完成：冷/热 CLI/热 worker/改单表/改译文均 regression-pass，每场景 607 产物摘要与基线一致，最大采样进程树 RSS 7,704,160 KiB < 7.5 GiB；原始结果见 bench-l-macos-native-verification.json。S/M/L macOS 留档回归已完整，其他平台留档、发行及 G3 仍未完成，7.1/7.5/7.7 保持未勾选，不删除 Python。

2026-09-30 macOS 发行与 G3：按用户最新范围，Windows 延后、Linux 不支持，均不作为通过项或阻塞项。干净副本排除旧 ct/ 与构建/夹具输出，受控 PATH 无 Python 命令；Cargo 332/332、HTTP 39/39、浏览器 115/115、Flutter 15/15 和分析无问题，独立 C# 读取 127 项 0 不一致、六 Excel 夹具再生、S/M/L 从空目录再生并原生校验，三档摘要与留档一致。ZIP 权限丢失已修复并经真实解压验证；原生包、签名 app 与只读挂载 DMG 的 CLI/worker/panel/EOF 真跑及无 Python/Flask 负载检查通过。launcher HTTP 就绪后打开浏览器、81 表导出忙碌时安全停止与重启无孤儿通过。7.1/7.5/7.7/7.9 完成，G3 通过，当前 39/45；远端 CI 未执行。原始失败、修复后结果与环境见 native/docs/baseline/macos-g3-verification.md。文档/退役清单和删除后复验仍待完成，因此旧 Python 暂未删除。
