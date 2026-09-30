# ct Launcher

main 的 Flutter 桌面壳负责工作区、端口、日志、托盘与自启，启动原生 `ct panel` 并在服务就绪后打开浏览器。
业务界面保留在 Web；没有引入完整 Flutter 工作台。

本轮支持 macOS；Windows 构建与验收延后，Linux 不提供支持或发行包。

运行时按“应用包内置 → 设置中的原生 ct 路径”查找，不回退 Python 或 venv。
旧工作区、端口、托盘和自启偏好保留，旧 Python 工具目录不会作为原生路径迁移；新安装不默认绑定 `gd/`。
停止/退出会通过 stdin EOF 等待服务完成当前发布，不做超时强杀。

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

macOS 将原生二进制放到 `.app/Contents/Resources/runtime/ct`，生成 ad-hoc 签名的 `.app` 和 DMG；
已保留的 Windows 实现布局是 `Release/runtime/ct.exe`，尚未完成本轮验收。没有 PyInstaller/解释器负载。
打包脚本可用 `RUNTIME_PACKAGE`（macOS）或 `-RuntimePackage`（Windows）指定原生包。
