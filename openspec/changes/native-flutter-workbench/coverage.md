# 界面 × 内核方法 × 验收场景 映射（native-flutter-workbench 任务 1.1）

基线是 `../rust-native-core/coverage.md` 的 21 行「现有能力/依据」表。本表把每一行落到桌面壳的**具体位置**：
页面/组件 → 内核方法 → 规格验收场景 → 证据（测试文件与真实例数、golden 截图）。
所有数字都是 2026-09-19 实跑结果（复算命令见文末第 5 节），不是估计值。

当前总量：Dart 侧 44 个测试文件、**283 例全绿**；Rust 侧 `cargo test --workspace` **270 passed / 0 failed**；
golden 截图 17 张（`launcher/test/goldens/`）；协议方法 25 个。

## 1. 基线 21 行的界面落点

| 基线能力/依据 | 页面/组件（`launcher/lib/`） | 内核方法 | 验收场景（spec 锚点） | 证据 |
|---|---|---|---|---|
| cli-interface | 无界面入口：桌面壳不复刻 CLI 过滤语义 | `export`/`validate`/`deploy` 的参数形状 | Responsive export and process lifecycle | `test/protocol/method_names_test.dart`(1)、`test/state/export_runner_test.dart`(10) 一比一传参；命令级差异归内核 6.1 |
| tool-workspace-separation | `ui/workbench/workbench_settings.dart`、`services/native_runtime.dart` | `workspace.open`（任意绝对根） | Desktop lifecycle and configured workspace paths / Customized workspace directories | `test/services/native_runtime_test.dart`(10)、`test/workbench_settings_test.dart`(5)、`test/settings_store_test.dart`(4) |
| schema-management | 资源清单与只读预览 | `resources.list`、`table.preview` | Native workspace navigation / Empty workspace | `test/state/workbench_repository_test.dart`(15)、`test/workbench_test.dart`(11) |
| schema-editor/type-system | `workbench_field_editor.dart`、`workbench_screen.dart` 的 `_linkCell` | `schema.candidate`（类型/枚举 token 合法性） | Full Schema navigation and Enum editing / Follow a type or ref link | `test/state/field_editor_kernel_test.dart`(5)、`test/state/field_editor_test.dart`(6)、`test/ui/workbench_navigation_test.dart`(5) |
| schema-editor/query-indexes | 属性区索引勾选（覆盖式声明） | `schema.candidate` + `set_indexes` | Guarded native Schema draft | `test/state/field_editor_kernel_test.dart`(5)、`test/state/schema_draft_kernel_test.dart`(4) |
| schema-editor/workspace-draft | `state/schema_draft.dart`、`state/workbench_repository.dart`、`workbench_draft_bar.dart` | `schema.candidate`、`schema.save`、`workspace.recover` | Guarded native Schema draft / Save a new Table、External schema modification；Draft persistence… / Older candidate response arrives last | `test/state/schema_save_kernel_test.dart`(5)、`test/state/workbench_repository_gate_test.dart`(6)、`test/state/workbench_recovery_test.dart`(4) |
| schema-editor/workbench | `workbench_quick_open.dart`、类型/ref 链接、`workbench_schema_editor.dart` | `resources.list`（含 `fields`/`values`/`primary`） | Full Schema navigation and Enum editing / Quick Open from export、Enum reorder and rename | `test/ui/workbench_draft_bar_test.dart`(10)、`test/ui/workbench_navigation_test.dart`(5) |
| excel-processing | 无界面入口（模板生成/导出在内核侧） | `template.generate`、`export` | Unsafe template migration | `test/state/template_kernel_test.dart`(3)、`test/state/template_service_test.dart`(7) + 内核 `tests/compat` |
| excel-template-styling | 无界面入口（样式由内核唯一实现） | `template.generate` | Unsafe template migration | 内核 270 例含样式夹具；桌面侧只断言显式两步（预检→生成） |
| data-validation | 导出面板问题区 + 候选问题定位 | `validate`（桌面尚无入口，见第 4 节）、`schema.candidate` | Responsive export and process lifecycle | `test/e2e_workbench_chain_kernel_test.dart`(10) 用真实 worker 串「校验→导出」 |
| json-export / json-single-line-records | 无界面入口 | `export` | — | 内核 golden 逐字节对照（`native/docs/baseline/parity-report.md` 第 2 节） |
| flatbuffers-export / csharp-binary | 无界面入口 | `export` | — | 同上：12 个 golden 逐字节一致 |
| i18n-pipeline | `workbench_i18n_view.dart`、`state/translation_repository.dart` | `i18n.query/save/sync/status/compact` | Translation and template workflow parity / Edit long translation | `test/state/translation_kernel_test.dart`(6)、`test/state/translation_repository_test.dart`(9)、`test/workbench_i18n_view_test.dart`(6) |
| incremental-export | 导出结果区（阶段/耗时/缓存统计） | `export` | Responsive export and process lifecycle | `test/state/export_runner_kernel_test.dart`(4)、`test/workbench_export_view_test.dart`(7) |
| export-publication | 无界面入口；界面只做取消与恢复呈现 | `cancel`、`workspace.recover` | Cancel during publication、Disk write fails then user exits | `test/state/export_runner_test.dart`(10)、`test/state/draft_store_faults_test.dart`(7)、内核故障注入 270 例 |
| unity-deploy | 导出面板「独立部署」 | `deploy` | Responsive export and process lifecycle | `test/state/export_runner_kernel_test.dart`(4)：导出请求里不含 deploy；`test/e2e_workbench_chain_kernel_test.dart` 真把文件送进 Unity 目录 |
| web-panel | 翻译/历史/日志/任务四个面板 | `i18n.*`、`history.list`、`logs.list`、`tasks.*` | Durable history and actionable diagnostics / Dismiss failure and navigate、Restart after upgrade | `test/state/desktop_state_kernel_test.dart`(2)、`test/state/desktop_state_test.dart`(9)、`test/workbench_desktop_panel_test.dart`(4) |
| web-panel-design-system | `ui/tokens.dart`、`widgets/`、`workbench_draft_bar.dart`、`workbench_about_dialog.dart` | 无（纯呈现） | Native visual and interaction quality / Resize while editing、Keyboard and input method | 17 张 golden + `test/workbench_golden_test.dart`(17 例)、`test/workbench_draft_banners_test.dart`(5) |
| launcher | `main.dart`、`services/window_options.dart`、`single_instance_lock.dart`、`tray_service.dart`、`exit_guard.dart` | `shutdown` | Desktop lifecycle… / Duplicate launch and login start | `test/services/desktop_shell_test.dart`(3)、`test/services/exit_guard_test.dart`(7)；双进程/真注册表未勾（归 5.5） |
| 新增 worker 协议 | `services/worker_service.dart`、`services/protocol/` | 全部 25 个方法 | Worker crashes、Old workspace event arrives、Save a new Table | `test/protocol/*`(24 例)、`test/services/worker_service_test.dart`(11，含真进程)、`test/state/workbench_repository_test.dart`(15) |
| 性能目标 | 无界面入口（`ct-xtask bench`） | `export` 全量/增量 | — | 内核 change 已按实测修订门槛；桌面交互帧时间归 5.2 |

