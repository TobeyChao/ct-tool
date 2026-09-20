# 重制能力覆盖与验收索引

本表于 2026-09-17 根据当前工作树复核，包含未提交的 Schema/日志相关实现。它是两个 change 的共同迁移清单，不是“已实现”证明。实施时每行补充原生测试/截图/运行记录；代码和规格存在已知冲突时按下方决策处理，不能按所有历史描述盲目重做。

| 现有能力/依据 | 必须承接的行为 | 负责 change / 验收锚点 |
|---|---|---|
| cli-interface；ct/cli.py；test_cli_filter_and_i18n_output | export 的 all/table/lang/verbose/for-build/root，validate/status/gen-template，i18n sync/status/compact，deploy；退出码和纯 JSON stdout；单值精确过滤 | 内核 6.1；对应 delta；命令级差异测试 |
| tool-workspace-separation | 数据目录不放源码，从 cwd 或 --root 运行；独立安装及隔离开发测试 | 内核 6.6–6.9；对应 delta |
| schema-management；schema tests | YAML 解码、未知字段拒绝、命名/类型/角色、深度/循环、确定顺序、主键 int32、CodeName、Enum wire type、uniform 默认省略 | 内核 2.1–2.5；边界夹具 |
| schema-editor/type-system；test_canonical_reader | 所有标量、嵌套 Record、固定/变长 vector、括号文法、Enum token 域、固定空槽默认 | 内核 2.4–2.5；数据逐项对照 |
| schema-editor/query-indexes；test_query_indexes | id/codename/hash 查询、碰撞比较、稳定顺序、合法角色和重复键闸门 | 内核 3.4–3.6；独立读取端 |
| schema-editor/workspace-draft；schema_save/add_resource tests | 所有结构命令、逐步 undo/redo/字段撤销、净差异、基线/hash、YAML-only、零变更不写、来源路径与 Excel 归属、事务恢复 | 内核 3.10–3.12、4.6；界面 3.3–3.9 |
| schema-editor/workbench；fuzzy/schema browser tests | 三类编辑器、Enum item/ordinal 风险、引用跳转、全局 Quick Open、搜索折叠恢复、类型/索引/依赖视图 | 界面 3.1–3.2、3.7；原生键盘/截图测试 |
| excel-processing；test_reading_compat/test_layout/test_planning | 活跃 Sheet、布局 hash/manifest、原始行号、缺失/损坏 manifest 分支、路径迁移、禁止非空数据丢失 | 内核 1.5–1.6、2.3、3.9、3.13 |
| excel-template-styling；test_canonical_template | 2D 表头、富文本两行字体、合并边框、行列尺寸、A(2D+1)冻结、Enum Note、下拉255限制及 warning、不建隐藏辅助 Sheet、白色数据区 | 内核 1.6、3.9；样式属性及打开检查 |
| data-validation；test_enum_token_gate/test_canonical_validate | 类型/主键/CodeName/ref/Enum、批量结构化错误、Excel 位置；辅助数据验证不是唯一数据闸门 | 内核 2.4–2.6；失败产物不变 |
| json-export / json-single-line-records | 每语言、server_only、嵌套序列化、单记录一行、顺序/Unicode/数字格式 | 内核 3.1、3.7；字节对照 |
| flatbuffers-export / csharp-binary-reader-test | FBS、Bundle、uniform vtable、C#/Lua namespace/API、字段类型、O(1)索引、字符串缓存、ref cache、vector base、稀疏i18n行对齐、语言切换generation与fallback | 内核 3.2–3.7；全部既有生成器测试及独立游戏端对照 |
| i18n-pipeline；test_canonical_i18n/test_state | source骨架、四态、confirmed、orphan、compact dry-run、状态分母、有效译文合并和格式 | 内核 3.7–3.8；界面 4.1–4.3 |
| incremental-export | 无变更mtime、强制写、局部Bundle、输出修复、账本独立、类型/译文依赖；新增解析/ref缓存不得漏校验 | 内核 5.1–5.6；变更/损坏矩阵 |
| export-publication；storage/app publication/input tests | 输入捕获、锁、恢复先于加载、新增清理、删除恢复、晚取消、失败账本、未恢复只读诊断、过滤不清理无关产物 | 内核 4.1–4.6；各阶段故障注入 |
| unity-deploy；test_sync_dir/test_deploy | enabled降级、source/dest解析、for-build、同内容不写、代码meta保留/删除、缺源失败、热导出仍部署、CLI失败账本 | 内核 4.4–4.5；界面 4.4独立部署 |
| web-panel | 翻译表选择器只含i18n、状态筛选/列显隐/长文本、同步和进度、模板状态、模块日志与五条历史 | 界面 4.1–4.8；内核 6.10 |
| web-panel-design-system | 统一视觉、跨模块草稿/任务、持续错误、危险确认、help/about/docs、保存响应不清后续编辑 | 界面 1.2–1.4、3.8–3.9、4.8–4.9 |
| launcher；main.dart/settings/auto_launch/tray/single_instance | 单实例、自启/托盘、窗口生命周期、偏好迁移、内置运行时、安装路径 | 界面 2.2–2.5、4.7、5.3；对应 delta |
| 新增 worker 协议 | 握手、能力、所有业务方法、history/logs/tasks、分页revision、大整数、代次、取消/shutdown、重复ID、未知终态 | 内核 1.4、6.2–6.3、6.10；界面 1.5、2.1、4.6 |
| 性能目标 | 冷全量、热CLI/worker、改单表、译文；输出等价与阶段/RSS配对测量 | 内核 1.2、6.5；界面5.2交互测量 |

