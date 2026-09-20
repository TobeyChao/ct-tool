## 1. 视觉样板与契约接入准备

- [x] 1.1 以 ../rust-native-core/coverage.md 为基线细化原生测试映射，逐项标注页面、内核方法和验收场景，验证无遗漏的保存/模板/i18n/部署入口。  - 产出：`openspec/changes/native-flutter-workbench/coverage.md` —— 以 `../rust-native-core/coverage.md`
    的 21 行为基线，逐行标出「页面/组件 → 内核方法 → spec 验收场景 → 证据」，并附三张核对表：
    写入口清点（10 类）、25 个协议方法的桌面侧触达矩阵、缺口与去向。
  - 无遗漏结论是脚本核对出来的，不是数出来的：写方法 `schema.save`、`template.plan/generate`、
    `i18n.save/sync/compact`、`export`、`deploy`、`cancel`、`tasks.dismiss`、`workspace.recover`
    逐个都有界面入口 widget key、内核门禁与测试文件对应（第 2 节表格）；四类「保存/模板/i18n/部署」
    各自只有一条写路径，界面不重复裁决。
  - 同时暴露 3 个真实缺口并写明去向（不悄悄跳过）：`validate` 尚无桌面按钮（5.4 补）、
    `workspace.snapshot`/`workspace.status` 确认不接（5.7 按「无界面入口」核销）。
  - 口径：Dart 44 个测试文件 / **283 例**（`flutter test --reporter json` 汇总，golden 矩阵展开后 17 例）、
    17 张 golden 截图、Rust **270 passed**；复算命令写在 coverage.md 第 5 节。

- [x] 1.2 整理现有深林绿令牌与基础控件，交付按钮、字段行、状态、焦点和中英文字体样板并人工检查一致性。
- [x] 1.3 实现工作台壳、资源区、主编辑区、可调属性区和底部任务区，使用明确标识的模拟数据运行桌面样板。
- [x] 1.4 补齐空态、错误、长文本、忙碌与冲突状态，在规定尺寸/缩放矩阵保存截图并修复遮挡、错位及溢出。
- [x] 1.5 接收 rust-native-core 第 1 阶段产出的协议 v1 和样例，建立 Dart DTO/传输接口，验证能解析同源消息与大整数标签。

## 2. 本地运行时与工作区

- [x] 2.1 替换 panel 启动服务为 stdio worker client，验证握手、消息关联、分页和 stderr 隔离；版本不兼容时写入口禁用。
  - 证据：`launcher/lib/services/worker_service.dart`（`StdioWorkerTransport` + `WorkerService`）与
    `launcher/test/services/worker_service_test.dart`（11 例，`flutter test` 全绿）：握手记录协议版本/能力、
    requestId 唯一且乱序终态各归其请求、失败终态透传 `issues[]`、连接级错误整体降级、对端断开时挂起请求
    以 `transport-closed` 收口不悬挂、`stop()` 先发 shutdown 再关 stdin、`cancel` 带 `targetRequestId`；
    对端回显版本 99 时 `writeBlockReason()` 报「不兼容」并禁用写入口。两条真实进程用例直接连 `ct worker`：
    `workspace.open` → `status=ready` + revision/tables 且 stderr 行不进入协议；`logs.list` 以
    `page.limit=1` 连续翻页保持同代次、逐页换行、篡改游标返回 `stale-page`。
- [x] 2.2 实现内置运行时发现和显式开发路径，验证缺文件/错误架构/中文空格路径可诊断且不回退 Python。
  - 证据：`launcher/lib/services/native_runtime.dart` 只有「应用包内置 → 设置里的显式路径」两条来源；
    `launcher/test/services/native_runtime_test.dart`（10 例）覆盖三平台布局、内置缺失、开发路径缺失、
    开发路径填成目录，以及「定位器自身从不提出 python/.venv 路径」。中文+空格路径与无解释器环境由
    `cargo run -p ct-xtask -- dist` 自检和 `native/docs/baseline/isolation-check.md` 实证；启动失败
    （错误架构/权限）时 `WorkerService.start()` 把 `ProcessException` 与 stderr 前 5 行落成可诊断原因。
    `launcher/tool/build_windows.ps1` 默认嵌入 `native/dist` 原生运行时到 `runtime\ct.exe`（与定位器布局
    一致，实测报 `ct 0.0.0`），仅保留 `-LegacyPythonRuntime` 作为面板未下线前的过渡开关。
- [x] 2.3 实现工作区切换、总览、资源列表和只读预览，验证旧工作区事件不会更新当前视图。
  - 证据：数据契约 `lib/ui/workbench/workbench_models.dart`（`WorkbenchData`/`WorkbenchResource`/`WorkbenchField`
    与 `sampleData`），真实来源 `lib/state/workbench_repository.dart`（`workspace.open` → `resources.list` →
    按需 `table.preview`），工作台壳 `workbench_screen.dart` 改为只认契约并支持 `refresh`/`onResourceSelected`；
    旧 mock 文件只留类型别名，总览的“模拟数据”占位改为真实分类计数。
    `test/state/workbench_repository_test.dart`（7 例，含**真实 ct worker** 读通 Item/Rarity 与预览 2 行）与
    `test/workbench_live_test.dart`（3 例界面侧）：切换工作区后 A 的迟到回包既不渲染也不触发重绘（断言
    `generation == 2`、`workspaceId` 仍为 B、重绘次数不变）；旧 `workspaceId` 的事件被丢弃；打开失败时界面
    显示内核原文错误。`flutter test` 95 例全绿、`flutter analyze` 0 issues。
