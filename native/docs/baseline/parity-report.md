# 产物与诊断一致性报告（rust-native-core 任务 6.4）

生成方式（全部可复现，均只写临时目录/`native/target`，不写真实 `gd/`）：

```sh
cd native
cargo test --workspace --no-fail-fast                    # 兼容/故障注入/并发对照
cargo run -p ct-xtask -- fingerprint                     # 基线源码树指纹 + 测试清单
node tools/parity/cli-text-diff.mjs                     # 原生 CLI vs Python 留档基线（默认不跑解释器）
node tools/parity/cli-text-diff.mjs --live-python       # 需要参照在位时：同机配对实测并刷新留档基线
cargo run -p ct-xtask -- dist                            # 无 Python 环境自检（打包二进制真跑）
```

测量环境：Windows 11 x64（28 逻辑核），`rustc 1.98.1`，Python 参照 `ct/.venv` = `Python 3.12.14`。

## 1. 基线锚点

| 项目 | 值 |
|---|---|
| 基线源码树指纹 | `native/docs/baseline/source-tree.json` 的 `tree.sha256`（1000+ 个文件；该文件本身不参与自身摘要）。这是本报告时点钉住的验收快照，随验收/发布重算；CI 每次推送只把当前源码树的摘要记进运行摘要与 artifact，不要求日常提交同步该文件 |
| 业务兼容矩阵 | `native/docs/baseline/compat-matrix.json`（21 行，逐行对应 `coverage.md` 表格，由 `tests/compat/tests/coverage_matrix.rs` 校验） |
| Python 参照测试 | `ct/tests/**` 687 个测试函数；矩阵外（Web/架构）目录被显式排除并留档 |
| 原生测试 | 50 个含 `#[test]` 的文件；`cargo test --workspace` 最近一次 **275 passed / 0 failed**（`cargo clippy --workspace --all-targets -- -D warnings` 干净、`cargo fmt --check` 通过） |

### L 档配对测量（rust-native-core 任务 6.5 的 Windows 部分）

`native/docs/baseline/bench-l-windows.json`（runs=5 + 1 预热，2026-09-19）：夹具 100 表 × 10,000 行
（18,480,481 数据格、4,000,000 条译文、3 语言、607 个产物）。四个可比场景 Rust/Python 中位耗时比
0.288–0.331（上限 0.5/0.35，全达标），**607 个产物聚合摘要与 Python 逐字节相同**，测量前后真实
`gd/` 各 0 行改动。峰值 RSS 比 1.85–1.94×（≤2.5× 通过，且优于 M 档 2.11–2.31×），但 Rust 绝对峰值
5.6–7.0GiB 越过 M/L 共用的 ≤1.25GiB 常量，`verdict` 四项记 `fail`：该常量不随数据量缩放，
L 档收口需先显式修订口径或改分波流式闸门（见 `design.md` 的 2026-09-19 追加段）。判定口径随后按方案 A 显式修订（绝对上限按档给：M ≤1.25GiB、L ≤7.5GiB），
`xtask bench-recheck` 重算后 `bench-l-windows.json` 四项 verdict 由 `fail` 变 `pass`，M/S 两份报告
判定不变；样本与产物摘要未改。

### 本轮补记（native-flutter-workbench 任务 3.7 / 4.9）

- `resources.list` 现在随清单返回 schema 定义本身：`fields`（table/record，沿用
  `field_to_data` 的持久化词表）、`values`（enum 成员，统一 `{name, comment}` 形态，顺序即
  ordinal）与 `primary`。界面因此能在**没有任何草稿命令**时看到枚举成员，
  「改名带 originalOrdinal」这条规则才真正可达；证据：`ct-cli/tests/worker_chain.rs`
  新增断言（Item 3 个字段 + `primary=Id`，Quality 两个 `{name, comment}` 成员）。
- `schema.candidate` 的 `netDiff` 条目透传领域层的 `change`/`oldName`/`fields[].details`，
  净差异对话框因此能显示「重命名 Mythic → Legendary：ordinal 1 → 3 · wire 风险」，
  不再把改名猜成删除+新增；证据：`ct-worker` 单元测试
  `net_diff_payload_keeps_rename_details` + `launcher/test/ui/workbench_draft_bar_test.dart`。
- 导出/校验/发布链路未改动：兼容用例仍逐字节对齐 Python golden（275 passed 内含
  `tests/compat/tests/export_pipeline.rs`）。

## 2. 产物字节对照（Python 真跑产出的 golden）