## 范围调整（2026-09-17 用户决策）

本次重构不保留旧工具链兼容：不做旧 apply-journal/1、旧历史格式、旧锁文件的迁移，
不提供 Python 回退，验收后删除 Python 实现。产物格式（JSON/FBS/Binary/Accessor）
仍以现行游戏读取端契约为准，Python 产出仅作为格式与性能的验证参照。

## 冲突、替代和明确不迁移的内容

- Web 旧“保存自动改 Excel/删除 Excel”与现行 YAML-only 冲突：保留 YAML-only；模板/翻译/导出显式操作，资源删除不删数据文件。
- 浏览器 HTML/CSS/inert/IndexedDB 的技术形式改为 Flutter 对等交互和应用目录持久化；旧 IndexedDB 草稿不自动导入，首启提示先在旧端保存。localStorage 不是草稿存储。
- 旧固定 720×460 launcher 改为可调原生工作台，最小 1024×700；手机390px布局和 Linux GUI 不属于首发，桌面 Windows/macOS、CLI Windows/macOS/Linux。
- Python `ct panel`、Flask 端口/工具目录回退由原生入口替代；旧 Python 留作隔离对照，不是新版本运行依赖。开发安装和测试入口用 tool-workspace-separation delta 明确更新。
- 当前 incremental-export 要求每次重新解析；本次明确改为有效缓存复用，并同步 cli-interface/unity-deploy 表述；完整正确性覆盖不变。
- i18n-pipeline 标为“未实现”的 stale告警/旧fingerprint联动，不自动扩成迁移必做功能；本次新的有效输入缓存按自己的 delta 验收。
- unity-deploy 标为“未实现”的 Web Deploy阶段/ct status新增deploy输出不照搬；保留现有五阶段与 status 三类。原生独立部署为明确新增入口。
- Excel 模板重建维持当前数据值迁移，不承诺任意附加 Sheet/宏/图表/公式文本的无损保留，也不新增公式计算器；不得宣传成完整Excel编辑。
- `excel-processing` 中标注旧意图/未实现的 custom properties 行为，以现行 layout manifest 实现及测试为准；不恢复废弃元数据格式。
- 生成器对照要求输出字节一致；Excel ZIP容器按实际单元格/样式/迁移语义验证，不要求时间戳等容器字节相同。

## 验收记录要求

每行以现有测试为起点建立新实现的等价场景，不要求把 Python 测试机械翻译为 Rust。无法运行的平台/独立读取端明确保留未完成；OpenSpec strict 只证明规划结构合法，不能证明功能或性能通过。对照发现旧 bug 或规格冲突时记录并显式决定修复范围，不静默削减功能或复制数据损坏行为。

## 逐行验收映射（任务 6.12）

机器可读形式见 `native/docs/baseline/compat-matrix.json`，由
`native/tests/compat/tests/coverage_matrix.rs` 与上表逐行、逐格比对：每行引用的 Python 参照测试
文件必须真实存在且含测试函数，原生锚点文件必须存在且含 `#[test]`/`testWidgets(`，点名的
`文件::测试函数` 必须在对应文件里定义；现行 Python 测试（`ct/tests/web/**` 浏览器端与
`ct/tests/architecture/**` 除外）必须被某一行承接，不允许静默丢覆盖。