- [x] 2.4 迁移有效工作区与桌面偏好并废弃 host/port/Python 配置，重启验证保留值和实际启动参数。
  - 证据：`lib/services/settings_store.dart` 只保留工作区/可选运行时路径/自启/托盘常驻四项；`load` 清除
    `tool_dir`、`port`、`host`、`python_path` 旧键并置 `migratedFromLegacy`，`legacyKeysCleared()` 供复验。
    `lib/ui/workbench/workbench_settings.dart` + 工作台「设置」模块提供工作区选择、重新读取、指定/回落原生
    运行时与内核来源摘要；`lib/app.dart` 的入口已从面板服务改为 `WorkerService` + `WorkbenchRepository` +
    `WorkbenchScreen`（退出/关闭先 `shutdown` worker），`panel_service.dart` 与旧 `launcher_screen/overview/logs/settings`
    面板壳一并删除。
    测试：`test/settings_store_test.dart`（4 例：旧键清除+偏好保留、模拟重启后值保留、运行时回落自动推断、
    **设置里的 runtimePath 即 worker 实际启动的那个**并读出 Item/Rarity）与 `test/workbench_settings_test.dart`
    （4 例：内核来源可见、迁移提示、托盘开关即时写回且重启保留、重新读取真的再走内核请求）；界面不再出现
    「端口/工具目录/.venv」配置项。`flutter test` 91 例全绿。
  - 顺带完成 2.5 的一半：`lib/main.dart` 窗口改为可调、默认 1280×800、最小 1024×700（不再继承旧的不可调设置）。

- [ ] 2.5 保留单实例/自启/托盘并改主窗口为可调尺寸，验证双启动不增 worker、系统自启状态一致且不继承旧不可调窗口设置。
  - 已落地：`lib/services/window_options.dart`（默认 1280×800、最小 1024×700、可调，
    `main.dart` 改用它且不再继承旧的不可调窗口设置）；`SingleInstanceLock` 支持注入目录、
    暴露 `held`、`release()`，并把「锁真的被别进程持有(TimeoutException)」与「查不出来」分开——
    后者 fail-open 且把原因打到 stderr；`SettingsStore.legacyKeys` 追加
    `window_width/height/x/y/resizable/maximized` 六个旧键一并清除。
    测试：`test/services/desktop_shell_test.dart` 3 例。
  - 未勾原因：双启动不增 worker、系统自启状态一致这两条要真机双进程/真注册表，
    同进程 widget 测不出来；连同异常退出与旧版本回滚一并归 5.5 的验收矩阵。

## 3. Schema 工作台

- [x] 3.1 接入 Table/Record/Enum 创建、编辑、改名、删除和导航，验证空工作区创建及同草稿类型相互引用。
  - 证据：命令词表与 payload 由内核拥有，客户端只拼装 —— `lib/state/schema_draft.dart`
    （`add_resource / rename_resource / delete_resource / add_field / rename_field / delete_field /
    set_property / set_type / set_enum_values` + `CommandLog` 游标）；`lib/state/workbench_repository.dart`
    把命令投影进资源清单（草稿项标 `dirty`、路径提示「保存后由内核落盘」），并以 `resources.list`
    新返回的 `schemaRevision` 作草稿基线（协议文档方法表已同步该字段与「撤销只移动 cursor」约定）。
    界面 `lib/ui/workbench/workbench_schema_editor.dart` 挂在资源区：新建/改名/删除/加字段/撤销/重做/
    丢弃/算候选可用，未选中资源时依赖选中的动作禁用。
  - 测试：`test/state/schema_draft_test.dart`（7 例，命令形状与游标语义）、
    `test/state/workbench_repository_test.dart`「草稿投影与候选」组（8 例：切换工作区即丢草稿、
    旧候选回声被拒、内核拒绝时错误码交给界面等）、`test/workbench_schema_editor_test.dart`（5 例界面侧），
    以及 `test/state/schema_draft_kernel_test.dart`（4 例，**直连真实 ct worker**：空工作区创建三类资源且
    候选无阻塞问题、同一草稿内 Record 被 Table 字段引用被内核接受、未声明类型被内核拒绝、
    改名走内核级联并出现在 netDiff.changed）。`flutter test` 115 例全绿。
- [x] 3.2 实现字段类型/角色/约束、索引与属性编辑，复用内核候选问题定位，验证不生成非法组合。
  - 证据：内核先补上编辑器的真实状态出口——resources.list 的 Table 条目新增 `indexes`（已声明的索引
    kind），table.preview 的列新增 `i18n`/`serverOnly`/`comment`/`ref`/`excelColumns`（未声明即缺席，
    见 native/docs/protocol/v1.md 与 native/tests/protocol/tests/editor_state.rs）。
    WorkbenchRepository 用预览列做字段行种子，草稿投影补齐 move_field/set_indexes/rename_enum_item，
    属性投影与内核白名单一致（comment/i18n/server_only/excel_columns/ref）。属性区
    workbench_field_editor.dart 提供改类型、i18n 与 server_only 开关、注释、ref（可清除）、
    展开组数（可清除）、上移/下移/删除、枚举成员改名（带 originalOrdinal）与 codename 索引勾选；
    客户端不做第二套校验：candidateProblems 同时接收「带问题的候选」与「被内核拒绝的候选」两种
    明细，并按 location 归属到资源/字段；主键字段禁删禁调序，界面明说内核未提供改主键命令。
  - 顺带修出的真问题：set_type 的参数键是内核的 `type_text`（原实现写 typeText 会被拒）；
    set_indexes 的 table 必须是资源 id `table:Item`（候选按 resource_id 合并索引），原实现传裸表名
    会静默无效。两处都由新增的内核测试抓到并修正。
  - 测试：test/state/field_editor_kernel_test.dart 5 例（直连真实 ct worker：属性与索引回显来自内核、
    i18n+server_only 非法组合被内核拦住且 YAML 一字节未动、excel_columns 用在 int32 上被拒绝、
    合法编辑保存只改 YAML 并真的移除 codename 索引、ordinal 错位被内核拒绝）；
    test/state/field_editor_test.dart 6 例（命令形状、投影、撤销、问题归属）；
    test/workbench_field_editor_test.dart 4 例界面侧（开关回显内核状态、改动只进草稿、
    主键不给删除/调序、非法组合的问题块原样列出内核文本）。
