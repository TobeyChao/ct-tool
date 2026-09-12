## Why

改表后 `ct export` 只产出到 `gd/output/`，Unity 工程的 Assets（`Content/Config` 二进制、`Scripts/Config/Gen` 代码、`Scripts/Lua/Config/Gen` 代码）不会自动更新，运行/打包前极易用到旧数据；同时二进制产物入库带来无意义的 diff。需要把"导表"与"同步到 Unity"合并为一步，且配置可见、失败可感知。

## What Changes

> ⚠️ **实现现状（2026-09-12 复核，与本节描述有出入 —— 本 change 尚不具备归档条件）**：
> `tasks.md` 曾被整片勾成 `[x]`，但下列条目**并未实现**：
> - 代码里**没有 `DeployStep`**，默认管道里也**没有** deploy 步骤。部署是 CLI 路径上 `ct export`
>   之后的独立调用 `_run_deploy()`（`ct/src/ct/cli.py`）。
> - **web 路径从不部署**：`/api/workspace` 的 `deploy.targets` 恒为 `[]`，web 前端没有「部署目录」行，
>   导出进度 steps 里也没有 "Deploy"（`CanonicalExportTask.export_steps` 就是 `CANONICAL_STEPS`）。
> - `ct status` **不打印任何 deploy 信息**，其输出只有 `missing` / `changed` / `drifted` 三类。
> - 逐条勘误见 `design.md` 与 `tasks.md` 的 ⚠️ 标注。

- **新增 deploy 配置**（`config/global.yaml` 的 `deploy:` section）：`enabled`、`unity_project`（相对 project_root 或绝对路径）、`targets`（source→dest 映射）、`build_targets`（`--for-build` 时追加）。所有字段带默认值，未配置/未启用时导表行为不变。
- **导出自动部署**（⚠️ 未实现为 `DeployStep`；实际：CLI 导出后由 `_run_deploy()` 同步，web 路径不部署）：`ExportPipeline` 末尾新增 `DeployStep`——导表成功后按 targets 同步产物到 Unity Assets；"所有表均无变化"时跳过导出但仍执行部署（⚠️ 该分支也不存在，`ct export` 每次都全量重建）。
- **目录同步语义**：目标目录与产物严格一致（新增/覆盖/删除多余文件）；`.meta` 保护——仍存在文件的 meta 不动，删除文件连带删同名 `.meta`；bin 纯覆盖。
- **失败即报错**：deploy 任一步失败，`ct export` 以非 0 退出；部署失败不提交缓存。
- **新增 `ct deploy` 子命令**：只部署不导出，与管道共用同一逻辑。
- **`--for-build`**：`export`/`deploy` 追加构建目标（如 `Assets/StreamingAssets/Config`）。
- **可见性**（⚠️ 未实现：web API 的 `deploy.targets` 恒为 `[]`、前端无「部署目录」行、`ct status` 无 deploy 输出）：web 面板工作区信息区显示 deploy 摘要（启用状态与目标绝对路径）；web 导出进度加 "Deploy" 步骤；`ct status` 输出 deploy 状态。
- 未配置 deploy 的项目行为完全不变（默认跳过）。

## Capabilities

### New Capabilities
- `unity-deploy`: 把导出产物分发到 Unity 工程 Assets 的能力——配置、自动部署、构建目标、可见性与失败语义。

### Modified Capabilities
- 无（既有 CLI/web/i18n 行为不变，deploy 是新增能力）。

## Impact

- 新增：`ct/src/ct/export/deploy.py`（目录同步 + 部署编排）、`tests/deploy/`。
- 修改：`ct/src/ct/config.py`（`DeployConfig`）、`ct/src/ct/cli.py`（导出后 `_run_deploy()`、`ct deploy`、`--for-build`；⚠️ 无「所有表均无变化」分支——`ct export` 每次都全量重建）、`ct/src/ct/web/app.py`（workspace API 只回 `enabled`/`unity_project`；⚠️ `deploy.targets` 恒为 `[]`）。
- ⚠️ **未修改**：`ct/app/export.py`（已不存在）、`ct/web/tasks.py`（步骤列表未加 Deploy）、web 前端（无「部署目录」行）。
- 文档：ct-tool 根 `README.md`、`ct/docs/README.md`（手册；⚠️ `ct/docs/web-panel.md` **不存在**）。
- 打包：重新构建 launcher（mac/win），供 fabulous-game 仓库更新 `Config/launcher-apps/`。
- 不改变导出产物格式、schema 语义与既有命令行为。