`native/fixtures/export_pipeline/golden/` 由 `native/fixtures/export_pipeline/generate.py`
用现行 Python 实现真跑生成（18 个夹具文件 + 12 个 golden）。Rust 侧
`tests/compat/tests/export_pipeline.rs::pipeline_matches_python_byte_for_byte` 逐字节比对全部 12 个文件：

| golden 文件 | 字节 | sha256 前缀 |
|---|---|---|
| `export_pipeline/golden/excel/layout_manifests/item.json` | 3144 | `33895bcad2a8b68b…` |
| `export_pipeline/golden/output/binary/data_en.bin` | 228 | `c96e2007742563ae…` |
| `export_pipeline/golden/output/binary/data_zh.bin` | 316 | `f9ec026cfb6af5d7…` |
| `export_pipeline/golden/output/fbs/container.fbs` | 126 | `845e753f158cf4ea…` |
| `export_pipeline/golden/output/fbs/item.fbs` | 461 | `af494fd0d39ff3f8…` |
| `export_pipeline/golden/output/fbs/types.fbs` | 44 | `0a11352285975bdb…` |
| `export_pipeline/golden/output/generated/csharp/enums.cs` | 335 | `9158ca9a17143cfb…` |
| `export_pipeline/golden/output/generated/csharp/itemaccessor.cs` | 9524 | `883e8e96943fc16d…` |
| `export_pipeline/golden/output/generated/lua/enums.lua` | 181 | `56f11653fdf606d9…` |
| `export_pipeline/golden/output/generated/lua/itemaccessor.lua` | 2223 | `7260a20a2a01880a…` |
| `export_pipeline/golden/output/json/item_en.json` | 189 | `ad0707c24ae48ffe…` |
| `export_pipeline/golden/output/json/item_zh.json` | 185 | `b194197271680014…` |

12 个 golden 的聚合摘要（按 `相对路径\tsha256\n` 拼接后再取 sha256）：
`a6ef36268e588f89175249862b20f5fd99c3fa6d8eee88b2246109067323949b`。

其他 golden 组同样逐字节校验：`binary`（13）、`excel`（13）、`template`（30）、
`schema_state`（8）、`fingerprints`（2，含 `golden.json` 的分层指纹与 schemaRevision/candidateHash 逐值对照）。

## 3. CLI 文本、退出码与产物对照（S 夹具 + 流水线夹具）

`native/docs/baseline/cli-text-diff.md`（由 `node tools/parity/cli-text-diff.mjs` 生成）结论：
`export`、增量 `export`、`export --all`、`validate`、`status`、`i18n status` 六个场景
**stdout/stderr 归一化文本一致、退出码一致、11/11 正式产物逐字节一致**，
生成缓存条目数一致（13 条，按类别逐项相同）。

S/M 基准夹具（10/50 表 × 100/2000 行、20 列、3 语言、uniform 开/关、含 ref/Enum/Record/vector）上，
两个引擎在冷/热/改单表/改译文四场景下的 `output/**` 聚合摘要**逐场景相等**：

- S：`e1eacc403fcd…`（冷、热 CLI、热 worker）、`6dcec9dce2ed…`（改单表）、`52e2b99abe4f…`（改译文），67 个产物。
- M：`070051cef908…`（冷、热 CLI、热 worker）、`7006184c7332…`（改单表）、`bdeb15e8ed75…`（改译文），307 个产物。

原始样本、中位数/尾部、进程树峰值 RSS、硬件与种子见
`native/docs/baseline/bench-s-windows.json` / `bench-m-windows.json`（`xtask bench` 生成，
测量脚本 `native/tools/bench/measure.ps1`，Python 侧通过 `tools/bench/python-entry.py`
跑在真正的解释器进程里，避免 pip 存根把内存算少）。两份报告都记录了
`git status --porcelain gd` 前后 0/0 条 —— 基准没有写真实 `gd/`。

## 4. 故障注入与并发对照

