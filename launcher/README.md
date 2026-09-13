# ct_launcher

ct 配表工具桌面启动器：一键启动面板、托盘常驻、开机自启。

## 构建

构建脚本会先用 PyInstaller 冻结 `ct` CLI 并嵌入应用包，产物自带运行时，目标机器无需安装 Python：

- macOS：`launcher/tool/build_macos.sh`（需 Flutter、Xcode + CocoaPods）
- Windows：`launcher/tool/build_windows.ps1`（在 Windows 机器执行）

产物分别为 `.app`（内置 `Contents/Resources/runtime/`）与 `Release/` 目录（`ct_launcher.exe` + 同级 `runtime\`）。

### 只刷新内置运行时（改了 ct、外壳没改）

外壳只按固定路径拉起 `runtime/ct`（见 `lib/services/panel_service.dart`），与 ct 版本无关，
所以**改 ct 不必重建整个应用**，重新冻结运行时再覆盖即可：

```bash
cd ct && .venv/bin/python -m PyInstaller --noconfirm --distpath dist --workpath build packaging/ct.spec
rm -rf <app>/Contents/Resources/runtime && mkdir -p <app>/Contents/Resources/runtime
cp -R ct/dist/ct-runtime/. <app>/Contents/Resources/runtime/
codesign --force --deep -s - <app>      # Resources 变了原签名即失效，不重签 macOS 拒绝启动
```

Windows 侧把 `<app>` 换成 `ct_launcher.exe` 同级目录，运行时放到同级 `runtime\`。
PyInstaller 不支持跨平台构建，Windows 运行时必须在 Windows 上冻结。

## 运行

双击启动后，在设置页把「工作区」指向游戏数据目录（如 `Config/gd`，需含 `config/global.yaml`）；工具目录仅在应用包未内置运行时或需要外部开发环境时配置。
