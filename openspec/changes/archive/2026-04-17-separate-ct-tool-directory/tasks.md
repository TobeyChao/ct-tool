## 1. 创建新目录结构

- [x] 1.1 在仓库根目录创建 `ct-tool/` 目录

## 2. 迁移工具文件

- [x] 2.1 将 `gd/ct/` 移动到 `ct-tool/ct/`
- [x] 2.2 将 `gd/pyproject.toml` 移动到 `ct-tool/pyproject.toml`
- [x] 2.3 将 `gd/requirements.txt` 移动到 `ct-tool/requirements.txt`
- [x] 2.4 将 `gd/docs/` 移动到 `ct-tool/docs/`

## 3. 清理 gd/ 残留

- [x] 3.1 删除 `gd/ct_tool.egg-info/`（迁移后重新安装会在 `ct-tool/` 下重新生成）

## 4. 验证安装与运行

- [x] 4.1 在 `ct-tool/` 下执行 `pip install -e .`，确认安装成功无报错
- [x] 4.2 在 `gd/` 下执行 `ct --help`，确认命令可用
- [x] 4.3 在 `gd/` 下执行 `ct export --all`，确认导出流程正常

## 5. 更新文档

- [x] 5.1 更新 `CLAUDE.md` 中的安装路径（`cd gd` → `cd ct-tool`）
- [x] 5.2 更新 `ct-tool/docs/README.md` 中的安装说明，反映新路径