| 类别 | 锚点 |
|---|---|
| 发布各阶段崩溃/回滚/mtime 还原/备份缺失 | `native/tests/compat/tests/publication_recovery.rs` |
| 工作区锁（进程内、跨进程、进程死亡释放、Python 持锁互斥） | `native/tests/compat/tests/workspace_lock.rs` |
| 输入捕获期间被改（Excel/YAML/译文/目录成员） | `native/tests/compat/tests/export_pipeline.rs` |
| 缓存损坏/篡改/版本升级/同 mtime 内容变更 | `native/tests/compat/tests/cache_artifacts.rs` |
| 增量与强制矩阵（8 个变更/损坏场景） | `native/tests/compat/tests/incremental_matrix.rs` |
| 不同并发度下字节与诊断顺序一致 + 峰值内存留档 | `native/tests/compat/tests/parallel_determinism.rs` |
| 校验闸门（主键/CodeName/Enum token/ref/过滤/顺序） | `native/tests/compat/tests/validate_gates.rs` |
| 协议层：坏帧、超限、断连、重复 ID、取消、分页代次、事件队列背压 | `native/tests/protocol/tests/*`（45 例）+ 同源 `native/fixtures/protocol/wire-cases.json`（7 例，Dart 侧解码同一批消息） |
| 桌面状态：历史/日志/任务问题/dismiss、历史写失败不误报 | `native/tests/compat/tests/desktop_history.rs`、`native/tests/protocol/tests/desktop_state.rs` |
| 桌面壳客户端直连真实 worker（握手/关联/取消/安全关闭/分页 `stale-page`/stderr 隔离） | `launcher/test/services/worker_service_test.dart`（11 例，`CT_WORKER_BIN` 指向 `native/target/debug/ct.exe`）+ `launcher/test/services/native_runtime_test.dart`（10 例） |
| 草稿命令投影、真实内核候选与**双守卫保存**（任务 3.1/3.3/3.4：空工作区创建、同草稿相互引用、非法类型被拒、外部改动/伪哈希/工作区占用时拒保存且保留草稿、YAML-only） | `launcher/test/state/schema_draft_kernel_test.dart`（4 例）+ `launcher/test/state/schema_draft_test.dart`（7 例）+ `launcher/test/state/workbench_repository_test.dart`（草稿组 8 例）+ `launcher/test/workbench_schema_editor_test.dart`（5 例） |
| 工作台只读链路（切换工作区/总览/资源列表/只读预览）与旧工作区竞态丢弃 | `launcher/test/state/workbench_repository_test.dart`（7 例，含真实 worker）+ `launcher/test/workbench_live_test.dart`（3 例界面侧） |
| 桌面壳导出/独立部署/取消：过滤参数一比一、终态以内核为准、busy 不覆盖状态、断连终态未知且不自动重放、导出绝不顺带部署 | `launcher/test/state/export_runner_kernel_test.dart`（4 例，**真实 ct worker**：阶段/耗时/缓存非哑值、`tasks.list` 里没有 deploy、未知表名与未知语言均由内核拒绝、内核回 `unknown_request`）+ `launcher/test/state/export_runner_test.dart`（10 例）+ `launcher/test/workbench_export_view_test.dart`（7 例界面侧） |
| 桌面壳退出守卫与异常退出恢复（托盘隐藏、显式退出、`workspace.recover` 三种结局原样呈现） | `launcher/test/services/exit_guard_test.dart`（5 例）+ `launcher/test/state/workbench_recovery_test.dart`（4 例）+ `launcher/test/workbench_recovery_banner_test.dart`（2 例界面侧） |
| 用户目录草稿：信封四要素（格式版本/工作区身份/基线/commands+cursor）、tmp+rename 原子落盘、按工作区隔离、冲突与损坏只保留不套用 | `launcher/test/state/draft_store_test.dart`（8 例）+ `launcher/test/state/workbench_repository_draft_test.dart`（8 例）+ `launcher/test/workbench_draft_banners_test.dart`（5 例界面侧） |
| 模板预检/生成的内核裁决：保存 YAML 不建 Excel、显式生成才建工作簿且不碰别人的工作簿、缺 manifest 时阻塞且写请求发不出去、模板只作用于 Table | `launcher/test/state/template_kernel_test.dart`（3 例，真实 ct worker）+ `launcher/test/state/template_service_test.dart`（7 例）+ `launcher/test/workbench_template_panel_test.dart`（3 例界面侧） |
| 编辑器状态回显（resources.list 的 `indexes`、table.preview 的字段属性）——内核不给出就无法诚实渲染开关 | `native/tests/protocol/tests/editor_state.rs`（2 例） |
| 桌面壳字段类型/属性/索引编辑：命令形状对齐内核（`type_text`、`set_indexes` 用资源 id），非法组合由内核候选拦住且保存被拒，合法编辑仅改 YAML | `launcher/test/state/field_editor_kernel_test.dart`（5 例，真实 ct worker）+ `launcher/test/state/field_editor_test.dart`（6 例）+ `launcher/test/workbench_field_editor_test.dart`（4 例界面侧） |
| 桌面壳翻译：筛选/分页/保存范围/sync 与 compact 两段式确认都由内核裁决 | `launcher/test/state/translation_kernel_test.dart`（6 例，真实 ct worker：无 source 时一律 orphan、预检不写盘、执行只删孤立、未知语言被内核拒绝）+ `launcher/test/state/translation_repository_test.dart`（9 例）+ `launcher/test/workbench_i18n_view_test.dart`（6 例界面侧） |

