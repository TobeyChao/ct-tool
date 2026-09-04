## REMOVED Requirements

### Requirement: 工具源码存放于独立目录 ct-tool/
仓库根目录 SHALL 包含 `ct-tool/` 子目录，其中存放工具的全部源码和打包配置，包括：Python package `ct/`、`pyproject.toml`、`requirements.txt`、`docs/`。

### Requirement: 工具可从 ct-tool/ 安装
开发者 SHALL 能够通过在 `ct-tool/` 目录下执行 `pip install -e .` 完成工具安装，安装后 `ct` 命令可在任意目录使用。

## ADDED Requirements

### Requirement: 工具源码位于根级 ct/ 项目并采用 src layout
仓库根目录 SHALL 包含自包含的 `ct/` 项目目录：Python 包位于 `ct/src/ct/`，`pyproject.toml`、`requirements.txt`、`tests/`、`docs/` 随项目存放。

#### Scenario: 目录结构符合规范
- **WHEN** 查看仓库根目录与 `ct/` 项目
- **THEN** 存在 `ct/src/ct/` 包目录，且 `ct/` 下同时包含 `pyproject.toml`、`requirements.txt`、`tests/`、`docs/`，根目录不存在平铺的 `tests/`、`docs/` 或 `pytest.ini`

### Requirement: 工具可从 ct/ 安装
开发者 SHALL 能够通过在 `ct/` 目录下执行 `pip install -e .` 完成工具安装，安装后 `ct` 命令可在任意目录使用。

#### Scenario: 从 ct/ 安装后命令可用
- **WHEN** 在 `ct/` 目录下执行 `pip install -e .`
- **THEN** 命令 `ct --help` 返回正常输出，无报错

### Requirement: 测试在 ct/ 项目内运行
开发者 SHALL 能够在 `ct/` 目录下执行 `pytest` 运行全部测试，无需任何 `pythonpath` 配置。

#### Scenario: 项目内跑通全量测试
- **WHEN** 在 `ct/` 目录下执行 `pytest`
- **THEN** 全部测试通过，仓库根目录不存在 `pytest.ini`