- `cli-interface`（cli｜kernel）→ 已验收：`native/crates/ct-cli/tests/cli.rs::export_happy_path_writes_artifacts_and_ledger`、`native/crates/ct-cli/tests/cli.rs::export_unknown_table_and_bad_lang_exit_one`、`native/crates/ct-cli/tests/cli.rs::export_validation_failure_reports_issue_list`；命令级文本/退出码/JSON 形状由 cli.rs 15 例覆盖（含写入/复用计数与缓存命中汇总行）；worker 侧另有 worker_chain.rs 全链对照。
- `tool-workspace-separation`（workspace｜kernel+ui）→ 部分验收：`native/crates/ct-cli/tests/cli.rs::panel_command_gives_migration_guidance`、`native/docs/baseline/isolation-check.md`；Windows 侧已验收（发行包自检 + gd 真实工作区只读对照），macOS/Linux 的包与 PATH 隔离随任务 6.6 在真机/CI 复跑。
- `schema-management`（schema｜kernel）→ 已验收：`native/crates/ct-domain/tests/type_expression.rs::primary_key_type_is_int32`、`native/crates/ct-domain/tests/type_expression.rs::vector_grammar`、`native/crates/ct-domain/tests/config.rs::custom_dirs_resolve_against_root`；schema 加载/拒绝/顺序与资源图由 schema_loading.rs、resource_graph.rs 覆盖；与 Python 逐值对照在 schema_parity.rs。
- `schema-type-system-reader`（schema｜kernel）→ 已验收：`native/tests/compat/tests/canonical_read.rs::clean_rows_match_python`、`native/tests/compat/tests/canonical_read.rs::bad_rows_match_python_issues`、`native/tests/compat/tests/canonical_read.rs::vector_cell_grammar`；同一批夹具上 Rust 与 openpyxl 逐单元格/逐问题对照（含坏值）。
- `query-indexes`（schema｜kernel）→ 已验收：`native/tests/compat/tests/binary_golden.rs::bundle_bytes_match`、`native/tests/compat/tests/validate_gates.rs::duplicate_primary_key_rejected`、`native/tests/compat/tests/validate_gates.rs::codename_empty_and_duplicate_rejected`；索引与 Bundle 字节一致（含碰撞/顺序），闸门在 validate_gates.rs。
- `schema-workspace-draft`（schema｜kernel+ui）→ 已验收：`native/tests/compat/tests/schema_save.rs::save_stale_revision_rejected_and_untouched`、`native/tests/compat/tests/schema_save.rs::save_bad_candidate_hash_rejected`、`native/tests/compat/tests/schema_save.rs::save_writes_only_changed_yaml`；内核侧命令重放/候选/净差异/YAML-only 全部通过；界面编辑器由 native-flutter-workbench 承接。
- `schema-workbench-ui`（ui｜ui）→ 由 native-flutter-workbench 承接：`launcher/test/workbench_test.dart`、`launcher/test/workbench_golden_test.dart`；属于 native-flutter-workbench；本次内核验收只保证协议与数据可用。
- `excel-processing`（excel｜kernel）→ 已验收：`native/tests/compat/tests/layout_manifest.rs::header_nodes_deterministic`、`native/tests/compat/tests/layout_manifest.rs::manifest_payload_matches_golden`、`native/tests/compat/tests/excel_edge.rs::fixture_active_sheet`；读取端与 Python 逐值一致；模板/迁移语义在 template_semantics.rs。
- `excel-template-styling`（excel｜kernel）→ 已验收：`native/tests/compat/tests/template_semantics.rs::template_v1_structure`、`native/tests/compat/tests/template_semantics.rs::template_v2a_structure`、`native/tests/compat/tests/template_semantics.rs::template_readback_via_calamine`；ZIP 内样式 XML 结构断言 + calamine 回读；不承诺任意工作簿无损保留。
- `data-validation`（schema｜kernel）→ 已验收：`native/tests/compat/tests/validate_gates.rs::unknown_enum_token_rejected`、`native/tests/compat/tests/validate_gates.rs::bad_ref_rejected_even_with_table_filter`、`native/tests/compat/tests/validate_gates.rs::deterministic_issue_order`；闸门失败零产物改动由 incremental_matrix.rs::illegal_data_fails_both_modes_and_touches_nothing 佐证。
- `json-export`（export｜kernel）→ 已验收：`native/tests/compat/tests/json_export.rs::json_bytes_match_python`、`native/tests/compat/tests/json_export.rs::json_single_line_records`、`native/tests/compat/tests/json_export.rs::json_empty_table`；server_only 与三语言组合在 export_pipeline.rs 全产物字节对照内。
- `flatbuffers-export`（export｜kernel）→ 部分验收：`native/tests/compat/tests/binary_golden.rs::item_nonuniform_bytes_match`、`native/tests/compat/tests/binary_golden.rs::item_uniform_bytes_match`、`native/tests/compat/tests/binary_golden.rs::sparse_uniform_bytes_match`；生成端字节/API 已验收；Unity 工程内 C# 实读与语言切换 generation/fallback 对照需游戏端环境，本环境未运行（任务 6.12 记为环境受限）。
- `i18n-pipeline`（i18n｜kernel+ui）→ 已验收：`native/tests/compat/tests/i18n_flow.rs::sync_status_compact_roundtrip`、`native/tests/compat/tests/i18n_flow.rs::serialize_format_matches_python`、`native/tests/compat/tests/i18n_flow.rs::merge_entry_rules`；翻译工作台界面由 native-flutter-workbench 承接（界面 4.1–4.3）。
- `incremental-export`（publication｜kernel）→ 已验收：`native/tests/compat/tests/incremental_matrix.rs::unchanged_inputs_keep_bytes_and_mtime_but_all_rewrites`、`native/tests/compat/tests/incremental_matrix.rs::effective_translation_change_updates_only_that_language`、`native/tests/compat/tests/incremental_matrix.rs::inert_translation_metadata_does_not_rebuild_anything`；变更/损坏矩阵与阶段 profile 均已通过（阶段合计耗时、写入/复用计数）。
- `export-publication`（publication｜kernel）→ 已验收：`native/tests/compat/tests/export_pipeline.rs::pipeline_matches_python_byte_for_byte`、`native/tests/compat/tests/export_pipeline.rs::input_change_during_build_blocks_publish`、`native/tests/compat/tests/export_pipeline.rs::partial_export_keeps_other_ledger_entries`；含 CLI 只读诊断（cli.rs::validate_and_status_report_recovery_needed）。
- `unity-deploy`（publication｜kernel）→ 已验收：`native/tests/compat/tests/export_pipeline.rs::deploy_syncs_and_preserves_meta`、`native/tests/compat/tests/export_pipeline.rs::deploy_failure_keeps_ledger_untouched`、`native/crates/ct-cli/tests/cli.rs::deploy_without_config_reports_no_change`；.meta 保留/删除与缺源失败在临时夹具真实验证；界面独立部署入口属 native-flutter-workbench。
- `web-panel`（ui｜ui）→ 部分验收：`native/tests/compat/tests/desktop_history.rs::history_appends_newest_first_and_trims_to_five`、`native/tests/protocol/tests/desktop_state.rs::module_logs_filter_by_module_and_level`、`native/tests/protocol/tests/desktop_state.rs::task_issues_page_and_dismiss_are_connection_scoped`；内核侧历史/日志/任务问题分页已验收；工作台视觉与交互由 native-flutter-workbench 承接。
- `web-panel-design-system`（ui｜ui）→ 由 native-flutter-workbench 承接：`launcher/test/workbench_test.dart`、`launcher/test/workbench_golden_test.dart`；设计令牌与页面回归在 native-flutter-workbench 验收。
- `launcher`（launcher｜ui）→ 环境受限：`launcher/test/protocol/wire_cases_test.dart`；Dart 协议侧在 Windows 已跑（launcher/test/protocol）；macOS 托盘/自启与安装路径需真机验收。
- `worker-protocol`（protocol｜kernel）→ 已验收：`native/tests/protocol/tests/handshake.rs::handshake_declares_version_and_capabilities`、`native/tests/protocol/tests/request_id.rs::duplicate_write_request_executes_only_once`、`native/tests/protocol/tests/pagination.rs::successful_write_invalidates_older_pages`；同源契约夹具同时由 Dart 解码（launcher/test/protocol/wire_cases_test.dart）。
- `performance`（performance｜kernel）→ 进行中：`native/tests/compat/tests/parallel_determinism.rs::peak_memory_recorded_for_bounded_parallelism`、`native/tests/compat/tests/stage_profile.rs::incremental_export_writes_nothing_and_forced_rewrites_all`；S/M/L 夹具与配对测量在任务 1.2/6.5 落地；本环境只有 Windows 真机。