## 2. 写入口清点（保存 / 模板 / i18n / 部署 + 其余变更类）

| 内核方法 | 改什么 | 界面入口 | 门禁（谁说了算） | 证据 |
|---|---|---|---|---|
| `schema.save` | 仅 YAML | 工具条 `wb.save`、草稿条 `wb.draftSave`、Ctrl/Cmd+S | 双守卫 `schemaRevision`+`candidateHash`、净差异为零/候选计算中/有阻塞问题一律禁保存、保存期冻结编辑 | `test/state/schema_save_kernel_test.dart`、`test/state/workbench_repository_gate_test.dart`、`test/ui/workbench_draft_bar_test.dart`(10) |
| `template.generate` | 建/迁 Excel | `wb.templateGenerate` | 必须先过 `template.plan` 预检且「放行」才可点；非 Table 资源不给按钮（`wb.templateNotTable`） | `test/workbench_template_panel_test.dart`(3)、`test/state/template_service_test.dart`(7) |
| `i18n.save` | 单条译文 | 行内 `wb.i18nEditText`（失焦/回车提交，Esc 取消） | 文本未变不发请求；范围与条目由内核回包 | `test/state/translation_repository_test.dart`(9) |
| `i18n.sync` | 补骨架 | `wb.i18nSync`、`wb.i18nSyncTable` | 全库/单表两档，进度取 `i18n.status` | `test/state/translation_kernel_test.dart`(6) |
| `i18n.compact` | 删孤立条目 | `wb.i18nCompactPlan` → `wb.i18nCompactPreview` → `wb.i18nCompactApply` | 先 dry-run 再确认；orphan 范围由内核判定 | 同上（6 例内含「预检不写盘」） |
| `export` | 写产物+账本 | `wb.exportRun`/`wb.exportAll`/`wb.exportTable`/`wb.exportLang` | 忙时禁重复提交；断连终态标未知、不自动重放；导出不顺带部署 | `test/state/export_runner_kernel_test.dart`(4)、`test/workbench_export_view_test.dart`(7) |
| `deploy` | 写 Unity 目录 | `wb.deployRun` | 独立入口，参数由内核解析；未配置目标时如实 0 同步 | 同上 + e2e 链真落盘 |
| `cancel` | 终止写任务 | `wb.exportCancel` | 终态以内核为准，发布后取消不误报 | `test/state/export_runner_test.dart`(10) |
| `tasks.dismiss` | 关通知 | 任务行关闭按钮 | 已关闭不复活 | `test/state/desktop_state_test.dart`(9) |
| `validate` | 不改文件（只读闸门） | 导出页 `wb.validateRun` | 有写任务在跑时禁用并说明原因；`ok`/`issues` 全取内核回包，界面不判 | `test/state/validate_runner_kernel_test.dart`(4)、`test/ui/workbench_validate_panel_test.dart`(3) |
| `workspace.recover` | 还原/清理 | `wb.recover`（`wb.recoveryBanner`） | 恢复必须先于加载资源；既还原旧文件也清理本事务新增 | `test/state/workbench_recovery_test.dart`(4)、`test/workbench_recovery_banner_test.dart`(2) |

