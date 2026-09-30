## 1. 实施基线与确定性复现

- [x] 1.1 在 `feat/native-workbench-cutover`（规划基线 `5b70971`）隔离 worktree 携带本方案，记录 HEAD、macOS/Flutter/Rust 版本及现有主工作区差异摘要；验收为规划文件在实施分支齐全，真实 `gd/` 未变且测试使用临时存储根。
- [x] 1.2 为现有草稿测试加入可控 I/O 屏障与失败注入，确定性重现连续 save、save→clear、写入中 load、等待时新增任务和 dispose 后完成；验收为旧实现至少在顺序/等待/生命周期断言上明确失败，不靠重跑概率、sleep 或取消断言。

## 2. 草稿存储与状态顺序

- [x] 2.1 按实际存储根与草稿目标文件建立同进程共享 FIFO，统一 `save/clear/load/preserve`，保留 `.tmp` 原子发布与遗留恢复布局；验收为同文件跨 store 实例顺序一致、异步存储根解析乱序也不改变调用登记次序、不同文件可并行，load 不删除活动临时件，save→clear 后正式文件不存在。
- [x] 2.2 让每项失败反馈给调用者但不阻断后续队列，安全释放空闲队列；验收为 write/rename/clear 失败后重试仍执行并成功，目录/权限/损坏/残留临时件原有测试通过。
- [x] 2.3 将自动落盘、显式重试及清理统一到 repository 调度接口，入队捕获不可变 workspaceKey/baseline/commands/cursor；验收为快速编辑和 undo/redo 的最终信封精确等于最新快照，旧 save 不能复活已放弃或保存后清理的草稿。
- [x] 2.4 重定义 `persistSettled`/flush 为全部已请求操作排空，新增任务时继续等待最新队尾，并区分待落盘与失败；验收为等待尚未完成时最新请求显示待落盘，旧成功不能覆盖新状态，最新失败保留命令且成功重试清除正确警告。
- [x] 2.5 加入 repository 存活与工作区/编辑序号保护，覆盖 save/clear/load/restore/preserve/discard 完成通知并将其移出 I/O catch；验收为延迟完成后 dispose 无 notifier/未处理异步异常，旧 load 不覆盖 B 或同工作区新编辑，clear 失败保留冲突/损坏提示与文件身份，文件仍写正确归属。

## 3. 退出与恢复可靠性

- [x] 3.1 将窗口/设置/托盘及 Cmd+Q/Dock 退出共用单次决策和无条件 flush，确认到关闭期间冻结编辑及切工作区，取消/失败后释放冻结并允许重试；验收为并发退出只决策一次，active=0 的 redo/clear 仍排空，mock window/worker 的关闭在落盘成功之后，失败不能误报已保留，明确放弃有序 clear，托盘隐藏及 worker 发布收尾回归仍通过。
- [x] 3.2 在切换前冻结并 flush 出站 A，失败留在 A 或明确放弃，成功后同步偏好与 B 视图；用临时目录验证快速 create/rename/undo→重启、A/B 切换及失败重试，验收为 A 的未落盘内存不丢失、完整 commands/cursor/redo/基线/归属一致，未知格式与冲突仍保留原文件。
- [x] 3.3 在 macOS 临时工作区执行编辑后立即保留退出再启动，记录恢复命令/cursor/资源和无残留 worker 的结果；验收为实际退出前草稿已落盘并可恢复，全过程真实 `gd/` 未变。

## 4. Quick Open 全链修复

- [x] 4.1 将全链夹具显式设置 `showDesktopTitleBar: true` 并把旧 `wb.draftQuickOpen` finder 改为标题栏 `ct.titleBar.quickOpen`，补充入口、调色板、最近项与选中结果断言；验收为真实 worker 上从翻译页打开并选中资源进入 Schema，草稿/cursor 保持，截图步骤与收尾业务断言全部到达。
- [x] 4.2 保留并复验 Cmd/Ctrl+P、资源 pane 关闭时搜索、Esc 和焦点恢复；验收为现有导航/标题栏/草稿条测试通过，不新增旧按钮、不跳过全链测试或放宽等待判定。

## 5. 禁用按钮与定向视觉基线

- [x] 5.1 为 `CtButton.accent/ghost` 添加 enabled/disabled 回调、语义和状态颜色检查；验收为禁用按钮无法触发回调且采用既有灰色 token，启用按钮与正常交互保持，不修改布局/字体。
- [x] 5.2 固定 macOS/Flutter 环境，仅更新 empty/loadError/busy/conflict/component gallery 5 张 `_macos` golden，逐图记录 actual/master/diff 审阅；验收为变化局限于预期禁用按钮区域，其余 12 项 golden 文件摘要不变，Windows 基线与比较容差不变。
- [x] 5.3 不带 `--update-goldens` 执行完整 `workbench_golden_test.dart`；验收为 17 项全部通过且无溢出异常，CI 未增加期望值生成步骤。

## 6. 整体回归与交付

- [x] 6.1 构建真实内核并设置绝对路径 `CT_WORKER_BIN`，运行草稿存储/故障、repository draft、exit guard、导航和完整全链测试；验收为全部通过，竞态测试用可控调度覆盖设计矩阵，原偶发恢复测试定向重复 10 次无残留任务或异常。
- [x] 6.2 在 launcher 运行 `flutter test --reporter expanded`、`flutter analyze` 与 `dart format --output=none --set-exit-if-changed lib test integration_test test_driver`；验收为完整套件无跳过原失败用例、全部通过，静态分析与格式无问题，保存环境/测试计数及退出重启证据。
- [x] 6.3 在仓库根运行 `cargo test --manifest-path native/Cargo.toml --workspace --locked`、`node native/tools/check-retirement.mjs --after-deletion`、`node native/tools/check-docs.mjs`；验收为原生回归和退役/文档检查通过，Schema/Excel/i18n/输出冻结参考未被本次修复修改。
- [x] 6.4 在全部源码、测试与证据完成后执行 `xtask fingerprint --root <实施工作区>` 并 `fingerprint --check`，核对 diff 与真实 `gd/` 摘要，按实际验收勾选任务；验收为指纹一致且仅方案范围文件改变，最终报告三个问题各自的修复与验证，不用规格归档代替测试通过。
