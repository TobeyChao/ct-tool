## Purpose

把工具源码（ct-tool）与游戏数据工作空间（gd）分离为独立目录，使工具可安装复用、数据空间保持纯净。

## Requirements

### Requirement: gd/ 目录仅包含工作空间数据
`gd/` 目录 SHALL 不包含任何 Python 源码文件、`pyproject.toml`、`requirements.txt` 或 `ct_tool.egg-info/`。

#### Scenario: gd/ 下不存在工具文件
- **WHEN** 查看 `gd/` 目录
- **THEN** 不存在 `ct/`、`pyproject.toml`、`requirements.txt`、`ct_tool.egg-info/`，仅包含 `config/`（含 `global.yaml`）、`excel/`、`output/`、`cache/`、`i18n/`；`gd/tools/` 与 `gd/scripts/` 均不存在

### Requirement: ct export 仍在 gd/ 下执行
工作空间操作（`ct export`、`ct validate` 等）SHALL 在 `gd/` 目录下执行（或通过 `--root gd/` 指定），行为与迁移前完全一致。

#### Scenario: 迁移后导出流程不变
- **WHEN** 在 `gd/` 目录下执行 `ct export`
- **THEN** 工具正常读取 `config/`、`excel/`，输出写入 `output/`，与迁移前行为一致

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
