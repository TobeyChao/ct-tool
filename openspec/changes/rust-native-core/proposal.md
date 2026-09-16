## Why

当前 Python 管线在生成缓存命中前仍逐表解析校验 Excel，缓存键还会重复遍历和序列化输入。需要以可测量的性能收益为目标，建设跨平台 Rust 核心，让 CLI 与原生桌面共享唯一业务链路，同时保留现有产物格式和可靠发布语义。

## What Changes

- 新增 Rust workspace，提供 `ct-core`、独立 `ct` CLI 和供 Flutter 调用的版本化 stdio worker；运行不依赖 Python、浏览器或 HTTP 服务。
- 迁移现有 Schema/资源图、Excel 读取与模板迁移、校验、i18n、JSON/FBS/FlatBuffers/C#/Lua 生成、部署、状态及 Schema 候选/YAML-only 保存用例。
- 增加类型化解析缓存、分层指纹、有界并行和确定性输出，按依赖失效，避免热导出重复解析；缓存与成功账本继续分离。
- **BREAKING（内部执行契约）**：默认导出允许复用验证过的解析及局部校验结果，替代“每次重新解析全部输入”的要求；校验覆盖范围和拒绝非法数据的保证不变。`--all` 完整重建。
- 保持 CLI 命令、过滤规则、产物字节、账本和可恢复事务兼容；新增 worker 入口，不支持 Rust `ct panel`，旧 Web 入口只存在于迁移对照实现。
- 建立冷全量、热缓存、单表修改、译文修改基准与 Python 对照验收；Rust CLI 首发覆盖 Windows/macOS/Linux。

## Capabilities

### New Capabilities

- `native-core-runtime`: Rust 运行时、版本化协议、兼容切换与性能验收。

### Modified Capabilities

- `incremental-export`: 扩展解析/校验缓存与依赖失效，保留输出和账本语义。
- `cli-interface`: 对齐增量校验复用和 --all 语义，保留命令输出及部署策略。
- `unity-deploy`: 对齐热缓存校验覆盖的表述，保留每次成功 CLI 导出后的部署。
- `tool-workspace-separation`: 明确原生源码、安装和测试入口与旧 Python 对照工程的关系。

## Impact

新增拟定 `native/` Cargo workspace、协议和对照夹具，逐步迁移 `ct/src/ct/{app,schema,excel,export,cache,storage}` 的职责。既有 CLI 业务命令语义沿用 `cli-interface`；Python 专有 panel 入口不属于新 CLI 的兼容范围。

与 `native-flutter-workbench` 的边界：本 change 定义并实现 worker 协议及所有业务用例，界面 change 实现客户端和桌面安装包。先冻结 v1 契约，随后可独立开发，不建立双向实现依赖。

不设计新的游戏数据格式，不要求用户迁移 YAML/Excel，不调用 flatc 生成正式产物，不跳过 ref 闸门。旧 Python 只作过渡对照；验收后生产入口统一使用 Rust，整体源码删除另行清理。性能目标是待测验收门槛，不宣称当前已达到。