- [x] 3.3 接入命令日志、cursor、undo/redo 与净差异，验证新增后删除归零及候选刷新不改变基线。
  - 证据：`lib/state/schema_draft.dart` 的 `CommandLog`（append 截断 redo 分支、undo/redo 只移动游标）
    与 `WorkbenchRepository` 的 `commands/cursor/candidate`；工具栏撤销/重做按钮与「差异」对话框
    （`_showCandidateDialog`）全部呈现内核回包：candidateHash、新增/修改/删除计数与阻塞问题数。
    线格式约定：**commands 全量送、撤销只移动 cursor**，生效前缀由内核解释（`native/docs/protocol/v1.md` 已记）。
  - 测试：`test/state/schema_save_kernel_test.dart`「净差异：新增后再删除应归零；候选刷新不改变基线」
    （真实 worker：一加一删 → `netDiff` 三列表全为 0；连续两次候选 `candidateHash` 相同且 `schemaBaseline` 不变）、
    `test/workbench_schema_editor_test.dart`「差异按钮弹出内核净差异与问题计数」、
    `test/state/workbench_repository_test.dart` 草稿组（游标进请求、旧回声被拒、内核拒绝时交出错误码）。
- [x] 3.4 接入 schemaRevision/candidateHash 保存，验证外部改 YAML、候选过期、busy 与发布失败保留草稿。
  - 证据：`SchemaSaveParams`（`launcher/lib/services/protocol/dto.dart`）带
    `schemaRevision + candidateHash + commands + cursor`；`WorkbenchRepository.saveDraft()` 只在
    「有草稿 + 已有无阻塞问题的候选 + 基线非空」时放行，成功即清草稿并重读清单（新基线来自内核响应）；
    **任何拒绝都保留草稿**、只作废候选并刷新基线供重算。工具栏保存按钮接入该方法（mock 场景仍保留提示）。
  - 测试（直连真实 `ct worker`，`test/state/schema_save_kernel_test.dart` 5 例）：
    ① 保存成功 → 新 `schemaRevision` 为 64 位、`excel/i18n/output/cache` 均未被创建、
      `.ct/export-publication.json` 不留残留、清单改由内核提供且不再标草稿（YAML-only）；
    ② 外部改 YAML（新增 schema 成员）→ 旧基线被拒、`draftCount` 仍为 1、外部文件未被覆盖、
      `hero.yaml` 根本没写出、其余 config 文件内容指纹不变、旧候选作废且基线已刷新；
    ③ 伪造 `candidateHash`（等价于服务器重建不一致 / 事务前失败）→ 内核拒绝且带结构化 `issues[]`，
      整个 config 指纹不变；
    ④ 导出写任务占用工作区（busy）→ 保存被拒、草稿保留、目标 YAML 未产生；
    ⑤ 净差异归零与候选刷新不改基线（同时作为 3.3 的验收）。
    界面侧：`test/workbench_schema_editor_test.dart`「真实草稿下保存走双守卫请求，成功后清空草稿」
    断言发出的四个守卫参数与保存后 `草稿 0 条`。`flutter test` 122 例全绿。
- [x] 3.5 实现用户目录草稿存储与恢复，验证同基线重启恢复、异基线冲突提示、工作区隔离和旧浏览器草稿迁移提示。
  - 证据：新增 launcher/lib/state/draft_store.dart —— 信封含 formatVersion、工作区身份、原始基线、
    完整 commands 与 cursor；写盘是 tmp + rename 的原子替换，文件名用自己实现的 FNV-1a（不用
    Object.hash：它不保证跨运行稳定，重启就找不到自己的草稿），路径分隔符与大小写归一后同一工作区
    只有一份文件。WorkbenchRepository 在每次入草稿/撤销/重做/放弃/保存成功后落盘，
    switchWorkspace 读回基线之后 restoreDraft()：基线一致才原样承接命令与游标（redo 分支保留），
    基线不同只报冲突、损坏只报路径，两者都不套用也不删文件；不注入 store 时完全不碰文件系统
    （样板与单测默认如此）。
  - 界面：总览新增 WorkbenchDraftBanners（冲突/未落盘/损坏留档/旧浏览器草稿一次性提示），
    编辑面板显示 draftPersistLabel 落盘状态；app.dart 把设置并入 refresh 合并监听，
    「知道了」立即生效并跨重启保留；退出守卫新增 draftNotPersisted，草稿未落盘时不许静默退出。
  - 测试：test/state/draft_store_test.dart 8 例（四要素齐全、按工作区隔离且文件名跨进程稳定、
    原子无残留临时文件、冲突只报不删、空草稿删档、损坏判 damaged 且可留档查看、缺字段一律不可靠、
    归属与文件名不一致视为 damaged）；test/state/workbench_repository_draft_test.dart 8 例（编辑即落盘、
    同基线重启恢复命令+游标、撤销过的草稿不重放 redo 分支、基线变化只报冲突且文件仍在、损坏草稿给路径、
    写失败仍保留内存编辑并持续警告、未注入 store 时零文件副作用、换工作区互不串档）；
    test/workbench_draft_banners_test.dart 5 例界面侧。
- [x] 3.6 接入显式模板预检/生成和状态刷新，验证保存仅改 YAML、迁移失败不覆盖 Excel，Record/Enum 无模板按钮。
  - 证据：新增 launcher/lib/state/template_service.dart（template.plan / template.generate，参数就是裸表名）
    与 workbench_template_panel.dart：主编辑区底部按选中资源显示——Table 才给「迁移预检 / 生成模板」，
    Record/Enum 显示「没有独立 Excel 模板」而不是放假按钮；生成按钮只在最新预检 canGenerate 为真时可用，
    预检的 actions/warnings/problems 与内核文本原样列出；生成成功后立刻再预检一次，界面不留在旧结论上。
  - 测试：test/state/template_service_test.dart 7 例（未预检不发写请求、参数形状、生成后重查、
    阻塞时按钮禁用且请求发不出去、内核拒绝不改判成功、预检失败不假装可生成、换资源清掉旧预检）；
    test/state/template_kernel_test.dart 3 例（真实 ct worker：新建表保存后只有 quest.yaml、
    excel/Quest.xlsx 不存在，预检报「生成空模板」→ 显式生成后工作簿才出现且 Item.xlsx 字节不变；
    抹掉布局 manifest 后预检阻塞、生成请求根本不发、Excel 一字节不动；对 Enum 预检由内核直接拒绝）；
    test/workbench_template_panel_test.dart 3 例界面侧（含 Enum 无入口）。