显式检查项（上表未单列、但验收要求逐条确认的行为）：

- server_only 字段只进 JSON、不进客户端产物 → 已验收：`native/tests/compat/tests/json_export.rs::json_bytes_match_python`。server_only 与三语言组合在 export_pipeline.rs 的 11 产物字节对照内。
- 游戏读取端缓存 / 语言切换 generation 与 fallback → 部分（环境受限）：`native/tests/compat/tests/binary_golden.rs::bundle_bytes_match`。Bundle 字节、稀疏 i18n 行对齐与主语言 fallback 已在产物侧对照；Unity 工程内 C# 实读与 generation 切换需游戏端环境，本环境未运行。
- 部署保留/删除代码 .meta → 已验收：`native/tests/compat/tests/export_pipeline.rs::deploy_syncs_and_preserves_meta`。临时夹具里预置旧文件+旧 .meta+孤儿 .meta，验证 GUID 保留与连带删除。
- for-build 目标范围 → 已验收：`native/crates/ct-cli/tests/cli.rs::deploy_without_config_reports_no_change`。CLI --for-build 与 worker deploy 共用 ct_export::deploy；未配置时输出与 Python 一致的跳过提示。
- 部署缺源失败且账本不推进 → 已验收：`native/tests/compat/tests/export_pipeline.rs::deploy_failure_keeps_ledger_untouched`。本地产物保留、cache/state.json 不写入，错误分类为 RunError::Deploy。
- 解析/ref 缓存不得漏掉校验 → 已验收：`native/tests/compat/tests/incremental_matrix.rs::illegal_data_fails_both_modes_and_touches_nothing`。非法数据在增量与 --all 两种模式下都失败且零改动；ref 目标主键变更由 fingerprints.rs 触发失效。
- 独立运行时包不依赖 Python → 已验收（仅 Windows 真跑）：`native/crates/ct-xtask/src/dist.rs`。dist 自检把 PATH 收敛为包内单目录并清 PYTHON* 变量，真跑 validate/status/export/worker；macOS/Linux 需在 CI 或真机复跑。
- 旧格式不迁移（不做旧工具链兼容） → 已验收：`native/tests/compat/tests/desktop_history.rs::unknown_history_format_is_ignored_then_replaced`。旧 apply-journal/1、旧桌面历史、旧锁文件不迁移：保留材料并拒绝在其上写入（publication_recovery.rs 同组）。

