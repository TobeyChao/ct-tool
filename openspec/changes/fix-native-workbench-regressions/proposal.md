## Why

`feat/native-workbench-cutover` 在 rebase 后的 `5b70971` 上出现 7 项 Flutter 回归失败：1 项 Quick Open 测试入口过时、1 项草稿并发持久化/销毁竞态、5 项禁用按钮截图基线过时。相关实现与 rebase 前 `2d7dfc9` 一致；其中草稿问题可能影响用户编辑的落盘顺序与退出可靠性，优先修复，并恢复完整回归的可信度。

## What Changes

- 将同一草稿文件的持久化操作排队，捕获不可变的工作区、基线、命令历史和 cursor；保存、清理和读取不得争用临时文件或发生旧写覆盖新写。
- 统一自动落盘、手动重试、放弃/保存后的清理与等待接口；在最新草稿尚未完成落盘时如实显示状态，工作区切换和对象销毁后不得发布旧状态或访问已销毁 notifier。
- 退出保留草稿时等待最新落盘结果；失败保留内存和错误提示，用户可重试、留下或明确放弃，保持现有 worker 发布收尾语义。
- 将真实 worker 全链测试的 Quick Open 操作更新为现有标题栏入口，补充结果断言，并保留 Cmd/Ctrl+P 的独立行为覆盖。
- 确认当前禁用按钮的灰色样式与不可点击语义，再定向更新 macOS 的 empty/loadError/busy/conflict 与 component gallery 共 5 张 golden；保留其余截图及严格比较标准。
- 补充可控异步顺序、故障及生命周期回归；全套 Flutter、静态分析与格式通过后更新源码指纹。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

无规格级行为变更。此变更落实 native 分支已有 `native-flutter-workbench` 的 `native-desktop-workbench` 契约：`Draft persistence and response ordering safety`、`Guarded native Schema draft`、`Full Schema navigation and Enum editing` 和统一退出保护；不把主规格的浏览器 IndexedDB 约束改成桌面文件存储。

`.openspec.yaml` 使用 `skip_specs: true`：本次是既有实现缺陷与测试基线修复，不创建重复的 native 能力或人为新增规格。设计中的验收矩阵明确每项行为的检查方式。

## Impact

实施目标为 `feat/native-workbench-cutover`，从已推送的 `5b70971` 起继续；主工作区仍在 `main`，本提案目前只新增规划文件，后续实施需将完整规划带入 native 分支。

主要影响 `launcher/lib/state/workbench_repository.dart`、`launcher/lib/state/draft_store.dart`、统一退出流程及其测试、全链截图测试与 5 张 macOS golden。无需修改 Rust 内核业务、worker 协议、草稿格式版本、文件名规则、Schema 保存双守卫或 YAML-only 边界；无需新增运行依赖。草稿存储仍限于应用目录，测试只用临时夹具，真实 `gd/` 不参与写入验证。

Windows 发行验收延后，Linux 不支持；本次 macOS 图像基线验收不代表跨平台验收完成。不会借此同步/归档未完成的 native 主变更。