## 4b. 真实工作区对照发现并已修复的差异

用发行包二进制在真实 `gd/` 上只读跑 `validate/status`（`native/tools/bench/isolation-check.mjs`，
结论见 `native/docs/baseline/isolation-check.md`）时发现：

- Python `ct validate` → 校验通过；原生 → 报 `ComplexShowcase.xlsx` 表头单元格 P4
  `"ItemIds\nRewardDefinition"` 与期望 `"ItemIds\nvector<int32>"` 不一致并退出 1。
- 根因：`ct-excel` 的 `emit_vector` 在「未分组 vector」分支里把叶自身类型文本当成继承的
  字段注解往下传，record 成员的表头第二行因此变成 `vector<int32>`；现行实现（Python）写的是
  所属 record 名 `RewardDefinition`。
- 修复：该分支改为原样传递继承注解（`native/crates/ct-excel/src/layout.rs`）。修复后原生
  `ct validate --root gd` 与 `ct status` 结果与 Python 一致（校验通过，退出码 0）。
- 回归钉住：`native/crates/ct-excel/tests/layout_header_parity.rs`（2 例）同时钉住表头归属与
  manifest 列/节点的 Python 真跑抓取值；`publication_recovery.rs::crash_after_prepared_cleans_private_only`
  补上「恢复必须删除 journal 记录的私有暂存文件」断言（6.7 演练发现的第二处泄漏，见
  `native/docs/baseline/recovery-drill.md`）。

## 5. 已知且刻意保留的差异

1. **控制台编码**：Python 在中文 Windows 以 locale(GBK) 输出，原生内核统一 UTF-8。
   对照脚本按各自编码解码后再比文本，因此内容一致；但**任何直接抓字节比较原始控制台输出的做法都会误报**。
2. **生成缓存键名**：`cache/artifacts/<kind>/<hash>.json` 的文件名是各自引擎 canonical 键的哈希，
   跨引擎不同名（条目数量与类别一致）。正式产物 `output/**` 才要求逐字节一致。
3. **产物文件名大小写**：Python 经 `os.path.normcase` 在 Windows 上会把 `Item_en.json` 归一为
   `item_en.json`，原生内核保留声明大小写。对照与增量测试按大小写不敏感键比较，并依赖
   `pkey` 的平台归一避免同目录重复写。
4. **journal / 历史 / 锁文件格式**：按本次决策只做新格式，不迁移旧 `apply-journal/1`、
   旧桌面历史与旧锁文件；旧材料保留并拒绝在其上写入（`publication_recovery.rs`、
   `desktop_history.rs::unknown_history_format_is_ignored_then_replaced`）。
5. **Excel 容器字节**：模板 ZIP 容器时间戳等不要求一致，按单元格/样式/迁移语义验证
   （`template_semantics.rs` 用 calamine 回读 + ZIP 内样式 XML 断言）。

## 6. 生产入口切换判定

已验收：CLI/worker 功能面、产物与文本一致性、发布可靠性、协议契约、桌面状态、
独立运行时包与无 Python 自检（Windows）、真实 `gd/` 只读对照（见上文 4b）、桌面打包与 CI 已不再
需要 Python；桌面壳 283 例测试全绿（只读链路、旧工作区竞态守卫、偏好迁移、草稿投影、净差异与双守卫保存、
任务/日志/历史三张表与 dismiss、导出与独立部署、取消/busy/断连终态未知、退出守卫与发布事务恢复、
字段类型与属性与索引编辑、翻译筛选/保存/sync/compact，其中 32 例直连真实 `ct worker`）。


**门槛状态（2026-09-19 显式修订后）：Windows 侧时间与峰值内存全部达标；仍未验收的是跨平台与 L 档**：

- 时间项（正式记录 `bench-m/s-windows.json`，runs=5、预热 1；上一轮 runs=3 记录保留为
  `bench-{m,s}-windows-2026-09-18.json`）：M 档中位数比 冷 **0.315**（Rust 11,103ms / Python 35,224ms）、
  热 CLI **0.296**（7,017 / 23,703）、改单表 **0.303**（7,083 / 23,370）、改译文 **0.312**（7,178 / 23,021）；
  S 档 0.371–0.476。按修订门槛（冷 ≤0.5；其余 ≤0.35；S 不回退 max(10%, 50ms)）逐项 **pass**。
  热 CLI 原值 ≤0.2 与另三项 ≤0.35 不自洽（等于要求快 5 倍，实测稳定快 3.2–3.4 倍），已按
  design.md 的 2026-09-19 决策显式修订，非默认放宽。
  比值只在同一记录内比较：同机同夹具的 Python 冷全量中位数从上一轮的 52,985ms 变为 35,224ms
  （机器状态差 1.50×），跨记录比较无意义。`hot-worker` 场景 Python 无常驻模式 ⇒ 记 `no-baseline`，只留 Rust 数字。
