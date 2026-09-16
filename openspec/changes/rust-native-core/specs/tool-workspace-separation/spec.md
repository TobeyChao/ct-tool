## MODIFIED Requirements

### Requirement: 工具源码位于根级 ct/ 项目并采用 src layout
仓库 SHALL 将原生工具源码放在根级 native/ Cargo workspace，Flutter 桌面放在 launcher/，游戏工作区不包含工具源码。迁移期 ct/ 的 Python src layout、tests/docs SHALL 保留作兼容对照；不得把仍需对照的 Python 工程删除当作迁移验收。

#### Scenario: 目录结构符合规范
- **WHEN** 查看迁移后的仓库
- **THEN** native/ 包含原生构建/测试入口，launcher/ 包含桌面工程，ct/ 保留过渡对照，gd/ 无工具源码或构建依赖

### Requirement: 工具可从 ct/ 安装
正式 CLI SHALL 可通过平台原生发行包安装，并在任意目录调用 ct --help；开发者 SHALL 可从 native/ 构建。迁移期 ct/ 的 pip install -e . 仅用于旧版本对照，不作为新生产环境的前提；安装说明 SHALL 避免同名 ct 路径混淆。

#### Scenario: 从 ct/ 安装后命令可用
- **WHEN** 开发者在隔离 Python 环境从 ct/ 安装旧对照工具
- **THEN** 旧 ct --help 可用且文档标识为对照入口，不覆盖正在验收的原生可执行路径

#### Scenario: Native install without Python
- **WHEN** 用户安装原生发行包并在工作区执行 ct export
- **THEN** 使用原生核心，无需安装 Python 或 pip 包

### Requirement: 测试在 ct/ 项目内运行
原生核心 SHALL 从 native/ 运行 Cargo 测试，桌面从 launcher/ 运行 Flutter 测试；迁移期 Python 对照测试 SHALL 继续通过 ct/.venv 在 ct/ 运行，不使用全局 Python 或真实 gd 作为夹具。各测试入口 SHALL 在文档明确区分。

#### Scenario: 项目内跑通全量测试
- **WHEN** 在 ct/ 使用其虚拟环境运行 pytest
- **THEN** 对照套件保持独立可执行，不要求给 Python 增加 native 源码路径

#### Scenario: Native and desktop checks
- **WHEN** 执行原生及桌面各自的测试入口
- **THEN** 两者使用临时工作区，结果和覆盖映射可供验收，不能把旧 Python 测试通过当成新实现已验证
