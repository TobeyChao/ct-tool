## Why

main 分支的 Web 工作台已有完整的浏览器编辑流程，本分支 Rust 内核已有主要业务能力，但两者尚未连接，Web 仍依赖 Python/Flask。需要在功能对等验收后由 Rust 同时承担业务与 HTTP 服务，保留 Web 使用体验，并移除工具的 Python 运行、构建及验收依赖。

## What Changes

- 新增 Rust HTTP 服务并恢复原生 `ct panel`，托管从现有 Web 提取的 HTML/CSS/JS；生产包内嵌静态资源，使用者无需 Python、Node 或 Flutter。
- HTTP、stdio worker 与 CLI 共用 `ct-app` 用例及可靠存储；补齐 Web 所需的候选资源、保存回执、状态分类、翻译汇总、任务与日志历史，禁止通过 Python 补算。
- 保留现有五个 Web 模块、视觉与响应式布局、IndexedDB 草稿、Schema 双守卫和 YAML-only 保存、独立模板操作及只发布本地产物的 Web 导出策略。
- 明确任务属于服务进程：刷新、关闭标签页不等同于取消；显式取消与进程关闭遵守发布安全边界。修正旧 Web 规格中自动修改 Excel、无增量导出等过时描述。
- 支持当前 Web 的同源草稿接续、历史导入及当前发布 journal 恢复；未知旧事务保留材料并阻止写入，不承诺任意历史格式自动迁移。
- **BREAKING**：对等验收后删除 Python 内核、Flask 服务、Python CLI/安装入口及其有效测试和工具脚本依赖；最终不提供双内核选择、自动回退或运行时切换。迁移期 Python 仅作临时对照。
- 将浏览器测试迁至 JS/TS Playwright，HTTP 验收迁至 Rust，必要夹具生成与基准工具迁至 Rust/JS；在无 Python、无旧 `ct/` 工程环境中完成构建、测试、夹具再生和发行验证。

## Capabilities

### New Capabilities

- `native-web-runtime`: Rust HTTP 服务、共享任务生命周期、Web 契约适配、升级接续及无 Python 发行验收。

### Modified Capabilities

- `web-panel`: 原生服务运行、增量导出及安全任务生命周期、YAML-only 表格管理和历史连续性。
- `cli-interface`: 原生 `ct panel` 启动契约，以及去除错误诊断对 Python traceback 的强制要求。
- `tool-workspace-separation`: 原生工具、独立 Web 资源及无 Python 安装/测试入口，删除旧 Python 工程前的验收门槛。

## Impact

- 拟新增 `native/crates/ct-web/`、`web/`，修改 `ct-app`、必要的公共任务基础设施、`ct-cli`、`ct-xtask`、原生发行流程及 CI；迁移 `ct/src/ct/web/static/`、`ct/tests/web/` 和仍有效的 `ct/docs/`。
- 以本地 main `8dc7b81` 的 Web 行为为初始参照；实施前记录实际采纳提交与工作树差异。当前未提交的 native/launcher/gd 改动不由本提案覆盖或回滚。
- 复用 `rust-native-core` 已实现能力，不重建内核。本提案取代其“不提供 ct panel / Web 退役”的范围决策，并承接最终 Python 退役门槛；不把其未完成的平台、恢复、性能或游戏端验证自动视为通过。
- Flutter 工作台继续消费原生 worker，不改回浏览器 launcher；其既有功能和协议不得因共享模块调整而回归。本次不新增 Web 部署入口、云服务、多用户协作、前端框架重写或任意旧事务修复器。
- 仓库历史提案、留档数据可保留 Python 来源说明；`test-proj/` 中实际仍参与受支持验收的 Python 脚本须替代，纯历史实验只归档说明、不批量删除用户资料。
- 全程使用临时工作区夹具；对等与删除门槛见 design、specs、tasks，规划完成不代表运行验收通过。
