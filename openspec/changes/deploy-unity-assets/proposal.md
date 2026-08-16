## Why

改表后 `ct export` 只产出到 `gd/output/`，Unity 工程的 Assets（`Content/Config` 二进制、`Scripts/Config/Gen` 代码、`Scripts/Lua/Config/Gen` 代码）不会自动更新，运行/打包前极易用到旧数据；同时二进制产物入库带来无意义的 diff。需要把"导表"与"同步到 Unity"合并为一步，且配置可见、失败可感知。

## What Changes

- **新增 deploy 配置**（`config/global.yaml` 的 `deploy:` section）：`enabled`、`unity_project`（相对 project_root 或绝对路径）、`targets`（source→dest 映射）、`build_targets`（`--for-build` 时追加）。所有字段带默认值，未配置/未启用时导表行为不变。
- **导出自动部署**：`ExportPipeline` 末尾新增 `DeployStep`——导表成功后按 targets 同步产物到 Unity Assets；"所有表均无变化"时跳过导出但仍执行部署。
- **目录同步语义**：目标目录与产物严格一致（新增/覆盖/删除多余文件）；`.meta` 保护——仍存在文件的 meta 不动，删除文件连带删同名 `.meta`；bin 纯覆盖。
- **失败即报错**：deploy 任一步失败，`ct export` 以非 0 退出；部署失败不提交缓存。
- **新增 `ct deploy` 子命令**：只部署不导出，与管道共用同一逻辑。
- **`--for-build`**：`export`/`deploy` 追加构建目标（如 `Assets/StreamingAssets/Config`）。
- **可见性**：web 面板工作区信息区显示 deploy 摘要（启用状态与目标绝对路径）；web 导出进度加 "Deploy" 步骤；`ct status` 输出 deploy 状态。
- 未配置 deploy 的项目行为完全不变（默认跳过）。

## Capabilities

### New Capabilities
- `unity-deploy`: 把导出产物分发到 Unity 工程 Assets 的能力——配置、自动部署、构建目标、可见性与失败语义。

### Modified Capabilities
- 无（既有 CLI/web/i18n 行为不变，deploy 是新增能力）。

## Impact

- 新增：`ct/export/deploy.py`（目录同步 + 部署编排）、`tests/deploy/`。
- 修改：`ct/config.py`（DeployConfig）、`ct/app/export.py`（DeployStep 入默认管道）、`ct/cli.py`（无变化分支、`ct deploy`、`--for-build`）、`ct/web/tasks.py`（步骤列表加 Deploy）、`ct/web/app.py`（workspace API deploy 摘要）、web 前端（工作区信息区展示）。
- 文档：ct-tool `README.md`、`docs/web-panel.md`。
- 打包：重新构建 launcher（mac/win），供 fabulous-game 仓库更新 `Config/launcher-apps/`。
- 不改变导出产物格式、schema 语义与既有命令行为。
