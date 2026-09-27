# 桌面 UI 帧时间（任务 5.2，profile 模式，macos）

- 夹具：M 档（50 表 × 2000 行 × 20 列），真实 `ct worker`（`/Users/tobeychao/Documents/Projects/ct-tool/native/target/release/ct`）
- 口径：`WidgetsBinding.addTimingsCallback` 采到的逐帧 build/raster 时长
- 预览行数：300
- 设备：MacBookPro18,1 / Apple Silicon arm64，macOS 27.0，Flutter 3.47.0；profile 桌面应用 + release Rust worker
- 运行：`CT_WORKER_BIN=<native/target/release/ct> flutter drive --driver=test_driver/integration_test.dart --target=integration_test/ui_responsiveness_test.dart -d macos --profile --no-pub`。本机 `open -a <profile ct_launcher.app>` 将同一测试窗口置前（Flutter 报 `Failed to foreground app; open returned 1` 时等待首帧）；最终驱动 exit 0。
- 60Hz 参考：`totalSpan` p95 应 <16.7ms；下表 p95/max 单位均为毫秒

| 阶段 | 帧数 | build p50/p95/max (ms) | raster p50/p95/max (ms) | totalSpan p50/p95/max (ms) |
|---|---|---|---|---|
| 大字段表 | 65 | 0.447 / 0.855 / 1.188 | 1.599 / 2.011 / 2.939 | 2.386 / 3.305 / 3.986 |
| 分页预览 | 340 | 0.542 / 1.073 / 20.492 | 0.624 / 2.066 / 4.628 | 1.381 / 3.451 / 25.341 |
| 持续日志 | 104 | 0.664 / 1.585 / 3.683 | 1.074 / 1.769 / 4.409 | 2.241 / 3.405 / 8.294 |

分页预览首次完整运行测得 build max 40.053ms、raster max 45.998ms、totalSpan max 65.338ms，超过 build 34ms 门槛。原因是每次续页都将累计 300×20 格同步格式化为文字。现在预览行按可见索引延迟转换，同一行复用结果；界面按内核游标加载 6 页至 300 行。修复后分页预览 build max 20.492ms、raster max 4.628ms、totalSpan max 25.341ms，三阶段均满足脚本门槛（build p95 <8ms、max <34ms；raster p95 <33.4ms、max <100ms）。这是一次机器上的前后测量，长尾数值会随系统负载变化。