- [x] 3.7 补齐 Enum item 追加/改名/重排及 ordinal 风险、类型/ref 跳转和全局 Quick Open，验证 originalOrdinal、空查询最近项、pane 关闭和跨模块键盘操作。
  - 证据：Quick Open 是 `lib/ui/workbench/workbench_quick_open.dart` —— 资源清单取自
    `resources.list`，空查询把「最近打开」排在最前（按工作区键 `wb.<key>.recents` 持久化在偏好里，
    上限 8 条），fuzzy 用子序列 + 连续/词首加权；上/下键 + Enter 纯键盘可选，Esc 关闭面板。
  - 证据：类型/ref 跳转在 `workbench_screen.dart` 的 `_linkCell` —— 类型（Record/Enum）与
    `Table.Primary` 形态的 ref（先剥掉 `.Primary` 段）能对上内核资源名就渲染成链接，点击切主区，
    来源压栈后工具条出现返回按钮。
  - 证据：枚举成员四项都通了 —— 追加工具条「加成员」（整表 `set_enum_values`，owner 用
    `enum:Name` 形态）、属性区改名走 `rename_enum_item` 带 `originalOrdinal`、上移/下移/删除成员
    一律整表改写（内核 `fields_of(Enum)` 明确返回「没有字段列表」，move_field/delete_field 走不通），
    并在工具条与属性区各留一条 ordinal/wire 风险提示。
  - 前置修复：这条本来不可达 —— 清单里没有成员清单，未编辑过的枚举在界面上是空的。已让
    `resources.list` 随条目返回 `fields`/`values`/`primary`（词表与 `field_to_data` 一致，
    成员统一 `{name, comment}`），见 `native/crates/ct-worker/src/methods/resources.rs` 与
    `ct-cli/tests/worker_chain.rs` 的新断言。
  - 测试：`test/ui/workbench_navigation_test.dart` 5 例（类型链接跳转+返回栈、`Item.Id` ref 跳转、
    追加成员命令形状、重排/删除必须整表改写、Quick Open Esc 关闭 + 最近打开持久化）。
- [x] 3.8 实现代次过滤与保存期间草稿冻结，验证乱序候选不能覆盖当前 hash，保存成功后状态刷新失败不恢复旧草稿。
  - 证据：候选落地要同时满足两层校验——回声 `draftGeneration` 等于本次请求发出的代次，
    **且**该代次仍等于仓库当前最新代次；只比前者是本项修出的真缺陷（第 1 代晚到会把手上的
    `hash-2` 覆盖回 `hash-1`）。保存进行中冻结全部编辑入口（入草稿、撤销、重做、放弃）并给出
    可见原因 `wb.draftError`；`saveDraft()` 在 `_saving` 期间直接返回 null，重复提交发不出第二条
    `schema.save`。保存成功的落地顺序改为「先清草稿+换基线+作废候选，再刷新状态」：刷新失败只报
    `wb.refreshError`（“YAML 已保存，但状态刷新失败”），草稿不回来、不要求重存，也不会被误报成保存失败。
    另按规格补齐「净差异为零禁用保存」（空事务不该占用一次提交）。
  - 测试：`test/state/workbench_repository_gate_test.dart` 6 例（旧响应迟到不覆盖、基线不被候选推进、
    保存期冻结编辑、重复提交只发一次、刷新失败仍算已保存、零差异禁保存、守卫失配保留草稿并刷新基线）。
- [x] 3.9 验证原子草稿写入的权限/磁盘满/中断/旧格式场景，持续警告且保留原始材料；退出不能将失败持久化视为已保留。
  - 证据：`DraftStore` 写入是 `.tmp` + flush + rename；读取端把中断残留的 `.tmp` **如实报告并清走**
    （`DraftLoad.leftoverTemp`），半截/不认识的信封一律 `damaged` 并保留原文件（`preserve()` 改名留档），
    目录本身不可用（被文件占用/权限/只读介质）时读取返回 `none + reason`，仓库据此把
    `draftPersisted=false` 并显示「草稿尚未落盘」警告与「重试落盘」入口——**不会**把"读不到"说成"没有草稿"。
    退出守卫新增 `draftNotPersisted`：只要内存里还有未持久化的编辑就必须征询，风险条单列“尚未写入用户目录”，
    用户仍可显式选择「仍退出」，但不会被静默当成已保留。
  - 诚实边界：ENOSPC（磁盘满）无法在本机测试里可靠构造，它与上述写失败走同一条 `save()` 异常路径，
    由「目录不可用」一例覆盖；真机磁盘满/断电留待任务 5.5 的异常退出演练补实测，不在此项内宣称已验。
  - 测试：`test/state/draft_store_faults_test.dart` 7 例（原子且无旁路文件、`.tmp` 残留报告并清除、
    只有半截临时件时绝不当作草稿、正式件被写坏→damaged+保留+可留档、更高格式版本不可靠、
    目录不可用时 save 抛错而 load 不崩、清空幂等）；`test/services/exit_guard_test.dart` 新增 2 例
    （未持久化必须征询；提示单列一条且仍可显式退出）。`flutter test` 255 例全绿。

## 4. 翻译、导出和任务生命周期

- [x] 4.1 实现翻译表/语言/状态筛选、列显隐和分页，验证切表及更新行后筛选状态保留。
  - 证据：launcher/lib/state/translation_repository.dart + workbench_i18n_view.dart 挂上「翻译」模块。
    表下拉取自资源清单，语言下拉取自 i18n.status（不硬编码语言），状态筛选把 status 交给
    i18n.query 由内核过滤；分页用内核的 page.limit + nextCursor，「已取 N 条（代次 R）」就是实际
    取到的条数。切表与保存行都只重置分页，筛选与列显隐保留；「全部状态」不伪造 status 键。
  - 测试：test/state/translation_repository_test.dart「状态筛选与分页都由内核执行；切表与保存行之后
    筛选保留」「加载更多带上一次游标，末页之后不再可加载」；test/state/translation_kernel_test.dart
    「译文条目与状态由内核给出，状态筛选在内核执行」（真内核：无 source 时状态一律 orphan，界面
    不改判；同步后筛选 translated 返回的行确实都是 translated）；test/workbench_i18n_view_test.dart
    对应两例界面侧。
