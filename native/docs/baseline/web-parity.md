# Native Web 接入基线

- Web：main `8dc7b81`；提案在 main 提交为 `55e3822`。
- 原生源码：`feat/native-workbench-cutover` 检查点 `2d7dfc9`，仅引入 native/；原分支已保存其他 launcher/gd 改动，不整体合并。
- launcher：按用户确认保留 main 的浏览器启动器，迁移其运行时发现、打包与安全退出，不引入完整 Flutter 工作台。
- 场景与源码摘要：`web-parity.json`。目标测试路径为计划落点，pending 不是已通过；完成后填写实际锚点与运行证据。
- 活跃规格：`openspec/changes/native-web-python-retirement/`；原分支旧 change 的“Web 退役/无 panel”结论不适用于此集成。

## 允许的明确差异

1. HTTP 服务与内核由 Rust 承担；发行包不含解释器。
2. 缺配置等工作区错误通过可访问诊断面板呈现；监听失败仍非零退出。
3. 页面关闭不隐式取消任务；取消/服务关闭遵循发布安全边界。
4. 强制导出绕过缓存；默认增量复用，保存仍仅 YAML。
5. 发布材料无法可靠恢复时保留并阻止写入，不退回 Python。

其他 main Web 的用户可见行为均要求替代验收，尤其草稿、长文本翻译、键盘/焦点、900/740px 投影与视口/缩放矩阵。

## 门槛

G1 Web 全流程、G2 原生跨入口与产物回归：本机通过，见 [验收记录](web-smoke/verification.md)。G3 无 Python 开发/再生/三平台发行：未完成。

首次引入运行的 `cargo test --workspace --no-fail-fast` 日志在本机 `/tmp/ct-native-main-baseline.log`；发现 coverage_matrix 仍引用原分支 Flutter 工作台测试。必须按 main launcher 范围重新映射；此发现不构成任何门槛通过，不能删掉断言冒充通过。

## 本次已执行

执行命令、平台、原始日志与完成边界见 [web-smoke/verification.md](web-smoke/verification.md)。146/146 旧场景已挂接实际替代锚点，`check:parity --require-complete` 无待迁移项；3 个旧 Schema/资源/保存 API 文件的 27 个场景已全部由真实原生 HTTP 测试承接。发布版与旧面板的同机性能配对、Cargo/Flutter 全量回归及原生导出后的独立 .NET 读取端已留档，G1/G2 完成；G3 尚未完成，暂不删除 Python。

Python 相关路径初始清单见 `python-retirement-inventory.json`（211 项，包含历史引用；pending-audit 不表示可删除）。
