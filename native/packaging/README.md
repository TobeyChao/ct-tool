# packaging

平台发行包元数据与构建脚本（由 `cargo run -p ct-xtask -- dist` 驱动）：

- `windows/`：MSI/便携包，含 ct.exe（CLI + worker）
- `macos/`：CLI 二进制与供 launcher 嵌入的 Resources 布局
- `linux/`：CLI 二进制（首发仅 CLI，Linux GUI 不在首发范围）

验收要求：无 Python/无仓库环境可安装运行，中文与空格路径可用（任务 6.6）。