- [x] 4.2 接入行内失焦保存、长文本对照和取消，验证条目 text/confirmed/status 与保存范围正确。
  - 证据：_EditableCell 失焦（或回车）才提交，Esc 恢复原值并 cancelEdit()；提交前先比对「文本与
    确认位都没变」→ 直接不发请求；saveRow 一次只送一条 i18n.save（table/lang/key/text/confirmed
    全带上），成功后用内核回包的 status 更新该行，不自己推断、也不顺手重查整页；确认位走同一通道
    单条提交。长文本对照按钮打开对话框，原文与译文都是可选中全文。
  - 测试：test/state/translation_repository_test.dart「行内保存只发一条请求，状态取内核回包」
    「未改动的行不产生写请求；取消编辑只清高亮」（含不存在的键不送内核）；
    test/state/translation_kernel_test.dart「单条保存只改该语言文件，状态由内核重判」（真内核写盘后
    断言 schema YAML 与 Excel 字节不变）与「未知语言由内核拒绝，界面不谎报保存成功」；
    test/workbench_i18n_view_test.dart「译文失焦即保存，只发一条 i18n.save」。
- [x] 4.3 接入 sync、进度总览及 compact 范围确认，验证 orphan 清理不会影响其他表或语言。
  - 证据：进度总览直接渲染 i18n.status 的每语言 translated/missing/stale/orphan 计数；同步分「同步全库」
    与「同步本表」（后者才带 table 参数），结果按内核 {tables, inserted} 显示。清理是两段式：
    wb.i18nCompactPreview 先发 dryRun:true 并展示内核给的待删键列表，用户必须在确认框再点一次
    「确认清理」才发 dryRun:false；未确认时一条写请求都不发。
  - 测试：test/state/translation_repository_test.dart「同步范围由参数决定」「清理必须先预检：dry-run
    不回写，显式执行才删」「写任务被内核拒绝时给出错误码，不谎报成功」；
    test/state/translation_kernel_test.dart「sync 重建 source 集合，之后进度总览有真实计数」
    「compact 预检只报告不写盘，显式执行才删孤立且不牵连其它条目」（真内核：手工塞入 9999.Name，
    预检列出它且文件不变；执行后只少它一条，1001.Name 仍在）与「source 缺失时内核不肯清理」；
    test/workbench_i18n_view_test.dart「清理孤立必须先预检，确认后才执行写操作」「取消预检不会执行
    任何写操作」「同步与进度总览显示内核给出的数字」。
- [x] 4.4 接入导出过滤、阶段/耗时/缓存统计和可定位错误，验证桌面导出不自动部署、独立部署可用。
  - 证据：`launcher/lib/state/export_runner.dart` 把界面过滤条件一比一拼成 `export` 参数
    （`table`/`lang` 只在非空时送、`all` 始终显式送；`all` 按内核语义是**强制重建绕过缓存**，
    不是「全部表」，界面文案照此写），终态直接采用内核 `ExportResult`：`outcome/tables/durationMs/`
    `stages[].elapsedMs`/`cache.hits|misses`/`issues[]`；部署是另一条显式 `deploy` 请求
    （`forBuild` 参数），桌面导出不自动部署。`launcher/lib/ui/workbench/workbench_export_view.dart`
    渲染阶段进度条（`progress` 事件）、结果卡（表数/耗时/缓存命中比/逐阶段耗时）、问题卡与运行日志；
    问题「定位」把内核给的 `Issue.resource` 原样交给壳层 `_locateIssue`，切到 Schema 模块并选中该资源。
  - 测试：`test/state/export_runner_test.dart` 10 例（参数拼装、导出不得顺带部署、progress/issue 按
    requestId 与 seq 单调汇入、取消只转达意图、busy 不覆盖状态、断连不重放）；
    `test/workbench_export_view_test.dart` 7 例界面侧；`test/state/export_runner_kernel_test.dart` 4 例
    **直连真实 ct worker**（阶段/耗时/缓存非哑值、`tasks.list` 里从未出现 deploy、单表过滤 tables=1、
    未知表名/语言由内核拒绝并交出错误文本。
- [x] 4.5 实现有界日志列表和最近五次导出历史，验证大量事件可滚动且结果按任务归属。
  - 证据：`lib/state/desktop_state.dart` 用 `logs.list` 的 `page.limit=200` 分页 + `nextCursor`
    续拉（界面是有界 `ListView`，滚到底给「加载更多日志」入口，列表项数即已取条数），
    `history.list` 提供最新在前最多 5 条；实时 `log` 事件也按当前工作区追加并设有上限。
  - 测试：`test/state/desktop_state_test.dart`「bind 一次拉齐三张表」「加载更多走下一页游标，
    末页之后不再可加载」；`test/workbench_desktop_panel_test.dart`「日志页有界分页：可滚动并继续加载，
    筛选由内核执行」（120 → 150 条、游标耗尽后按钮消失）与「历史页显示最近记录并归一旧状态码」；
    `test/state/desktop_state_kernel_test.dart`（真实 worker）断言导出后日志/历史确有内容、
    历史 `result=success`、`tables>=1`。
