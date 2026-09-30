# main 集成范围接管（2026-09-28）

用户确认以 main 的 Web 桌面壳作为产品入口，由原生 `ct panel` 提供服务。
原分支其他工作保存在 `2d7dfc9`；main 的提案检查点为 `55e3822`。
本次只引入 native 源码并适配 main Web/launcher，未整体合并原分支。

| 既有 change | 本次接管 | 继续保留的责任与未验收项 |
|---|---|---|
| rust-native-core | 撤销 panel 退役的产品决策；原生 CLI 同时提供 panel；全仓 Python 删除归本 change 门槛约束 | canonical 用例、worker v1、产物兼容、性能与各平台验收；原 tasks 勾选不变，当前 main 上未勾选项目不自动转为通过 |
| native-flutter-workbench | main 不采用完整 Flutter 工作台；launcher 保留浏览器壳、工作区/端口/托盘/自启，运行时迁至 native | 原分支 Flutter 工作台的成果和证据保留在其提交；不把其测试计作 main Web/launcher 验收，也不替它归档 |

原生源码已有测试结果不能替代本 change 的 G1/G2/G3。完整 Web 场景、macOS
发行、独立读取端及无 Python 夹具再生链仍按当前 tasks 与验收记录推进。
2026-09-30 用户修订支持范围：Windows 延后，Linux 不支持；本轮退役门槛不再
要求这两个平台的发行证据。历史记录保留原始范围，不将未运行平台登记为通过。
`ct/` 与必要 Python 脚本在门槛未全部通过前保留。

规格同步顺序：先核对既有 change 中不冲突的 canonical/协议/产物能力，再以
本 change 的 delta specs 更新 Web、CLI panel、launcher 和工具目录契约。
本 change 未完成前不执行同步或归档。后续若归档旧 change，必须先重新核对
其 `launcher`、`cli-interface`、`tool-workspace-separation` delta，排除已被
接管的 panel 退役、完整 Flutter 替换或 Python 目录必需条款；不能在晚归档
时把它们覆盖回主规格。

两个旧 change 的 proposal 已加本记录入口，任务状态与原分支文件保持原样。
