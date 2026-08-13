# ct_launcher

ct 配表工具桌面启动器：一键启动面板、托盘常驻、开机自启。

## 构建

构建脚本会先用 PyInstaller 冻结 `ct` CLI 并嵌入应用包，产物自带运行时，目标机器无需安装 Python：

- macOS：`launcher/tool/build_macos.sh`（需 Flutter、Xcode + CocoaPods）
- Windows：`launcher/tool/build_windows.ps1`（在 Windows 机器执行）

产物分别为 `.app`（内置 `Contents/Resources/runtime/`）与 `Release/` 目录（`ct_launcher.exe` + 同级 `runtime\`）。

## 运行

双击启动后，在设置页把「工作区」指向游戏数据目录（如 `Config/gd`，需含 `config/global.yaml`）；工具目录仅在应用包未内置运行时或需要外部开发环境时配置。