- [x] 4.6 实现取消、busy、断连未知终态与重连，验证发布后取消不会误报取消、不自动重放写请求。
  - 证据：`ExportRunner.cancel()` 只在 `running` 且已拿到内核事件里的 `requestId` 时才发
    `cancel{targetRequestId}`，且只记录内核回执（`cancelling/already_terminal/unknown_request`），
    **不改写阶段**；终态仍以内核 `result.outcome` 为准，发布之后返回成功就显示成功。
    `busy`（含 `schema-revision`/`candidate-hash` 类拒绝的映射码）走单独分支：回到发起前阶段、
    只给「内核忙等」提示、不写结果卡。断连由 `app.dart` 的 `_onWorkerChanged` 调
    `markDisconnected()`：阶段置 `unknown`、代次自增使迟到的终态作废，明确不自动重放写请求，
    `needsUserDecision` 让界面提示用户自己决定；重连通过设置「重新读取」/托盘重载走
    `_openWorkspace(force: true)` 并 `_rebuildRunner`，旧工作区的运行状态不带进新连接。
  - 测试：`test/state/export_runner_test.dart`「取消只转达意图：带 targetRequestId，且不把成功改写成取消」
    「busy 不覆盖状态：回到原阶段并只给提示」「断连标为终态未知，且不自动重放写请求」；
    `test/workbench_export_view_test.dart`「取消要等首个带 requestId 的事件，点击只转达意图」
    「断连后标为终态未知并明确不自动重放」；`test/state/export_runner_kernel_test.dart`
    「终态之后的取消不改写成功：客户端不发请求，内核回绝陌生 requestId」（真内核回 `unknown_request`）。
- [x] 4.7 实现托盘隐藏、显式退出及安全 shutdown，验证未保存草稿/运行任务的退出选择和异常退出恢复。
  - 证据：新增 `launcher/lib/services/exit_guard.dart`——`needsExitPrompt` 只看「有未保存草稿」或
    「有写任务在跑」这两个客观事实，都没有就直接放行不啰嗦；对话框把风险逐条陈述，
    提供「留下 / 先隐藏到托盘（仅在跑任务且托盘常驻）/ 仍退出」，关掉对话框等同「留下」。
    `app.dart` 把三条退出入口（托盘「退出」、设置里的「退出应用」、窗口关闭与 Cmd+Q）统一收敛到
    `_requestExit()`：托盘常驻时关窗只是 `_hideToTray()`（不动数据、不弹确认），确认退出前先
    `markDisconnected()` 再 `_quit()`（`shutdown` → 关 stdin → 超时才强杀），并删掉了旧的
    「3 秒后 `exit(0)` 兜底」计时器。异常退出恢复：`WorkbenchRepository` 暴露
    `recoveryNeeded/recoveryJournals/recover()`（结论取自 `workspace.open` 的 `recovery`），
    总览在有未完成事务时显示横幅 + 「恢复」按钮，恢复结果按内核 `recovered/noop/blocked` 原样呈现，
    只有内核真的清掉事务后横幅才消失。
  - 测试：`test/services/exit_guard_test.dart` 5 例（needsExitPrompt 真值表、无风险直接放行不弹框、
    有草稿时说明风险且「留下」不退出、跑任务时给出「先隐藏到托盘」与「仍退出」两条路、
    关掉对话框等同留下）；`test/state/workbench_recovery_test.dart` 4 例（recovered 后按新快照
    清横幅并按序重读 open+list、noop 不谎报恢复、blocked 原样交出内核 detail 且 revision 缺省、
    内核拒绝时给错误码并保留现场）；`test/workbench_recovery_banner_test.dart` 2 例界面侧；
    `test/workbench_settings_test.dart` 新增「设置里的退出应用只转达意图，由壳层走退出守卫」。

- [x] 4.8 接通 history/logs/tasks 查询与 dismiss，验证旧历史状态归一、重启保留五条、模块/级别筛选、问题分页及已关闭通知不复活。
  - 证据：三张表全部由 `tasks.list / tasks.issues / tasks.dismiss / logs.list / history.list` 提供，
    工作台底部任务区换成「任务 / 日志 / 历史」三页签（`lib/ui/workbench/workbench_desktop_panel.dart`），
    「历史」模块直接渲染内核账本。任务问题**按需**分页（未点不开），分页契约回传 `revision`；
    `dismiss` 后重读任务列表确认 `dismissed`；历史状态码只认 `success/cancelled/error/failed`，
    其余（如旧 `ok`）显示「未知（ok）」不报错也不谎报成功。
  - 测试：`test/state/desktop_state_test.dart` 9 例（含「旧回包与旧事件都不进当前视图」
    「当前工作区终态事件触发任务与历史重查」「实时日志按工作区归属追加」「任务问题按需分页 + 关闭后重读」）；
    `test/state/desktop_state_kernel_test.dart` 2 例（真实 worker：筛选由内核执行、问题分页带代次、
    dismiss 生效，**重连后已关闭通知不复活**、历史跨连接保留且 ≤5 条）；
    `test/workbench_desktop_panel_test.dart` 4 例界面侧。`flutter test` 137 例全绿。
- [x] 4.9 补齐全局草稿条、逐字段撤销、放弃确认、YAML差异、帮助/关于/外部文档入口，逐项验证业务范围说明及真实快捷键。
  - 证据：`lib/ui/workbench/workbench_draft_bar.dart` 的草稿条挂在 Scaffold 顶部，六个模块都在它下面；
    显示草稿步数、净变化资源数（候选没算过时写「净差异未计算」，不猜）与落盘状态，
    并给撤销/重做/步骤/净差异/放弃/保存/跳转/帮助八个入口。
  - 证据：逐字段撤销 = `repo.draftOutline` 的步骤面板，每行一条命令（`describeCommand` 只用内核已有
    字段拼标签），「停在此处」把游标移到该步之后、「回到基线」归零；命令与重做分支都保留。
  - 证据：放弃必须二次确认，文案写明丢弃的是 N 步草稿命令 + 用户目录草稿文件，且不动
    YAML/Excel/翻译/产物。
  - 证据：差异口径如实——内核候选给资源级净差异，界面额外透传 `change`/`oldName` 与
    `fields[].details`（`ordinal 1 → 3 · wire 风险`、`ordinal 不变 · API 名称变化`），
    并显式声明「候选 YAML 不落盘，这里不是逐行文本 diff」。内核侧改动见
    `ct-worker/src/methods/schema.rs::net_diff_of` 与单元测试
    `net_diff_payload_keeps_rename_details`。
  - 证据：`workbench_shortcuts.dart` 是键位的唯一来源，`workbench_about_dialog.dart` 的帮助表直接遍历
    `wbShortcutBindings()`，绝不出现「写的和绑的不一样」；关于框的版本/协议/能力数取自 worker 握手
    （`lib/app.dart::_kernelSummary` 现在多带协议版本与能力数两行）。外部文档入口用 `url_launcher`，
    打不开时如实显示失败原因。
  - 证据：Ctrl/Cmd+P、+S、+Z、+Shift+Z、+Shift+D、F1 六组绑定；输入框聚焦时撤销/重做让给文本撤销
    （`WorkbenchShortcuts.textEditingFocused()`），草稿游标不动。
  - 测试：`test/ui/workbench_draft_bar_test.dart` 10 例。`flutter test` 283 例全绿、
    `flutter analyze lib test` 0 issues、`cargo test --workspace` 270 passed / 0 failed。

