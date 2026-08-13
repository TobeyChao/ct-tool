## Why

launcher 目前必须依赖外部安装的 ct 工具（`Config/ct/.venv`）才能启动 `ct panel`，导致游戏仓库被迫携带工具源码、用户需要克隆 ct-tool 仓库并配置 Python 环境才能使用；工具代码两份存在已经引发多次同步漂移。目标：launcher 自带 ct 运行时（PyInstaller 冻结的 `ct panel` 二进制），游戏仓库只保留数据工作区 + 编译好的应用，用户无需拉取 ct-tool 或安装 Python。

## What Changes

- 新增 ct CLI 的 PyInstaller 打包入口：将 `ct panel` 命令（含 `ct.web` 静态资源）冻结为独立可执行文件（onedir 布局），输出 `ct-panel` / `ct-panel.exe`
- launcher 启动逻辑改为「内置运行时优先，外部工具目录回退」：macOS 从 `.app/Contents/Resources` 定位，Windows 从可执行文件同级目录定位；内置缺失时才回退到设置中的 toolDir
- 新增 macOS / Windows 构建脚本：构建 launcher 时将冻结产物嵌入应用包并做 ad-hoc 签名；Windows 脚本在 Windows 机器上执行
- 更新 AGENTS.md 与构建/分发文档：产物如何生成、放到哪里、fabulous-game 如何消费
- 交付任务：fabulous-game 仓库移除 `Config/ct` 与 `Config/launcher` 源码，改为只保留 `Config/gd` 数据工作区与编译好的 launcher 应用（删除动作在 fabulous-game 仓库执行）

## Capabilities

### New Capabilities
- `launcher`: launcher 自带 ct panel 运行时——内置运行时的发现/定位、启动顺序（内置优先 + 外部回退）、平台路径布局（macOS Resources / Windows 同级目录）、缺失时的用户提示

### Modified Capabilities

（无——`web-panel`、`cli-interface` 等既有 capability 的行为不变，本次只改 launcher 侧如何获得 ct 运行时）

## Impact

- `ct/`：新增打包配置（PyInstaller spec + 入口脚本），工具本身行为不变；`ct.web` 静态资源需随包收集
- `launcher/`：`lib/services/panel_service.dart`（启动命令解析）、`lib/services/settings_store.dart`（内置模式说明）、`macos`/`windows` 构建脚本
- 依赖：新增 PyInstaller（仅构建期，不入运行时依赖）；onedir 产物随应用分发
- 文档：根 `AGENTS.md`、launcher docs
- 分发：fabulous-game 的 `Config/ct`、`Config/launcher` 可移除（git 历史可恢复）；应用需在 macOS / Windows 分别构建
