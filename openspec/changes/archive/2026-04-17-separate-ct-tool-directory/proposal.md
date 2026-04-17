## Why

`gd/` 目录当前同时承担"工具仓库"和"工作空间"两个角色：Python 源码、打包配置与策划数据文件混放，两者生命周期不同（工具跟随版本迭代，数据随内容变更），且 `ct_tool.egg-info/` 等构建产物会污染数据目录。

## What Changes

- 新建 `ct-tool/` 目录，作为工具的独立仓库根
- 将 `gd/ct/`（Python package）移入 `ct-tool/ct/`
- 将 `gd/pyproject.toml`、`gd/requirements.txt` 移入 `ct-tool/`
- 将 `gd/docs/` 移入 `ct-tool/docs/`
- `gd/` 精简为纯数据工作空间，仅保留 `config/`、`excel/`、`output/`、`cache/`、`i18n/`、`tools/`
- 安装命令从 `cd gd && pip install -e .` 变为 `cd ct-tool && pip install -e .`

## Capabilities

### New Capabilities

- `tool-workspace-separation`: 工具源码与数据工作空间在目录层级上明确分离，各自有独立的根目录

### Modified Capabilities

（无——CLI 接口、Schema 格式、导出行为均不变）

## Impact

- **目录结构**：`ct-tool/`（新增）、`gd/`（精简，移除源码相关文件）
- **安装流程**：开发者需从 `ct-tool/` 执行 `pip install -e .`
- **运行流程**：`ct export` 等命令在 `gd/` 下执行，不受影响
- **CLAUDE.md**：需更新安装路径说明