## 5. 交互验收与正式包

- [ ] 5.1 完成键盘搜索/保存/undo/redo、焦点恢复、减少动态效果与中文输入法检查，记录 Windows/macOS 验收结果。
- [x] 5.2 在 profile/release 模式以大字段表、分页预览和持续日志验证 UI 响应，记录帧时间并修复业务阻塞 UI 的路径。
  - 跑法与前提：`flutter test` 只能出 debug 构建，所以帧时间用 drive 跑真实 profile 包——
    `flutter drive --driver=test_driver/integration_test.dart --target=integration_test/ui_responsiveness_test.dart -d windows --profile`
    （新增 dev_dependency `integration_test` 与 `test_driver/integration_test.dart`；`CT_WORKER_BIN` 指向 release 内核）。
    用例采 `WidgetsBinding.addTimingsCallback` 的逐帧 build/raster/totalSpan，结论落
    `launcher/test/evidence/responsiveness-profile.md`。
  - 实测（M 档真数据：50 表 × 2000 行 × 20 列，真实 ct worker，预览续到 300 行）：
    大字段表 148 帧 build 0.329/0.893/20.646、raster 1.174/1.465/7.929、totalSpan 2.176/3.154/41.835；
    分页预览 477 帧 build 0.438/0.671/13.19、raster 1.203/1.422/2.169、totalSpan 2.298/3.411/16.894；
    持续日志 94 帧 build 0.202/0.334/1.961、raster 0.423/0.72/1.367、totalSpan 1.331/1.849/3.05
    （单位 ms，格式 p50/p95/max）。断言口径：每阶段帧数 >10、build p95 <8ms、build max <34ms、
    raster p95 <33.4ms、raster max <100ms——p95 距 60Hz 预算有一个数量级的余量。
  - 修掉的阻塞路径：`WorkbenchRepository.resources` 原先**每次读取**都把全部预览行转成单元格文本
    （M 档 300 行 × 20 列 = 6000 次转换），而一帧里界面要读它 5 次以上；改为按键失效的投影缓存
    （键含条目名与 kind、预览行数、预览代次和、草稿命令数与游标、schema 基线）。同阶段 build max
    24.6ms → 20.6ms，p95 0.85 → 0.893ms（本就在噪声内，真正的收益是每帧不再重复 O(n) 投影）。
  - 顺带把「分页预览」做成真的：`loadMorePreview` 走内核游标（追加而非替换、代次变化整页重查、末页禁用），
    页脚从假文案「共 N 行 · 每页 50 · 第 1/1 页 + 两个永远禁用的箭头」换成
    `已显示 N 行 · 每页 50 · 还有更多/已到末页/加载中…/未连接内核` + `wb.previewMore`。
    过程中修掉一个真缺陷：续页里嵌套调用 `loadPreview(force)` 会被自己的「在途」标记挡掉，
    导致快照代次变化时不重查——`test/state/workbench_repository_preview_test.dart` 抓到并钉住。
  - 测试：新增 5 例（预览分页 3 + 界面页脚 2），`flutter test` **301 例全绿**；`workbench_live_test` 的页脚断言同步更新。
  - 剩余如实记录：选表后首帧 build 20.6ms / totalSpan max 41.8ms 来自一次性投影 300 行预览，
    属长尾而非系统性阻塞（p95 全部远低于预算）；macOS 侧帧时间随任务 5.1 的真机验收一并补，本项不声称跨平台。
- [ ] 5.3 构建 Windows/macOS 安装包并嵌入匹配架构 Rust 运行时，在无 Python/仓库环境验证安装、启动与卸载路径。
- [x] 5.4 使用临时工作区执行创建→保存→模板→填写夹具→校验→导出→翻译→独立部署，验证产物和截图，不能用 mock 勾选此项
  - 协议层串测：`test/e2e_workbench_chain_kernel_test.dart` 10 例（真实 `ct worker`、临时工作区、零 mock），
    逐步断言产物与账本（保存只改 YAML、模板迁移保住既有 2 行、导出产出 JSON+Accessor、增量命中缓存、
    独立部署真的送 5 个文件进 Unity 目录、无 `.ct-stage-*`/`.tmp` 残留）。
  - **界面截图证据补齐**：`test/e2e_workbench_chain_screens_test.dart` 用同一批真实内核对象驱动整个工作台，
    10 步各出一张 PNG 到 `launcher/test/evidence/`（Schema 清单/草稿步骤面板/净差异对话框/模板预检/
    模板生成/校验/导出/独立部署/翻译/Quick Open），并同步写 `chain-text-log.md` 记录每步界面上**真实渲染的
    文本**与内核事实（草稿步数、候选 hash 与 +N/~N/-N、校验摘要、运行相位、部署同步数）。
    截图不做像素比对：导出/部署面板含真实耗时，逐像素断言会把「数字变了」误报成「界面坏了」。
    已人工查看 PNG 确认布局与弹窗可见（flutter_tester 无 CJK 字体，中文为方块，与 1.4 矩阵同一限制）。
  - 本项前置的桌面「校验」入口已补：`state/validate_runner.dart` + 导出页 `wb.validateRun`，
    结论与问题逐条取自内核 `validate`（只读、不写盘）；写任务进行中禁用并说明原因。
    测试：`test/state/validate_runner_test.dart`(5) + `test/state/validate_runner_kernel_test.dart`(4，真实 worker：
    好夹具通过、单表范围、坏 schema 必须不通过且摘要不得写「校验通过」) + `test/ui/workbench_validate_panel_test.dart`(3)。
  - 诚实边界：Excel 数据行由 openpyxl 夹具提供，「人手工往新列填数」不能从协议层完成——串测改为验证
    schema 迁移保住既有数据行并把新 i18n 列纳入 sync/翻译范围；真机鼠标与输入法操作仍留在 5.1/5.5。
  - 已自动化：`test/e2e_workbench_chain_kernel_test.dart` 10 例（真实 `ct worker`、临时工作区、零 mock）
    串完 创建 → 双守卫保存 → 模板预检/生成 → 校验 → 全量+增量导出 → sync/查询/单条保存 → 独立部署 →
    历史/任务/日志三张表。逐步断言产物与账本：保存阶段只有 `quest.yaml`/`item.yaml` 变化而 Excel、翻译、
    `output/` 零改动；模板迁移保住既有 2 行数据且新增 i18n 列进入 sync 范围；导出产出 `Quest_zh.json` 与
    `QuestAccessor.cs`；第二次导出报生成缓存命中；独立部署把 5 个文件真的送进 Unity 目标目录、再部署报
    未变更；收尾无 `.ct-stage-*`/`.tmp` 残留。另钉一条回归：模板生成不得增删 schema 目录成员。
  - 未勾选原因：本项还要求"填写夹具"的真实 Excel 人工填行与**真机截图**归档，需与 5.1/5.2/5.3 一并在
    release 构建上采集；不用 mock 或样板截图代替。。
