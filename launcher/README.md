# ct Launcher

Flutter 桌面工作台通过原生 `ct worker` 的 stdio NDJSON 协议提供 Schema 编辑、翻译、模板、校验、导出与部署，并管理工作区、日志、任务、托盘与自启。
CLI、Web 和桌面工作台复用 Rust 内核用例；桌面端直接连接 worker。

本轮支持 macOS；Windows 构建与验收延后，Linux 不提供支持或发行包。

运行时按“应用包内置 → 设置中的原生 ct 路径”查找，不回退 Python 或 venv。
旧工作区、托盘和自启偏好保留；main 保存的 `native_runtime_path` 迁移为工作台的 `runtime_path`，旧 Python 工具目录与端口等面板偏好清除。新安装不默认绑定 `gd/`。
停止/退出先请求 worker shutdown，再通过 stdin EOF 等待发布收尾和进程退出，不做超时强杀。

## 开发与验证

```sh
cargo build --manifest-path native/Cargo.toml -p ct-cli
cd launcher
flutter test
flutter run -d macos
```

在设置中选择工作区；未自动找到开发二进制时填写 `native/target/debug/ct` 的绝对路径。

## 打包

先在 `native/` 执行 `cargo run -p ct-xtask -- dist`，再从仓库根目录执行：

- macOS：`bash launcher/tool/build_macos.sh`（Flutter、Xcode、CocoaPods）。
- Windows 脚本保留作后续材料，本轮不作为受支持发行入口。

发行说明与已知限制（交付形态、安装/卸载、快捷键、验证边界）：[`docs/release-notes.md`](docs/release-notes.md)。

工作台经 stdio 拉起内置 `ct worker`，握手校验协议版本与能力；版本不匹配时写入入口保持禁用并在横幅说明原因。

macOS 将原生二进制放到 `.app/Contents/Resources/runtime/ct`，生成 ad-hoc 签名的 `.app` 和 DMG；
已保留的 Windows 实现布局是 `Release/runtime/ct.exe`，尚未完成本轮验收。没有 PyInstaller/解释器负载。
打包脚本可用 `RUNTIME_PACKAGE`（macOS）或 `-RuntimePackage`（Windows）指定原生包。