结论：**保存、模板、i18n、部署四类写入口无遗漏**，且每一类都只有内核一个裁决方（界面没有第二条写路径）。

## 3. 25 个协议方法的桌面侧触达矩阵

脚本核对（`lib` 里是否有调用者 / `test` 里是否有断言），逐个方法列全，不挑好看的：

| 方法 | lib 调用者 | 测试文件数 | 判定 |
|---|---|---|---|
| workspace.open | workbench_repository.dart | 14 | 已接 |
| workspace.snapshot | — | 0 | 不接（总览计数走 `resources.list`，见第 6 节核销） |
| workspace.status | — | 1 | 仅协议层测试；界面未接（同上） |
| workspace.recover | workbench_repository.dart | 2 | 已接 |
| resources.list | workbench_repository.dart | 13 | 已接（本轮起带 `fields`/`values`/`primary`） |
| table.preview | workbench_repository.dart | 8 | 已接（首页 + 游标续页 `loadMorePreview`） |
| schema.candidate | workbench_repository.dart | 8 | 已接 |
| schema.save | workbench_repository.dart | 4 | 已接 |
| template.plan / template.generate | template_service.dart | 各 3 | 已接 |
| validate | — | 4 | **未接界面入口**（内核在 `export` 前置闸门内含校验；CLI 有 `ct validate`） |
| export | export_runner.dart, app.dart | 11 | 已接 |
| deploy | export_runner.dart, workbench_export_view.dart | 5 | 已接 |
| i18n.query/save/sync/status/compact | translation_repository.dart（status 亦 app.dart） | 各 2 | 已接 |
| history.list / logs.list / tasks.list / tasks.issues / tasks.dismiss | desktop_state.dart | 2–3 | 已接 |
| cancel | worker_service.dart, export_runner.dart | 4 | 已接 |
| shutdown | worker_service.dart | 2 | 已接 |

## 4. 缺口与去向（写清楚，不含糊）

1. ~~`validate` 无桌面按钮~~ **已补**（任务 5.4）：`state/validate_runner.dart` + 导出页「校验」按钮，
   结论与问题逐条取自内核 `validate`，写任务进行中禁用；内核证据 4 例（含「坏 schema 必须不通过」）。
2. `workspace.snapshot` / `workspace.status` 无调用者：总览计数由 `resources.list` 的清单算出
   （`test/state/workbench_custom_dirs_kernel_test.dart` 4 例钉住「非默认目录下分类计数不扫目录」），
   `workspace.status` 属 CLI 语义。**处置：确认为不接，已按「无界面入口」核销（见第 6 节）。**
3. 双启动不增 worker、系统自启状态一致：同进程测不出来，**归 5.5 真机矩阵**（任务 2.5 因此仍未勾）。
4. ENOSPC/权限位类故障注入在 Windows 临时目录不可稳定构造，**归 5.5**；本轮已用可读错误注入覆盖
   中断残留（`.tmp` 报告 + 清走）与损坏信封保留。
5. 帧时间/减少动态效果/中文输入法、macOS 与 Linux：归 5.1–5.3、5.6。

## 5. 复算方式

```powershell
# 例数与文件清单（权威口径：展开后的真实用例数）
cd launcher
flutter test --reporter json | <汇总 testDone 且 hidden=false 的脚本>   # 283
rg --no-heading -o "Methods\.[A-Za-z0-9]+" lib                          # 方法→调用者
rg -l "schema.save" test                                                 # 入口→证据
flutter test test/workbench_golden_test.dart --update-goldens            # 17 张 golden
cd ../native
cargo test --workspace                                                   # 270 passed / 0 failed
cargo run -p ct-xtask -- fingerprint --check                             # 1145 文件一致
```
## 6. 逐行核销（任务 5.7）

