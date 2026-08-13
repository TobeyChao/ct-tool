## Context

launcher（Flutter，macOS/Windows）当前通过 `SettingsStore` 定位 toolDir 下的 venv 入口（`bin/ct` 或 `python -m ct.cli`），用 `Process.start` 拉起 `ct panel`（Flask，127.0.0.1:port），随后通过 HTTP 与日志流交互。ct 是 src-layout Python 包，`ct panel` 子命令承载面板服务，`ct.web` 静态资源约 212K 需随包携带。动机见 proposal.md；本设计只解决"内置运行时如何打包、如何被发现、如何回退"。

## Goals / Non-Goals

**Goals:**
- launcher 应用包内随附可独立运行的 ct 运行时（onedir 布局），用户无需安装 Python 或拉取 ct-tool
- 启动时内置优先、外部工具目录回退；两种模式的启动参数、日志、退出处理行为等价
- 内置运行时按平台约定布局，无需用户配置即可发现
- macOS / Windows 各有一条可重复执行的构建链路

**Non-Goals:**
- 代码签名与公证（内部工具，先 ad-hoc 签名；正式分发时再补）
- 自动更新机制、Linux 支持
- 将 gd 数据或 Python 源码打进应用（数据仍在游戏仓库，源码仍在 ct-tool）
- 改变 `ct panel` 自身行为

## Decisions

### 1. PyInstaller onedir 冻结完整 CLI，而非只冻结 panel

冻结 `ct.cli:app`（Typer 应用）为独立可执行文件，输出名保持 `ct` / `ct.exe`，launcher 以 `ct panel --root ... --host ... --port ... --no-browser` 调用——与外部模式命令形态完全一致（满足 spec「启动行为等价」）。冻结完整 CLI 的额外收益：分发包内自带 `ct export/validate` 等命令，便于用户在无 Python 环境时脚本化使用。

- 备选 A：onefile 单文件——每次启动解压到临时目录、启动慢、杀软误报更普遍，子进程生命周期管理有已知坑（Tauri/PyInstaller 社区反复提及）。否决。
- 备选 B：只冻结 panel 子命令——缩小体积但丢失 CLI 其他能力，且需额外入口脚本维护。不采用。
- 备选 C：嵌入 python-build-standalone 便携运行时——体积更大（数百 MB 量级）、绝对路径问题多，对本场景过重。否决。
- 备选 D：Nuitka——误报低于 PyInstaller，但打包复杂度和维护成本更高，先不引入。

### 2. 内置运行时的平台布局与发现

- macOS：onedir 产物置于 `.app/Contents/Resources/runtime/`（含 `ct` 可执行与 `_internal`），运行时从 `Platform.resolvedExecutable` 向上定位 `Contents/Resources/runtime/ct`
- Windows：onedir 产物置于 launcher exe 同级 `runtime\ct.exe`，从 `File(Platform.resolvedExecutable).parent` 定位

发现规则：目标路径存在且为文件即视为可用（spec：无需配置即可发现）。启动抛异常时不自动回退（避免掩盖真实故障），直接展示错误；仅在"不存在"时走外部回退。

### 3. 回退与缺失提示

内置缺失 → 沿用现有 toolDir 逻辑（venv `bin/ct` 优先，其次 `python -m ct.cli`）；两者皆缺 → 错误信息同时说明「应用包内缺少内置运行时」与「工具目录配置指引」（spec：全部缺失时报告错误）。

### 4. 构建链路（双平台同构）

- `ct/packaging/ct.spec`：PyInstaller onedir，入口 `ct.cli:app`，`collect_data_files("ct.web")` 收集静态资源，排除 flatc 相关可选依赖（`ct panel` 不调用）
- macOS `launcher/tool/build_macos.sh`：在 ct venv 装 PyInstaller → 构建 onedir → `flutter build macos --release` → 拷贝 `runtime/` 进 `.app/Contents/Resources/` → `codesign --force --deep -s -` → 输出可分发 `.app`
- Windows `launcher/tool/build_windows.ps1`：同构流程，产物与 `ct_launcher.exe` 同级放 `runtime/`，在 Windows 机器上执行

### 5. 分发后的工作区配置

内置模式下 launcher 不再需要 toolDir；工作区（`Config/gd`）仍需用户在设置页指定——launcher 的仓库自动推断只适用于 ct-tool 仓库布局。首启引导在设置页默认打开即可，本次不做自动探测。

## Risks / Trade-offs

- [Windows 杀软误报（PyInstaller 产物常见）] → onedir 相对低频；后续代码签名；必要时提交 Microsoft WDSI 申诉
- [Python 3.14 与 PyInstaller 的兼容性未知] → 先以 ct venv（3.14）试构建；失败则用 3.13 建独立打包 venv（PyInstaller 支持成熟）
- [macOS 未公证，内部分发需右键打开] → 内部工具可接受；正式对外分发再补公证
- [内置运行时与 ct 源码版本绑定，改工具需重打包] → 构建脚本化降低门槛；设置页显示运行时版本（后续可选）
- [包体积增加（flask + pydantic 等 onedir 约 40–60MB）] → 应用已有 47MB，量级可接受

## Migration Plan

1. 先在 ct-tool 打通 macOS 构建链路与内置优先逻辑（外部回退保留，旧配置不受影响）
2. 交付阶段在 fabulous-game 移除 `Config/ct`、`Config/launcher` 源码，仅保留 `Config/gd` 与构建产物；回滚依赖 git 历史，launcher 外部回退保证功能不中断
3. Windows 构建脚本交由用户在有 Flutter 的 Windows 机器执行产出 exe

## Open Questions

- 设置页是否展示「当前运行时来源（内置/外部）」与内置版本号——可延后，不影响规格与任务拆分
