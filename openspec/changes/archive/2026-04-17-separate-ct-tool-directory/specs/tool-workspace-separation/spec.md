## ADDED Requirements

### Requirement: 工具源码存放于独立目录 ct-tool/
仓库根目录 SHALL 包含 `ct-tool/` 子目录，其中存放工具的全部源码和打包配置，包括：Python package `ct/`、`pyproject.toml`、`requirements.txt`、`docs/`。

#### Scenario: 目录结构符合规范
- **WHEN** 查看仓库根目录
- **THEN** 存在 `ct-tool/` 目录，且其中包含 `ct/`、`pyproject.toml`、`requirements.txt`、`docs/`

### Requirement: gd/ 目录仅包含工作空间数据
`gd/` 目录 SHALL 不包含任何 Python 源码文件、`pyproject.toml`、`requirements.txt` 或 `ct_tool.egg-info/`。

#### Scenario: gd/ 下不存在工具文件
- **WHEN** 查看 `gd/` 目录
- **THEN** 不存在 `ct/`、`pyproject.toml`、`requirements.txt`、`ct_tool.egg-info/`，仅包含 `config/`、`excel/`、`output/`、`cache/`、`i18n/`、`tools/`

### Requirement: 工具可从 ct-tool/ 安装
开发者 SHALL 能够通过在 `ct-tool/` 目录下执行 `pip install -e .` 完成工具安装，安装后 `ct` 命令可在任意目录使用。

#### Scenario: 从 ct-tool/ 安装后命令可用
- **WHEN** 在 `ct-tool/` 目录下执行 `pip install -e .`
- **THEN** 命令 `ct --help` 返回正常输出，无报错

### Requirement: ct export 仍在 gd/ 下执行
工作空间操作（`ct export`、`ct validate` 等）SHALL 在 `gd/` 目录下执行（或通过 `--root gd/` 指定），行为与迁移前完全一致。

#### Scenario: 迁移后导出流程不变
- **WHEN** 在 `gd/` 目录下执行 `ct export`
- **THEN** 工具正常读取 `config/`、`excel/`，输出写入 `output/`，与迁移前行为一致
