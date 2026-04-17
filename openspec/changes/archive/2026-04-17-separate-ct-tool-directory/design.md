## Context

`gd/` 是游戏数据工作空间，供策划填写 Excel、运行 `ct export` 生成产物。但目前它同时包含工具的 Python 源码（`ct/`）、打包配置（`pyproject.toml`、`requirements.txt`）和文档（`docs/`），两类内容生命周期和维护者不同。

拆分目标：新建 `ct-tool/` 目录承载所有工具源码，`gd/` 还原为纯数据工作空间。

## Goals / Non-Goals

**Goals:**
- 工具源码与工作空间数据在目录层级明确分离
- `ct_tool.egg-info/` 等构建产物不再出现在 `gd/` 下
- CLAUDE.md 和文档同步更新，反映新的安装路径

**Non-Goals:**
- 不重命名 Python package（仍为 `ct`）
- 不修改任何 CLI 接口或导出行为
- 不引入虚拟环境管理工具或 monorepo 工具链
- 不移动 `tools/flatc.exe`（属于工作空间运行时依赖）

## Decisions

### 工具目录命名：`ct-tool/`

与 `pyproject.toml` 中的包名 `ct-tool` 保持一致，不会和内部 package 目录 `ct/` 混淆。

备选 `tool/` 过于泛化，若仓库以后新增其他工具会产生歧义；`exporter/` 描述性强但脱离了现有命名体系。

### `docs/` 归属：随工具走

`docs/README.md` 记录 CLI 用法和 Schema 格式，是工具文档而非数据文档，放在 `ct-tool/docs/` 语义更准确。

### `tools/flatc.exe` 归属：留在 `gd/`

`flatc_path` 在 `config/global.yaml` 中以相对路径引用，解析基准是工作空间根目录。移走需修改配置约定，收益不大。

### 迁移方式：手动移动文件

变更仅涉及目录整理，无代码逻辑修改，直接 `mv` 即可。不引入脚本自动化，保持简单。

## Risks / Trade-offs

- **开发者肌肉记忆**：`pip install -e .` 的执行目录从 `gd/` 变为 `ct-tool/`，习惯旧流程的开发者需要适应。→ 在 CLAUDE.md 和 `ct-tool/docs/README.md` 中明确标注新安装路径。
- **编辑器/IDE 路径缓存**：部分编辑器可能缓存了旧的 Python 解释器路径或 import 路径，迁移后需重新配置。→ 属于一次性操作，可接受。

## Migration Plan

1. 创建 `ct-tool/` 目录
2. 移动 `gd/ct/` → `ct-tool/ct/`
3. 移动 `gd/pyproject.toml`、`gd/requirements.txt` → `ct-tool/`
4. 移动 `gd/docs/` → `ct-tool/docs/`
5. 删除 `gd/ct_tool.egg-info/`（重新安装时会在 `ct-tool/` 下重新生成）
6. 在 `ct-tool/` 下重新执行 `pip install -e .` 验证安装
7. 更新 CLAUDE.md 中的安装路径说明

**回滚**：将文件移回 `gd/`，重新安装即可，无数据丢失风险。