- [ ] 5.5 完成窗口/缩放矩阵、异常退出、旧设置迁移和旧版本回滚演练，形成已知限制及发行说明。
- [ ] 5.6 核对内核 change 兼容与性能验收通过后切换正式桌面构建入口；更新使用文档并确认安装包不再包含/启动 Flask 或 Python。
  - 正式桌面构建入口已切净：`launcher/tool/build_windows.ps1` 删掉 PyInstaller 过渡开关（脚本自留的
    「迁到 ct worker 后删除此开关」条件已满足），只剩「定位 `xtask dist` 原生包 → flutter build → 嵌
    `runtime\ct.exe` + 版本/自检元数据」一条路，并保留「包内不得混入解释器文件」硬检查。整脚本实跑通过
    （内置 `ct 0.0.0`，`flutter build windows --release` 15.4s）。
  - 「安装包不含/不启动 Python 或 Flask」改为可复算检查：新增 `launcher/tool/check_payload.ps1`。
    2026-09-19 实测：负载 **27 个文件**、Python/Flask 痕迹 **0 处**、`runtime\ct.exe` 6,657,536 字节；
    在「PATH 只剩负载 runtime 目录 + 清空 `PYTHONHOME/PYTHONPATH/PYTHONSTARTUP/PYTHONEXECUTABLE/
    VIRTUAL_ENV/CONDA_PREFIX`」的隔离环境里真跑只读命令，`ct status --root gd` 与
    `ct validate --root gd` 均 **exit 0**，真实 `gd/` 全程 0 行改动。
  - CI 侧不再是口头承诺：`.github/workflows/native.yml` 桌面壳 job 追加
    `xtask dist` → `build_windows.ps1` → `check_payload.ps1` 三步（负载含 Python 即红）。
  - 使用文档同步：`ct/docs/agent-project-reference.md`「launcher 打包与分发」原写「用 PyInstaller 冻结
    ct CLI 嵌入应用包」——已失效，改写为原生运行时三步流程 + 本轮实测数字；`native/README.md`
    桌面壳一节补上 5.6 的构建与负载复核入口。
  - 未勾选原因：本项前半句是「核对内核 change 兼容与性能验收**通过后**」才切换收口；内核侧 6.5 仍缺
    macOS/Linux 真机与 L 档配对测量、6.7 未收口，故构建入口与文档先落地，勾选留到该前置成立。

- [x] 5.7 逐行完成 coverage.md 的界面映射并补充截图/测试证据，验证所有非默认配置目录的概览、预览和历史都由内核提供，无 StatsService 硬编码扫描。
  - 逐行核销表已补：`coverage.md` 第 6 节把基线 21 行逐行标成「已核销 / 内核侧 / 部分待真机」，
    每行给出**具体测试文件与例数**或**截图文件名**（17 张 golden、10 张全链 evidence、帧时间报告）。
  - 非默认配置目录验证：新增 `test/state/workbench_custom_dirs_kernel_test.dart` 4 例（真实 worker）——
    把 `schemas_dir/types_dir/excel_dir/i18n_dir/output_dir/cache_dir` 全改成非默认（含中文段名）后：
    清单 `sourcePath` = `meta/schemas/item.yaml`、分类计数由清单算出、模板落在 `表格/Item.xlsx`、
    预览列由内核回、JSON 产物落在 `产物/json/Item_zh.json`、`history.list`/`tasks.list`/`logs.list`
    都记到这次导出；并断言默认目录 `config/schemas`、`excel/`、`output/` **根本不存在**——
    任何硬编码扫描都会给出 0/空，而界面显示的是内核路径。
  - StatsService 硬编码扫描已删除（`lib/services/stats_service.dart`：它扫 `config/schemas`、`i18n/`、
    `output/json`，且已无任何引用），并加机器守护 `test/services/no_workspace_scan_test.dart`(2)：
    `lib/` 里再出现工作区目录字面量或 `StatsService` 即红。
  - 预览分页顺带补成真的（见 5.2 注记）：`table.preview` 的游标续页在界面上可达，
    矩阵行 `table.preview` 的测试数从 4 升到 8。
  - 剩余真机缺口在第 6 节末段列明：macOS/Linux（1.3/6.5/6.6、5.3 mac 包）、双进程与自启（2.5/5.5）、
    输入法与焦点人工验收（5.1）。
