## Context

动机与范围见 [proposal.md](proposal.md)。目标代码为 native 分支 `5b70971`，检查使用该提交的独立只读 worktree，规划文件目前位于主工作区。

### 已确认的失败与证据

| 问题 | 观察与根因 | 处理级别 |
|---|---|---|
| 草稿恢复偶发失败 | `WorkbenchRepository._schedulePersist()` 每次覆盖 `_pendingPersist`；`persistSettled` 只等待最后一个 Future。`createTable` 与 `renameResource` 连续执行后较早写入仍可能在 `dispose()` 后完成，在 `notifyListeners()` 抛错；原异常又被 catch 后再次通知。`DraftStore.save()` 两次使用同一正式文件对应的 `.tmp`，存在 write/rename 争用。 | P1：编辑数据可靠性 |
| Quick Open 全链失败 | `e2e_workbench_chain_screens_test.dart:307` 仍查找 `wb.draftQuickOpen`；真实入口为标题栏 `ct.titleBar.quickOpen`。现有草稿条测试明确断言旧入口不存在。 | P2：测试与真实入口同步 |
| 5 张 macOS golden 失败 | empty/loadError/busy/conflict 各相差 1872 像素（0.18%），component gallery 相差 3495 像素（0.18%）。实际图像中禁用按钮为灰色，旧图像为绿色；`CtButton` 已显式处理 `WidgetState.disabled`。 | P2：视觉基线同步 |

前两项已在隔离副本复现：全链测试稳定失败；草稿恢复定向重复前两轮通过、第 3 轮复现销毁后通知。golden 定向 17 项中 12 通过、5 失败。上述相关代码在 `2d7dfc9` 与 `5b70971` 的 Git blob 一致，问题不由 rebase 引入。

原分支已要求原子草稿持久化、失败保留内存/警告、按工作区与基线恢复、全局 Quick Open 和统一退出保护。`native-desktop-workbench` 尚在 native 主变更的 delta 中；此修复不重复建立能力，不改变浏览器 IndexedDB 规格，因此声明 `skip_specs: true`。

## Goals / Non-Goals

**Goals:**

- 同一草稿在快速编辑、撤销/重做、清理、失败重试、工作区切换、正常退出与销毁时，文件顺序和界面状态可信。
- 用可控异步屏障固定复现竞态，保证最新 commands/cursor 落盘并可恢复，不能仅用多次重跑代替确定性检查。
- 全链验证真正经过可见 Quick Open 入口；更新已经确认过时的 5 张 macOS 基线，完整 Flutter 回归恢复全绿。

**Non-Goals:**

- 不改变草稿格式 v1、工作区命名/路径匹配规则、Schema/Excel/翻译/导出业务、候选双守卫或 YAML-only 保存边界。
- 不增加 debounce、自动重放写请求、全局刷新 golden、像素容差或新运行依赖。
- 不实现跨进程编辑协同、Windows 发行验收或 Linux 支持，不同步/归档 native 原变更来代替实现验收。

## Decisions

### 1. 以同一草稿目标文件的 FIFO 队列确定文件操作顺序

将 `DraftStore` 的同文件 `save/clear/load/preserve` 操作放入同一队列。身份由实际应用存储目录和现有 `fileName(workspaceKey)` 组成，不能只按 workspaceKey：不同临时存储根之间必须隔离。队列在同一进程内对同文件的多个 store 实例共享；不同文件可并行。

队列顺序按公开方法的调用顺序登记；若应用存储根首次解析需要异步等待，使用共享的根目录初始化与预登记任务次序，不能先各自 await `fileFor/directory` 再决定入队顺序。用根目录解析乱序的测试验证此边界。

一次 save 的写入、flush、rename 是完整队列任务；clear 不得抢在先前 save 之前，load 不得把正在写入的 `.tmp` 当成中断残留删除，preserve 不得改名在途发布的正式文件。保留现有 `.tmp` 文件布局与中断恢复规则，单 writer 保证其不再争用。失败返回调用者，内部队尾消化失败以允许下一项重试；空闲队列项用身份比较安全释放，不保留无界历史。

独立随机临时文件只能消除临时件冲突，仍会让旧 save 最后 rename 覆盖最新草稿，因此不能单独解决问题。只给 repository 的自动写入排队又会遗漏手动重试、直接 clear 和读取，所以文件边界必须统一。

### 2. 草稿任务在入队时捕获完整快照，等待接口覆盖所有入口

自动落盘与显式 `persistDraft()` 统一调度入口；入队时深复制序列化命令载荷，记录 workspaceKey、原始基线、完整命令及 cursor，并捕获工作区代次与草稿编辑序号。队列真正开始时不得读取已经改变的 `_root`、基线或命令列表。

新快照入队即把最新草稿标为待落盘，区分等待与真实失败；较早保存成功不得在最新快照仍等待时把界面恢复为“已落盘”。仅当前工作区、当前编辑序号且 repository 存活的完成结果更新 `_draftSavedAt`、错误和持久化状态。

