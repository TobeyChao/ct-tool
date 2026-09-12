> ⚠️ **状态校正（2026-09-12 复核）**：本文件此前被整片勾成 `[x]`，但 2.3 / 3.1 / 3.4 / 4.1 / 4.2 / 4.3 / 5.4
> **并未实现**（或前提不存在），已重新置为 `[ ]` 并逐条注明实情。**本 change 目前不具备归档条件**，
> 详见 `design.md` 末尾「⚠️ 归档前必须处理」与 `specs/unity-deploy/spec.md` 的逐条标注。

## 1. 配置层

- [x] 1.1 在 `ct/src/ct/config.py` 新增 `DeployConfig` pydantic 子模型（enabled/unity_project/targets/build_targets，全部带默认值：enabled=False、空列表）
- [x] 1.2 `GlobalConfig` 集成 deploy 字段，并提供路径解析：source 相对 project_root、dest 相对 unity_project（`resolve_deploy_targets()`）；`unity_project` 自身相对 project_root 或绝对路径
- [x] 1.3 在 ct-tool 文档与示例中给出 global.yaml 的 deploy section 配置模板（含注释说明路径语义）
  - `ct/docs/README.md`「部署到 Unity」：模板 + 路径语义表（`unity_project` 相对**工作区根**、`source` 相对**工作区根**、`dest` 相对 **`unity_project`**），并写明 `enabled: false`/整段缺省时行为与引入前完全一致、`build_targets` 只在 `--for-build` 时追加
  - `gd/config/global.yaml`：新增**整段注释掉**的示例 `deploy:` 块（可发现但不改变样例工作区行为）

## 2. 部署核心

- [x] 2.1 新增 `ct/src/ct/export/deploy.py`：`sync_dir(src, dst, reporter)` 实现目录同步三态（新增/覆盖/删除多余）+ meta 保护（存在文件 meta 不动、删除文件连带删同名 meta、bin 不管理 meta）
- [x] 2.2 实现 `deploy(config, for_build, reporter)`：按 targets 逐个同步、`--for-build` 追加 build_targets、未配置/未启用时跳过、输出同步日志（reporter.log）
- [ ] 2.3 ⚠️ **未实现 —— 重新打开**：~~新增 `DeployStep`（name="Deploy"），加入 `ExportPipeline` 默认 steps 末尾（Bundle 之后）；失败抛异常使导出中止~~
  - 实情：代码里**没有 `DeployStep`**，`ExportPipeline` 这个类也已不存在。部署是 CLI 在 `run_canonical_export()` 返回后调用 `_run_deploy()`（`ct/src/ct/cli.py`）触发的，**web / launcher 入口不会部署**。

## 3. CLI

- [ ] 3.1 ⚠️ **前提不存在 —— 重新打开**：~~修改 `export` 的"所有表均无变化"分支：跳过导出但仍执行部署，日志注明"仅部署"~~
  - 实情：`ct export` **每次都全量重建**（无增量跳过），CLI 里没有"所有表均无变化"的提前返回分支，也没有该日志。`ct/tests/deploy/test_deploy.py::test_no_changes_still_deploys` 实际验证的是"重新全量导出后目标被重新部署"，**不是**跳过导出。
- [x] 3.2 新增 `ct deploy` 子命令（只部署不导出），与 `_run_deploy()` 共用同一 deploy 逻辑
- [x] 3.3 `export`/`deploy` 增加 `--for-build` 选项，追加 build_targets
- [ ] 3.4 ⚠️ **未实现 —— 重新打开**：~~`ct status` 输出 deploy 状态行（启用 + 目标绝对路径 / 未配置）~~
  - 实情：`ct status` 只打印 `missing` / `changed` / `drifted` 三类，**不含任何 deploy 信息，也没有目标路径**。

## 4. Web 集成

- [ ] 4.1 ⚠️ **部分实现 —— 重新打开**：~~`/api/workspace` 的 config 返回 deploy 摘要（enabled、unity_project、targets 的绝对路径；未配置返回空）~~
  - 实情：`ct/src/ct/web/app.py` 只返回 `enabled` 与 `unity_project`；**`deploy.targets` 恒为 `[]`**（未解析绝对路径）。
- [ ] 4.2 ⚠️ **未实现 —— 重新打开**：~~`ct/web/tasks.py` 的 `ExportTaskState.steps` 追加 "Deploy"~~
  - 实情：**没有 `ExportTaskState`**；`CanonicalExportTask.export_steps` 直接 `return list(CANONICAL_STEPS)`，其中不含 Deploy。
- [ ] 4.3 ⚠️ **未实现 —— 重新打开**：~~web 前端工作区信息区新增"部署目录"行（未配置显示"未配置"），复用 workspace API 数据~~
  - 实情：`ct/src/ct/web/static/js/` 中没有任何 deploy 渲染代码。

## 5. 测试

- [x] 5.1 `ct/tests/deploy/`：目录同步三态 + meta 保护（存在文件 meta 不动、删除文件连带 meta）
- [x] 5.2 `ct/tests/deploy/`：未配置跳过、目标不可写失败报错（非 0 且缓存不提交）、重复部署幂等
- [x] 5.3 CLI 路径测试并入 `ct/tests/deploy/test_deploy.py`（仓库没有 `ct/tests/cli/`）：`ct deploy` 独立命令、`--for-build` 追加构建目标、"无变化"场景仍部署（⚠️ 经**全量重建**路径覆盖，不是"跳过导出"分支）
- [ ] 5.4 ⚠️ **未实现 —— 重新打开**：~~`ct/tests/web/`：workspace API 含 deploy 字段、导出进度 steps 含 Deploy~~
  - 实情：`ct/tests/web/` 中没有任何 deploy 断言。
- [x] 5.5 运行全量测试回归（既有 cli/app/web 测试应全绿）

## 6. 打包与文档

- [x] 6.1 更新 ct-tool 根 `README.md`（deploy 配置、`ct deploy`、`--for-build` 用法）
- [x] 6.2 更新手册 `ct/docs/README.md`（部署配置与路径语义、导出自动带部署 ⚠️ 仅 CLI 路径）—— 原任务写的 `ct/docs/web-panel.md` **不存在**
- [x] 6.3 重新构建 launcher（mac app 已完成并验证带 deploy；win exe 需 Windows 机器执行 `launcher/tool/build_windows.ps1`，本机无法构建），确认产物可替换 fabulous-game 的 `Config/launcher-apps/`