- 峰值内存：完成一轮针对性优化（写穿暂存 + 分波生成 + 逐语言释放）后，M 档进程树峰值由上一轮的
  冷 2,881,472KB 降到 **948,700KB（−67.1%）**，比值 6.97× → **2.25×**；热 CLI 2.57× → 2.23×、
  改单表 2.56× → 2.11×、改译文 2.42× → 2.31×；绝对峰值 682–926MiB。S 档比值 0.300–0.704（15–35MiB）。
  按修订门槛（S ≤1.2×；M/L ≤2.5× 且绝对 ≤1.25 GiB）逐项 **pass**；`xtask bench` 已把修订值实现为
  判定常量（`peakRssAbsLimitKb: 1310720`），记录与口径不再互相打脸。
  时间不仅没退：同轮对照冷 12,438→11,103ms、热 CLI 7,384→7,017ms、改单表 7,433→7,083ms、
  改译文 7,542→7,178ms；产物字节逐位不变（聚合摘要 070051ce… 与 Python 参照一致；发布中断恢复演练
  复测通过：kill 窗口内 357 个私有暂存、恢复后残留 0、307/307 mtime 保持）。
  余量依据（实测，不是修辞）：同码相邻两轮 runs=5 相差很小（冷 t 0.3142/0.3152、rss 2.230/2.247、
  峰值 950,488/948,700KB），但**场景间波动大**（改译文 rss 2.067 → 2.310），且 runs=3 的中间轮曾测得
  冷峰值 745,460KB——即峰值存在 ±25% 量级的不确定性，卡死在 2.3× 会在下一台机器上随机翻红。
  已落地机制：①产物字节生成即写穿 `.ct/staged/<op>` 私有暂存，发布只做改名，未提交批次由
  `Publication` 的 Drop 与「无 journal 的 recover」清扫（`publication_recovery.rs` 3 例钉住）；
  ②按 `CT_EXPORT_MEMORY_BUDGET_MB` 分波生成，一波合并完即丢弃该波解析行集；③账本哈希算完即释放
  工作簿字节；④Bundle 仅在预算容得下「全部语言同时在算」时并行，否则逐语言算并当场释放表级字节。
  **两条被实测推翻/确认的结论**（写在这里以免被当成口径借口）：
  ①降峰开关目前**不降总峰值**——预算 24/48/96/192MiB 扫下来冷峰值 911/960/944/879MiB、
  冷耗时 11.16/11.16/11.14/11.02s，全在噪声内；②剩余主因确实是阶段 1 `prepare_tables` 一次产出
  全部表的解析行集（M 档 10 万行 `serde_json::Map`，`CT_MEMDIAG` 估 199MiB 为下界，按峰值倒推约
  六到七成）。因此"再降内存"只能把校验闸门也改成按波进行，而 `ct validate`（读+解析+闸门）实测
  2.52s 占 `ct export --all` 11.35s 的 22% —— 二次解析会把改单表(实测 0.303)、改译文(实测 0.312)两项
  推到 ≈0.38–0.39，即牺牲两项已达标换一项，**本轮不采用**，改为按下述修订口径结案。
- macOS/Linux 只有 CI 定义，本机无对应真机；三平台性能与安装验收未完成（任务 1.3/6.5/6.6 的跨平台部分）。
- 游戏端（Unity C# 实读、语言切换 generation/fallback）与工作台界面（native-flutter-workbench）不在本 change 验收范围。
- Python 实现的删除（任务 6.7 最后一句）刻意未执行：旧面板壳已在桌面任务 2.4 删除，但 `ct/` 仍是性能门槛、
  跨平台与 `gd/` 真机对照的参照实现（门槛是比值，删了就永远无法重测），且 native-flutter-workbench
  还剩 13 项未验收；删除不可逆，需单独授权。

结论：本轮发现的两个语义/回收差异（record 成员的表头注解、恢复时未清私有暂存文件）都已修复并加
断言钉住；**当前差异清单里不存在「未解决的产物或诊断语义差异」**。不切换生产入口的原因是性能门槛
（尤其峰值内存）、跨平台与界面验收尚未完成，而不是存在字节级分歧。