`persistSettled`/显式 flush 等待该 repository 所有此前请求的 save/clear/retry，并在等待期间又有任务入队时继续等到稳定队尾。它只用于排空队列，调用方仍检查最新持久化结果；不能把“Future 完成”解释为写入成功。保存成功、放弃全部与 `discardStoredDraft()` 的清理同样进入队列，最后一个 clear 必须压过之前所有 save，不能在重启后让旧草稿复活。

本次先采用完整 FIFO，不合并中间编辑；规则容易验证，后续只有测得实际 I/O 压力才单独设计合并优化。

### 3. 以生命周期和代次保护通知，退出显式排空最新草稿

为 repository 增加存活标记，`dispose()` 后拒绝新持久化请求，已捕获的队列任务可完成文件写入但不得通知或改变销毁后的 UI。所有持久化成功/失败通知均在 try/catch 外按存活、workspace、编辑序号验证，防止把 notifier 生命周期异常误判成磁盘写失败。

工作区 A 的旧任务仍写 A 的捕获路径；切换 B 重置 B 的持久化视图，A 的成功或失败不得更新 B。重新加载同一目标时受存储队列保护，restore 不能读到中间快照或误删活动临时件。

完成守卫也覆盖 `restoreDraft/load/preserve/discard`：当前 `restoreDraft()` 在 await load 后直接恢复 `_log` 并通知，没有代次或存活检查。入队捕获工作区代次与编辑序号，返回后重新验证；A 的延迟 load、同工作区已开始新编辑后的旧 restore，以及 dispose 后的 load 都不得覆盖日志或通知。FIFO 只保证文件操作顺序，不能代替异步 UI 完成守卫。

切换工作区前先冻结出站草稿编辑并排空当前工作区请求，检查最新结果后才重置 `_root/_log`。若 A 未落盘，留在 A 供重试/留下/明确放弃；不得先清空 A 的内存再忽略其写入失败。不采用额外的按工作区内存草稿缓存。切换协调完成或取消时释放冻结，Shell 与偏好工作区一致，不先把设置改成 B 但仍显示 A。

在应用所有真实退出入口共用的流程中加入单次决策与 flush Future：窗口关闭、设置/托盘退出及 `AppLifecycleListener` 的 Cmd+Q/Dock 路径共用协调器。确认和 flush 到关闭期间冻结草稿编辑与工作区切换，保证不存在最后一次检查后新增请求。flush 无条件执行，包括 active command 为零但仍含 redo 历史、待清理文件等情况；不能以 `draftCount > 0` 省略。取消或失败后清掉本轮 Future 并解除冻结，让用户可以再次退出。

决定保留草稿时排空最新请求并重新检查结果，再关闭 worker 与窗口。持久化失败时保留内存和可见错误，不宣称下次能恢复；提供重试、留下或明确放弃。明确放弃也需要排空/清理完成，清理失败返回界面，并保留冲突/损坏提示、文件身份及内存；仅清理成功且仍属于当前工作区时才清提示。托盘隐藏仍保留进程，不必等待退出 flush；已有等待 worker 发布收尾的机制保持。

只加 `if (!disposed)` 能隐藏测试异常，但无法解决旧写覆盖、退出前丢失与错误“已落盘”状态；延长测试等待也不能保证顺序，因此不能作为修复方案。

### 4. Quick Open 全链测试走现有标题栏，不恢复旧按钮

全链测试的 `WorkbenchScreen` 当前未设置 `showDesktopTitleBar`，默认 false；先让此夹具显式启用与真实桌面应用一致的标题栏，再将过时 finder 更新为 `ct.titleBar.quickOpen`，在跨模块操作前后明确断言入口可见、调色板存在、空查询显示最近资源。补充从结果选择资源后进入 Schema、目标选中且原草稿/cursor 不变；现有 Cmd/Ctrl+P 测试继续独立覆盖键盘入口。

保持有界的按状态等待，等待结束必须断言目标状态，不能增加任意 sleep、跳过测试或改成只有截图。此问题不需要修改产品入口、增加重复按钮或调整现有布局。

### 5. 定向同步 5 张过时的 macOS golden，保留交互断言

先对 `CtButton.accent/ghost` 验证 enabled/disabled 的回调、颜色解析和禁用语义；确认禁用按钮无法点击，不被 SDK 默认状态覆盖。已查看的 actual/master 仅显示预期禁用态差异，当前产品样式保留。

固定当前 macOS 与 Flutter 工具链，在目标测试名过滤下生成 empty/loadError/busy/conflict/component gallery 5 张 `_macos` 图像。审阅实际/期望/差异图，确认变化只在预期按钮区域；审阅通过后再纳入 Git。禁止一次更新所有矩阵、变更 Windows 基线或放宽像素比较。

随后不带 `--update-goldens` 跑完整 golden 测试，17 项均应通过；其余 12 项及其文件摘要应保持一致。CI 只验证 golden，不生成期望值。flutter_tester 的 CJK 占位字体限制保留，本次不把真实中文字体/字号切换混入基线更新。

