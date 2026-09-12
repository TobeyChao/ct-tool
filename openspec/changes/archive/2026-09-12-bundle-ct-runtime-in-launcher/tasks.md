## 1. PyInstaller 打包

- [x] 1.1 新增 `ct/packaging/ct.spec`：PyInstaller onedir，入口 `ct.cli:app`，收集 `ct.web` 静态资源（`collect_data_files`），排除 flatc 等面板不需要的依赖
- [x] 1.2 在 ct venv 安装 PyInstaller 并试构建；验证 Python 3.14 兼容性，失败则用 Python 3.13 建独立打包 venv（设计 Decisions 1/Risks）
- [x] 1.3 验证冻结产物：`dist/ct-runtime/ct panel --help` 可用、面板静态资源正常加载、`export/validate` 等子命令可用

## 2. launcher 内置运行时

- [x] 2.1 `panel_service.dart` 新增内置运行时平台定位：macOS `.app/Contents/Resources/runtime/ct`、Windows exe 同级 `runtime\ct.exe`（设计 Decisions 2）
- [x] 2.2 启动逻辑改为内置优先、外部 toolDir 回退；两种模式命令参数一致（`--root/--host/--port/--no-browser`），日志与退出处理复用现有代码（spec：内置运行时优先/启动行为等价）
- [x] 2.3 内置与外部均缺失时，错误提示同时说明「内置运行时缺失」与「工具目录配置指引」，不残留进程（spec：全部缺失时报告错误）
- [x] 2.4 验证三态：内置存在→用内置；内置缺失→回退外部；两者皆缺→错误提示（spec：各场景）

## 3. 构建脚本与文档

- [x] 3.1 新增 macOS 构建脚本 `launcher/tool/build_macos.sh`：PyInstaller onedir → `flutter build macos --release` → 拷贝 `runtime/` 进 `.app/Contents/Resources/` → `codesign --force --deep -s -` → 输出可分发 `.app`（设计 Decisions 4）
- [x] 3.2 新增 Windows 构建脚本 `launcher/tool/build_windows.ps1`：同构流程，产物 `runtime\ct.exe` 与 launcher exe 同级（在 Windows 机器执行）
- [x] 3.3 更新 ct-tool 根 `AGENTS.md` 与 launcher docs：打包/分发说明、产物位置、fabulous-game 消费方式、Windows 构建前提

## 4. fabulous-game 交付（fabulous-game 仓库执行）

- [x] 4.1 移除 `Config/ct` 与 `Config/launcher` 源码（git 历史可恢复，保留 `Config/gd`）
- [x] 4.2 将 macOS 构建产物放入 fabulous-game（如 `Config/launcher-apps/`）并提交；Windows exe 由用户在 Windows 机器产出后放置
- [x] 4.3 更新 fabulous-game `Config/AGENTS.md`：工具使用方式改为「内置运行时应用 + 工作区指向 `Config/gd`」，不再需要工具目录配置

## 5. 端到端验证

- [x] 5.1 无 ct-tool 拉取、无 Python 环境（用干净机器/移除 toolDir 配置模拟）下双击 macOS `.app`，能启动面板并完成一次导出
- [ ] 5.2 Windows 链路（用户机器）：`ct_launcher.exe` 同级 `runtime\` 可启动面板并导出
