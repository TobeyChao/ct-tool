## Context

现有架构（参见 proposal.md - Why）：导出实现在 `ct/src/ct/app/canonical_export.py` 的 `run_canonical_export()`，进度按**固定阶段元组** `CANONICAL_STEPS = ("解析校验", "JSON", "Accessor", "FBS", "Bundle")` 上报 —— **没有 Flatc 步骤**（`.fbs` 文本由 `ct/src/ct/export/canonical_fbs.py` 直接产出），**也没有 `ExportTaskState.steps`**（web 面板用的是 `CanonicalExportTask.export_steps`，实现就是 `return list(CANONICAL_STEPS)`）。`GlobalConfig`（pydantic，`config/global.yaml`，路径相对 `project_root` 解析），事件 `ProgressReporter`/`CancelToken` 统一驱动 CLI 与 web。`ct export` **每次都全量重建**（没有增量跳过分支），成功后 CLI 才在导出之后另行调用 `_run_deploy()`、再调 `persist_export_state()` 提交缓存指纹；**web 面板只导出、从不部署**（`ct/src/ct/web/app.py` 的 `deploy.targets` 恒为 `[]`）。deploy 需要在不破坏上述架构的前提下，把产物分发到 Unity 工程 Assets。

## Goals / Non-Goals

**Goals:**
- 导出即同步：~~任何入口（CLI / web / launcher）导表后，产物自动落到 Unity Assets 三处~~ ⚠️ **未实现** —— 实际只有 **CLI 路径**在 `ct export` 之后调用 `_run_deploy()`（`ct/src/ct/cli.py`）；**web 面板从不部署**，launcher 的导出入口同样不经 `_run_deploy()`。产物落点为 binary→`Assets/Content/Config`、csharp→`Assets/Scripts/Config/Gen`、lua→`Assets/Scripts/Lua/Config/Gen`。
- 配置化与可降级：deploy 目标映射可配置；未配置/未启用时导表行为完全不变。
- 失败可感知：部署失败即报错，绝不静默。
- 可见性：web 面板与 CLI 能一眼看到 deploy 配置状态与目标路径。⚠️ **未实现** —— `ct status` 无 deploy 输出（只有 `missing`/`changed`/`drifted`），`/api/workspace` 的 `deploy.targets` 恒为 `[]`，web 前端无「部署目录」行（见 Decisions 7）。

**Non-Goals:**
- 不做 git 操作（提交/拉取由用户/外部流程负责）。
- 不改变导出产物格式、schema 语义、i18n 行为。
- 不在 launcher 设置页做 deploy 配置 UI（配置在 global.yaml，web 面板已展示，避免双份维护）。
- 不做跨平台脚本分发（deploy 是 Python 逻辑，随 ct 打包，天然跨平台）。

## Decisions

1. **命名 `deploy` 而非 `sync`**：项目内 "sync" 已被 i18n 占用（`i18n sync`、`I18nSyncStep`），复用会语义冲突。`deploy` 表达"分发产物"。
   - 替代：`distribute`/`publish` —— 均可，但 `deploy` 与既有 `export` 对仗最自然。

2. ~~**`DeployStep` 挂默认管道末尾**（Bundle 之后）~~ ⚠️ **未实现且方案已改**：没有 `DeployStep`，`ExportPipeline` 这个类也已不存在。**实际做法**是 CLI 在 `run_canonical_export()` 返回后调用 `_run_deploy(root, for_build)`（`ct/src/ct/cli.py:109`），`ct deploy` 子命令复用同一个 `_run_deploy()`。**代价**：CLI 之外的入口（web / launcher）**不会自动部署** —— 这正是本 change 不能按原描述归档的原因。
   - 替代：独立命令 + 各入口手动调用 —— 会漏（web/launcher 不易加钩子），且产生"导了没部署"窗口。（按现状看，这个替代方案其实就是已落地的形态。）

3. **targets 配置化**（`DeployConfig` pydantic 子模型）：`enabled`/`unity_project`/`targets`/`build_targets` 全部带默认值（`enabled=False`、空列表），旧配置与既有测试零影响。
   - 路径语义（必须写死）：`source` 相对 `project_root`（与现有 `resolve()` 一致）；`dest` 相对 **`unity_project`**（Unity 工程根）。例如 `source: output/binary` → `dest: Assets/Content/Config` 解析为 `<unity_project>/Assets/Content/Config`。
   - 替代：代码写死三处映射 —— 不灵活；加 StreamingAssets 或换目录要改代码。

4. **目录同步三态 + meta 保护**：目标与产物严格一致（新增/覆盖/删除多余）；仍存在文件的 `.meta` 一律不动（入库 meta 的 GUID 稳定），删除文件连带删同名 `.meta`（成对清理）；bin 纯覆盖、不碰 meta。
   - 替代：整目录 `rm` 再拷 —— 会连 `.meta` 一起毁掉，GUID 全变、git diff 噪音。
   - 实现：`sync_dir(src, dst)` 单函数，win/mac 同一 Python 实现（`shutil` + 枚举），不用 rsync（跨平台依赖）。