明确不迁移/不照搬的历史规格与理由：

- Web 面板「保存自动改 Excel/删除 Excel」：与现行 YAML-only 冲突，按 coverage.md 决策保留 YAML-only；模板/翻译/导出为显式操作。
- 浏览器 HTML/CSS/inert/IndexedDB 草稿与 localStorage：改为 Flutter 工作台 + 应用目录持久化；旧 IndexedDB 草稿不自动导入（native-flutter-workbench）。
- 720×460 固定 launcher 窗口、手机 390px 布局、Linux GUI：改为可调原生工作台（最小 1024×700），首发桌面 Windows/macOS；手机与 Linux GUI 不在范围内。
- ct panel / Flask 端口与工具目录回退：由原生入口替代；旧 Python 只作隔离对照，不是新运行依赖。
- incremental-export 的「每次重新解析」表述：本次明确改为有效缓存复用（任务 5.1–5.6 已验收），规格文字在 6.8 同步。
- i18n-pipeline 中标注未实现的 stale 告警/旧 fingerprint 联动：不自动扩成本次必做；新的有效输入缓存按自己的 delta 验收。
- unity-deploy 的 Web Deploy 阶段与 ct status 部署输出：不照搬；保留现有五阶段与 status 三类，原生独立部署为新增入口。
- 任意附加 Sheet/宏/图表/公式文本的无损保留：模板重建只承诺当前数据值迁移，不提供公式计算器，也不宣传为完整 Excel 编辑。
- excel-processing 的 custom properties 旧意图：以现行 layout manifest 实现与测试为准，不恢复废弃元数据格式。
- Excel ZIP 容器时间戳等字节级一致：容器按单元格/样式/迁移语义验证；只有导出产物要求逐字节一致。

验收证据索引：产物与诊断一致性见 `native/docs/baseline/parity-report.md`；性能原始数据见
`native/docs/baseline/bench-*-windows.json`；CLI 文本对照见 `native/docs/baseline/cli-text-diff.md`；
基线源码树指纹见 `native/docs/baseline/source-tree.json`。