状态口径：**已核销** = 界面映射 + 测试或截图证据齐；**内核侧** = 该能力无桌面入口，证据在 Rust 测试；
**待真机** = 需要 macOS/Linux 或真机鼠标/输入法操作。

| # | 基线行（`rust-native-core/coverage.md`） | 状态 | 证据（截图 / 测试） |
|---|---|---|---|
| 1 | cli-interface | 已核销 | `test/state/export_runner_test.dart`(10) 一比一传参；`test/protocol/method_names_test.dart`(1) |
| 2 | tool-workspace-separation | 已核销 | `test/services/native_runtime_test.dart`(10)、`test/workbench_settings_test.dart`(5)、`test/state/workbench_custom_dirs_kernel_test.dart`(4) |
| 3 | schema-management | 已核销 | `test/state/workbench_repository_test.dart`(15)、`test/workbench_test.dart`(11) |
| 4 | schema-editor/type-system | 已核销 | `test/state/field_editor_kernel_test.dart`(5)、`test/ui/workbench_navigation_test.dart`(5) |
| 5 | schema-editor/query-indexes | 已核销 | `test/state/schema_draft_kernel_test.dart`(4)、`test/state/field_editor_kernel_test.dart`(5) |
| 6 | schema-editor/workspace-draft | 已核销 | `test/state/schema_save_kernel_test.dart`(5)、`test/state/draft_store*_test.dart`(15)、`test/e2e_workbench_chain_kernel_test.dart`(10) |
| 7 | schema-editor/workbench | 已核销 | `test/ui/workbench_draft_bar_test.dart`(10)、`test/ui/workbench_navigation_test.dart`(5)、`test/ui/workbench_preview_paging_test.dart`(2) |
| 8 | excel-processing | 内核侧 | 内核 `tests/compat`（270+ 例）；桌面只走 `template.*`：`test/state/template_kernel_test.dart`(3) |
| 9 | excel-template-styling | 内核侧 | 样式夹具在内核；桌面证据 `test/evidence/chain-04/05-template-*.png` |
| 10 | data-validation | 已核销 | `test/state/validate_runner_kernel_test.dart`(4) + `test/evidence/chain-06-validate.png` |
| 11 | json-export / 单记录一行 | 内核侧 | `native/docs/baseline/parity-report.md` 第 2 节（12 golden 逐字节） |
| 12 | flatbuffers / C#·Lua 读取端 | 内核侧 | 同上；桌面产物证据 `test/e2e_workbench_chain_kernel_test.dart` 第 5 步 |
| 13 | i18n-pipeline | 已核销 | `test/state/translation_kernel_test.dart`(6)、`test/workbench_i18n_view_test.dart`(6)、`test/evidence/chain-09-i18n.png` |
| 14 | incremental-export | 已核销（界面侧） | `test/state/export_runner_kernel_test.dart`(4) 第二次导出报缓存命中 |
| 15 | export-publication | 已核销（界面侧） | `test/state/export_runner_test.dart`(10) 取消/断连；恢复横幅 `test/workbench_recovery_banner_test.dart`(2) |
| 16 | unity-deploy | 已核销 | `test/e2e_workbench_chain_kernel_test.dart` 第 7 步真送文件；`test/evidence/chain-08-deploy.png` |
| 17 | web-panel（翻译/历史/日志/任务） | 已核销 | `test/state/desktop_state_test.dart`(9)、`test/workbench_desktop_panel_test.dart`(4) |
| 18 | web-panel-design-system | 已核销 | 17 张 golden（`test/goldens/`）+ `test/workbench_golden_test.dart`(17)；帧时间 `test/evidence/responsiveness-profile.md` |
| 19 | launcher（单实例/自启/托盘/窗口） | 部分待真机 | `test/services/desktop_shell_test.dart`(3)、`test/services/exit_guard_test.dart`(7)；双进程与真注册表归 2.5/5.5 |
| 20 | 新增 worker 协议 | 已核销 | `test/protocol/*`(24)、`test/services/worker_service_test.dart`(11，含真进程) |
| 21 | 性能目标 | 已核销（界面侧） | `test/evidence/responsiveness-profile.md`（profile 逐帧 build/raster/totalSpan）；内核侧门槛见 `native/docs/baseline/bench-*.json` |

真机缺口只剩：macOS/Linux（1.3/6.5/6.6、5.3 的 mac 包）、双进程与自启状态（2.5/5.5）、
中文输入法与焦点恢复的人工验收（5.1）。**StatsService 已删除**，并由
`test/services/no_workspace_scan_test.dart` 钉住「lib 里不得再出现工作区目录硬编码扫描」。