5. **失败即报错，且不提交缓存**：实际链路是 CLI 在导出后调用 `_run_deploy()`，它捕获 `FileNotFoundError`/`OSError` → 打印 `[deploy error]` 并以 `typer.Exit(1)` 退出；`persist_export_state()` 排在 `_run_deploy()` **之后**（`ct/src/ct/cli.py:109-113`），所以部署失败时缓存指纹不提交。⚠️ 没有 `DeployStep.run`，也没有"管道终止"；且 web 路径根本没有 deploy，故"web 任务置 error 并显示"不适用。
   - 替代：警告继续 —— 会出现"导出成功但 Assets 没更新"的静默窗口，违背目标。

6. ~~**"所有表均无变化"分支仍执行部署**~~ ⚠️ **不适用（该分支不存在，也无需存在）**：`ct export` 现在**每次都全量重建**，CLI 里**没有**"所有表均无变化"的提前 `return`，也不打"仅部署"日志；每次导出后都会执行 `_run_deploy()`，fresh clone 场景自然覆盖。
   - 复用同一 `deploy()`，不另写逻辑。

7. **可见性** ⚠️ **大部分未实现**：
   - `/api/workspace` 的 `config.deploy` 只返回 `enabled` 与 `unity_project`；**`targets` 恒为 `[]`**（不是"目标绝对路径摘要"），web 前端也**没有**"部署目录"行。
   - `ct status` **不输出任何 deploy 信息**；其输出只有 `missing` / `changed` / `drifted` 三类。
   - launcher 不做（见 Non-Goals）。
   - ⇒ 这些未完成项已回写 `tasks.md` 并重新置为 `[ ]`。

8. **平台**：deploy 是纯 Python（`ct/src/ct/export/deploy.py`），PyInstaller `collect_submodules("ct")` 自动打包，无需平台分支；launcher 重新构建即可。

## Risks / Trade-offs

- [deploy 目标路径写错（相对/绝对混淆）] → 路径语义在 `DeployConfig` 与 `ct/docs/README.md`「部署到 Unity」里写死（含 `source`/`dest`/`unity_project` 各自的解析基准）。⚠️ 原计划的「`ct status` 与 web 面板显示解析后的绝对路径」**未实现**，当前没有一眼可查的出口。
- [目标目录被用户手动改过，同步删除误删文件] → `sync_dir` 只管理产物文件（按 `targets.source` 的清单），删除仅限清单内文件；文档提示 Assets 生成物目录由工具管理。
- [远程/CI 上跑 web 面板时 Unity 路径不可达] → `enabled` 默认 false；需部署的机器显式配置。web 面板本身也不部署，天然不受影响。
- [导出产物变了但 Assets 缺文件] → `ct export` 每次全量重建且 CLI 每次导出后都执行 `_run_deploy()`，因此不存在"跳过导出就漏部署"的窗口（⚠️ 原写的"无变化分支仍部署"不成立——没有该分支）；web 路径不部署，缺文件由 fabulous-game 侧钩子/缺失检测负责。
- [launcher 未更新导致旧 ct 无 deploy] → 发布顺序：ct-tool 先出包，fabulous-game 再更新 `Config/launcher-apps/` 并配置。

## Migration Plan

1. ct-tool 实现并测试 deploy（含打包脚本验证）。
2. 重新构建 launcher（mac app / win exe）。
3. fabulous-game 仓库更新 `Config/launcher-apps/`，在 `Config/gd/config/global.yaml` 配置 `deploy:`。
4. 实际导表一次，验证 Assets 三处更新、git 无二进制 diff。⚠️ 原写的"web/status 显示正常"**不具备验收条件**——web API 不回 targets、`ct status` 无 deploy 输出（见 Decisions 7）。
5. 回滚：删除 `deploy:` 配置即可回到"只导出不部署"（enabled=false），无需代码回滚。

## ⚠️ 归档前必须处理（2026-09-12 复核）

本 change 的 requirements（`specs/unity-deploy/spec.md`）里关于 **`ct status` 打印 deploy 状态行 + 目标绝对路径**、
**web 面板展示 deploy 状态**、**导出进度含 Deploy 步骤**的条款**均未实现**。这些 requirement 文本保留，
但在 `spec.md` 中已逐条标注 **⚠️ 未实现**；对应 `tasks.md` 条目已重新置为 `[ ]`。归档前要么补齐实现，
要么把这几条 requirement 拆到后续 change 并从本 change 的 delta 中移除。

## Open Questions

无（配置形态、失败语义、可见性、无变化行为均已决策）。
