## Why

当前 Flutter launcher 只负责启动本地 Flask 面板，编辑体验仍依赖浏览器。需要把它演进为美观、可独立安装的原生桌面工作台，并与 Rust 内核共用业务能力，保留成熟的 Schema、翻译与导出工作流。

## What Changes

- 在现有 `launcher/` 中实现完整 Flutter 工作台：资源导航、Schema 编辑与属性面板、翻译、模板、导出、日志历史、设置。
- 沿用深林绿设计令牌，先交付带模拟数据的交互样板，再接真实 Rust 服务；样板不视为功能完成。
- 接入 `rust-native-core` 定义的版本化 stdio worker 协议，界面不复制校验、候选计算或文件发布逻辑。
- 保持 Draft → 内核候选/净差异 → YAML-only 保存及 revision/hash 守卫；模板、导出和部署保持显式独立。
- **BREAKING**：正式桌面入口从启动 `ct panel`、打开浏览器改为 Flutter 工作台；桌面安装包改为随附 Rust 运行时，不再提供 Python 工具目录和 host/port 配置。
- Windows/macOS 为首发桌面验收平台；Linux CLI 由内核 change 验收，Linux GUI 不计入首发完成标准，保留可移植结构。

## Capabilities

### New Capabilities

- `native-desktop-workbench`: 原生桌面布局、完整业务入口、草稿、视觉质量、交互与任务生命周期。

### Modified Capabilities

- `launcher`: 内置 Rust worker、应用启动行为与平台打包替代原 Flask launcher 契约。

## Impact

影响 `launcher/lib/`、桌面平台工程、构建脚本和安装说明；消费 Rust change 的协议与可执行文件。本 change 拥有 Flutter 客户端与桌面安装包，Rust change 拥有全部业务用例与协议服务。

现有 Web/Python 源码在迁移期用于对照，不随新客户端分发；全仓删除旧实现不是本提案的完成前提。旧 `web-panel`、浏览器布局规格仅约束旧界面；原生界面的业务规则以现行 Schema workspace-draft/type-system/query-indexes、数据与发布规格为准，禁止恢复旧的保存即改 Excel 行为。

不包括移动端、云同步、Excel 单元格编辑器或 FFI 优化。界面可先基于协议夹具独立推进；完整集成依赖 Rust worker，两个 change 都通过后才替换正式桌面发行。
