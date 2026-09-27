## REMOVED Requirements

### Requirement: 工具源码位于根级 ct/ 项目并采用 src layout
**Reason**: 功能对等验收后 Python 工程退役，正式工具改为原生内核与独立 Web 资源。
**Migration**: 有效静态资源、文档、夹具与验收迁往 native/、web/、launcher/ 对应位置；保留历史出处，不以删除代替迁移。

### Requirement: 工具可从 ct/ 安装
**Reason**: 正式工具不再由 pip 安装或运行 Python。
**Migration**: 使用原生平台发行包或 Cargo 构建，并通过明确路径避免旧同名 ct 命令遮蔽。

### Requirement: 测试在 ct/ 项目内运行
**Reason**: 旧 pytest 入口随 Python 工程退役。
**Migration**: 必要场景迁为 Rust、JS/TS 浏览器及既有 Flutter 验收，退役前记录覆盖映射与通过证据。

## ADDED Requirements

### Requirement: Native and Web source separation
正式内核与 CLI/HTTP/worker 源码 SHALL 位于 native/，Web 静态资源与浏览器验收 SHALL 位于 web/，Flutter SHALL 保持 launcher/；游戏工作区 SHALL 保持纯数据。Python 工程 SHALL 仅在功能对等与独立验收通过后删除，有效文档和夹具 SHALL 先迁移且修复活跃引用。

#### Scenario: Post-retirement repository
- **WHEN** 查看完成迁移后的正式源码结构
- **THEN** native/、web/、launcher/ 各自具有明确入口，不依赖旧 ct/；gd/ 不含工具源码或构建依赖

### Requirement: Native installation and development entry points
用户 SHALL 可通过平台原生发行包获得 ct CLI、worker 和 panel，并在任意目录使用 --root 指定工作区。开发者 SHALL 可从 native/ 构建；安装与升级文档 SHALL 说明旧 Python ct 的路径冲突和新入口，不要求 pip、venv 或全局 Python。

#### Scenario: Install and run without Python
- **WHEN** 用户安装原生发行包并指定工作区运行 export 或 panel
- **THEN** 两条入口均使用原生内核，静态资源可用且不访问旧 Python 工程

### Requirement: Python-free verification and fixture regeneration
正式构建、内核/API 测试、浏览器测试、Flutter 回归、性能回归、必要夹具再生与发行校验 SHALL 不需要 Python。旧测试 SHALL 有替代覆盖映射，缺失旧工程 SHALL 不成为跳过必要验收的理由。Python 来源的静态留档与纯历史实验 SHALL 可保留，但不得作为正式流程的隐藏可执行依赖；仍被正式验收调用的实验脚本 SHALL 被替代。

#### Scenario: Run the supported verification entries
- **WHEN** 干净环境使用 Rust、Node/浏览器和适用的 Flutter 工具链执行各自入口
- **THEN** 全部必要验证使用临时工作区并独立完成，无需 Python 路径或真实 gd/ 夹具

#### Scenario: Regenerate required fixtures
- **WHEN** 删除可再生测试/基准输出后执行正式夹具生成入口
- **THEN** 所需规模和边界夹具可重建，摘要或语义符合冻结契约，不调用遗留 Python 生成器
