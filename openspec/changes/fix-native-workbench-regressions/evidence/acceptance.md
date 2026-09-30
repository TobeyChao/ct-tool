# 修复实施与验收

## 实施基线

- 分支：`fix/native-workbench-regressions`，基于 `feat/native-workbench-cutover` 最新已推送提交 `d8ac427afce075a8a4e4a3842e97379d35d5adb3`（原规划基线为 `5b70971`）。native 分支被另一个 CI 工作区占用，本次采用独立修复分支，保护其未提交协议测试。
- 验收前已将修复分支 fast-forward 对齐并行 CI 最新提交 `e64c121fb2622e2c1d4619abd7f6249c225634d2`，保留其取消检查、源码指纹诊断排除、Flutter 3.47.0 CI 固定版本和新增草稿测试。重复的 5 张 golden 已与本次定向更新逐字节一致，采用上游图像；本次完成存储/恢复/退出/切换的完整修复。新增上游延迟测试改在文件访问边界注入屏障，以验证文件队列的串行而非限定 repository 内部实现。
- 工作区：`/tmp/ct-tool-native-fix-20260930`。
- macOS 27.0，build 26A428；Apple Silicon。
- Flutter 3.47.0 stable，framework 4cf2416426；Dart 3.13.0，engine 5f77625673。
- Rust 1.98.1（48a229cea 2026-09-01）。
- Flutter 依赖通过 `flutter pub get --offline` 准备；真实 worker 由当前工作区 `cargo build --manifest-path native/Cargo.toml -p ct-cli --locked` 构建。
- 主工作区仍在 main，原有四个 gd 产物修改摘要保存在 `/tmp/ct-tool-native-fix-main-before.patch`，完成后逐字节核验；所有业务测试只用临时夹具和应用存储根。

## 确定性修复前证据

- 存储层先只加入文件访问适配器并保留旧顺序，6 项可控屏障测试全部失败：跨实例 `.tmp` 争用、save→clear/preserve 抢跑、load 删除活动临时件、目录解析乱序、调用后变更载荷。日志保存为 `logs/storage-red.txt`。
- 仓库层 5 项可控 Future 测试全部失败：最新快照错误报已落盘、仅等最后任务、等待期间新增任务遗漏、旧 restore 覆盖 Fresh 为 Old、clear 失败先清掉冲突提示。日志保存为 `logs/repository-red.txt`。
- 修复后存储测试 32/32 通过，含新增 17 项；文件队列按真实路径共享，同文件同步登记，不同文件 I/O 可并行。仓库继续以存活、工作区代次与快照序号守卫界面，等待接口排空全部新增任务。

## 最终验证

- 最终最新 native 基线上的 Flutter 完整套件 **454/454 通过**，没有跳过原 7 项失败；`flutter analyze --no-pub` 无问题；113 个 Dart 文件格式检查无变化。日志为 `logs/flutter-full.txt`、`logs/flutter-analyze.txt`。
- 原同基线恢复用例定向重复 **10/10 通过**；可控屏障覆盖存储顺序、首次目录解析、故障重试、redo、旧恢复、切换失败、清理失败、dispose 与同步监听器重入。日志为 `logs/restart-repeat-1.txt` 至 `logs/restart-repeat-10.txt`、`logs/reentry.txt`。
- 统一退出/壳层包括偏好写入抛错、连接失败及等待阶段解绑旧运行器；回归明确旧 A 业务服务不能在 B 视图继续使用。偏好失败继续绑定 B 并可见报告未保存，连接失败不复活 A；整个 transition 屏蔽指针、焦点和写入口。
- macOS 真窗口两阶段 `flutter drive` 通过：write 应用 PID 18505、restore 新应用 PID 18940；两个应用进程均已退出，两个 worker exitCode 都为 0。连续 create/rename/undo 后立即保留退出，新进程恢复相同 2 条 commands、cursor=1、redo=true、RestartHero 资源。报告为 `macos-write.json`、`macos-restore.json`；实际日志为 `logs/macos-write.txt`、`logs/macos-restore.txt`。
- Quick Open 真实 worker 全链和导航/UI 20/20 通过；macOS golden 17/17 通过。五张按钮更新精确区域与其他 29 张基线摘要保护见 [visual.md](visual.md)。上游已提交相同五张图，本次未重复改写其图像。
- Rust 完整 `cargo test --manifest-path native/Cargo.toml --workspace --locked` **335 项通过**；无新增原生业务实现改动。最初 d8ac427 指纹元数据检查失败在采用最新上游及本次最终源码指纹重新计算后通过；日志为 `logs/cargo-workspace.txt`。
- Python 退役检查、有效文档检查、工作区 gd 守卫和 OpenSpec strict 校验通过。主工作区四个未提交 gd 文件与实施前差异补丁逐字节相同；并发 CI 工作区的修改均保留。
- 最后全部验收记录/任务勾选完成后重新生成并检查源码指纹。历史参考/oracle、草稿格式 v1、Schema 保存双守卫、真实 gd 业务产物未修改。工作只实施在独立修复 worktree，无自动 commit/push/归档。
