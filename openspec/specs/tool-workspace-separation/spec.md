## Purpose

把工具源码（ct-tool）与游戏数据工作空间（gd）分离为独立目录，使工具可安装复用、数据空间保持纯净。

## Requirements

### Requirement: gd/ 目录仅包含工作空间数据
`gd/` 目录 SHALL 不包含任何 Python 源码文件、`pyproject.toml`、`requirements.txt` 或 `ct_tool.egg-info/`。

#### Scenario: gd/ 下不存在工具文件
- **WHEN** 查看 `gd/` 目录
- **THEN** 不存在 `ct/`、`pyproject.toml`、`requirements.txt`、`ct_tool.egg-info/`，仅包含 `config/`、`excel/`、`output/`、`cache/`、`i18n/`、`tools/`

### Requirement: ct export 仍在 gd/ 下执行
工作空间操作（`ct export`、`ct validate` 等）SHALL 在 `gd/` 目录下执行（或通过 `--root gd/` 指定），行为与迁移前完全一致。

#### Scenario: 迁移后导出流程不变
- **WHEN** 在 `gd/` 目录下执行 `ct export`
- **THEN** 工具正常读取 `config/`、`excel/`，输出写入 `output/`，与迁移前行为一致

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