### 6. 验收以确定性竞态测试和真实 worker 全链组成

| 场景 | 控制方式 | 必须满足 |
|---|---|---|
| 连续 save A、save B | 用 Completer 阻塞第一项文件操作，先排入第二项 | 第二项不开始；释放后最终文件等于 B，完整 commands 与 cursor 精确恢复 |
| 编辑后 undo/redo | 捕获每次快照，阻塞前一项 | cursor 与 redo 后缀一并恢复，不能仅按 active commands 重建 |
| save 后 clear | 第一项阻塞后放弃或 YAML 保存成功清理 | clear 最后执行；所有任务排空后文件不存在，旧 save 不能复活 |
| 写入过程中 load | 在 write/rename 阶段挂起 | load 等待，不能删除活动 `.tmp`；无在途写入时仍清理历史残留 |
| 失败后重试 | 第一项注入 write/rename 失败，下一项成功 | 队列不被永久拒绝；内存保留，最新成功清除对应失败警告 |
| 等待期间新增任务 | 取得 persistSettled 后继续编辑 | 等待覆盖新队尾，完成时无残留后台任务 |
| 销毁中完成 | 任务阻塞后 dispose 再释放 | 已捕获任务可收尾，无 notifier 异常或未处理 Future 错误 |
| A 切到 B | 阻塞 A 写入并请求切 B，分别注入成功与失败 | 切换等待最新 A，失败仍保留 A 内存/错误，成功后 A/B 归属正确 |
| 延迟恢复读取 | A 的 load 返回、同工作区新编辑或 dispose 之间受控调度 | 旧 restore 不覆盖当前命令、归属或通知 |
| 立即保留并退出 | 从窗口/Cmd+Q/托盘同时请求退出，最后一次编辑或 redo/clear 尚未 flush | 单次决策，冻结编辑/切换，无条件排空；失败可留下/重试并释放冻结 |
| 清理冲突草稿失败 | 阻塞 clear 后注入失败再重试 | 保留原提示与文件身份，仅重试成功后清除 |
| Quick Open 跨模块 | 标题栏入口及键盘入口分别走真实资源 | 最近项、选中资源、模块切换和草稿保持均有断言 |
| golden 同步 | 检查变化区域和摘要，再不更新运行 | 仅 5 张预期变化，全部 17 项与完整 Flutter 套件通过 |

复用现有 `draft_store_faults_test`、repository draft、exit guard、导航及全链测试夹具；测试接缝只用于阻塞 I/O 与注入失败，避免生产分支加入 test-only 业务逻辑。平台通道无法在普通测试启动真实窗口时，拆分可测的退出协调器，并用 mock window/worker 验证关闭顺序，最后用 macOS 临时工作区做一次编辑后立即退出再重启验证。

## Risks / Trade-offs

- [同步通知监听器可重入编辑或 flush] → 持久化任务先向存储入队并登记等待集合，再发布待落盘通知；确定性覆盖 save→重入 save、clear→重入 save 与监听器请求 flush，最新快照仍最后落盘。
- [FIFO 增加快速编辑时的等待] → 草稿快照小，任务异步执行，UI 不等待每次写入；集中记录耗时，当前不引入 debounce。
- [文件队列与通知队列语义混淆] → 文件层确保顺序，repository 用编辑序号筛选 UI，显式测试中间成功与最新待落盘并存。
- [失败吞掉导致假成功] → 每项操作原始 Future 保留失败，只修复内部链继续执行；flush 后检查结果，明确测试错误提示与重试。
- [dispose 不能异步等待] → 排空由正常退出入口负责，dispose 只阻止后续通知；已捕获任务不取消，测试 teardown 必须等待排空。
- [截图更新掩盖真实 UI 回退] → 保留禁用行为测试、限定 5 张、逐图审阅；其余矩阵不更新，严格比较不变。
- [同应用多 store 实例撞同一文件] → 同进程按真实存储目标共享队列；跨进程由现有单实例机制管理，本次不设计跨进程草稿锁。

## Migration Plan

1. 在 native 分支的隔离 worktree 携带本提案实施；主工作区的未提交 `gd/` 产物不参与。
2. 先加入可控调度失败测试，再修存储/repository/退出语义；然后修 Quick Open 测试，最后更新 5 张 golden。
3. 运行聚焦测试、macOS 全链与完整 Flutter 套件，记录环境和结果；执行 analyze/format、Rust workspace locked 回归、退役/文档检查。最后生成并复验源码指纹。
4. 草稿 format v1 与现有文件名保持，已有草稿可直接读取，无自动数据迁移；未知格式和基线冲突继续保留。
5. 回滚采用 revert 修复提交，包含代码、对应测试与基线及重新计算的指纹；不删除用户草稿，不批量刷新 oracle 或历史证据。是否提交/push 按后续用户授权执行。
