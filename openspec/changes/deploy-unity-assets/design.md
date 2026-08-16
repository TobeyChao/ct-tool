## Context

现有架构（参见 proposal.md - Why）：`ExportPipeline` 步骤管道（ParseValidate → I18nSync → Json → Fbs → Flatc → Accessor → Bundle），`GlobalConfig`（pydantic，`config/global.yaml`，路径相对 `project_root` 解析），事件 `ProgressReporter`/`CancelToken` 统一驱动 CLI 与 web，`ExportPipeline(steps=[...])` 构造时注入步骤列表。导出成功后 `save_cache` 才提交缓存。web 面板的导出进度由 `ExportTaskState.steps`（硬编码列表）驱动前端渲染；launcher 概览页不显示导出进度（导出去 web 面板）。deploy 需要在不破坏上述架构的前提下，把产物分发到 Unity 工程 Assets。

## Goals / Non-Goals

**Goals:**
- 导出即同步：任何入口（CLI / web / launcher）导表后，产物自动落到 Unity Assets 三处（binary→`Assets/Content/Config`、csharp→`Assets/Scripts/Config/Gen`、lua→`Assets/Scripts/Lua/Config/Gen`）。
- 配置化与可降级：deploy 目标映射可配置；未配置/未启用时导表行为完全不变。
- 失败可感知：部署失败即报错，绝不静默。
- 可见性：web 面板与 CLI 能一眼看到 deploy 配置状态与目标路径。

**Non-Goals:**
- 不做 git 操作（提交/拉取由用户/外部流程负责）。
- 不改变导出产物格式、schema 语义、i18n 行为。
- 不在 launcher 设置页做 deploy 配置 UI（配置在 global.yaml，web 面板已展示，避免双份维护）。
- 不做跨平台脚本分发（deploy 是 Python 逻辑，随 ct 打包，天然跨平台）。

## Decisions

1. **命名 `deploy` 而非 `sync`**：项目内 "sync" 已被 i18n 占用（`i18n sync`、`I18nSyncStep`），复用会语义冲突。`deploy` 表达"分发产物"。
   - 替代：`distribute`/`publish` —— 均可，但 `deploy` 与既有 `export` 对仗最自然。

2. **`DeployStep` 挂默认管道末尾**（Bundle 之后）：`ExportPipeline(steps=[...])` 本身就是注入式设计，加一步是既有模式的正常用法；CLI、web、launcher 三个入口全部自动获得 deploy，无需各入口单独接线。
   - 替代：独立命令 + 各入口手动调用 —— 会漏（web/launcher 不易加钩子），且产生"导了没部署"窗口。

3. **targets 配置化**（`DeployConfig` pydantic 子模型）：`enabled`/`unity_project`/`targets`/`build_targets` 全部带默认值（`enabled=False`、空列表），旧配置与既有测试零影响。
   - 路径语义（必须写死）：`source` 相对 `project_root`（与现有 `resolve()` 一致）；`dest` 相对 **`unity_project`**（Unity 工程根）。例如 `source: output/binary` → `dest: Assets/Content/Config` 解析为 `<unity_project>/Assets/Content/Config`。
   - 替代：代码写死三处映射 —— 不灵活；加 StreamingAssets 或换目录要改代码。

4. **目录同步三态 + meta 保护**：目标与产物严格一致（新增/覆盖/删除多余）；仍存在文件的 `.meta` 一律不动（入库 meta 的 GUID 稳定），删除文件连带删同名 `.meta`（成对清理）；bin 纯覆盖、不碰 meta。
   - 替代：整目录 `rm` 再拷 —— 会连 `.meta` 一起毁掉，GUID 全变、git diff 噪音。
   - 实现：`sync_dir(src, dst)` 单函数，win/mac 同一 Python 实现（`shutil` + 枚举），不用 rsync（跨平台依赖）。

5. **失败即报错，且不提交缓存**：`DeployStep.run` 抛异常 → 管道终止 → `save_cache` 不执行（现有机制天然满足）；CLI 非 0 退出，web 任务置 error 并显示。
   - 替代：警告继续 —— 会出现"导出成功但 Assets 没更新"的静默窗口，违背目标。

6. **"所有表均无变化"分支仍执行部署**：cli.py 现有的提前 `return` 会连部署一起跳过（fresh clone 后 excel 未变但 Assets 无产物）。改为：跳过导出、执行 deploy（日志"所有表均无变化，仅部署"）。
   - 复用同一 `deploy()`，不另写逻辑。

7. **可见性**：
   - `/api/workspace` 的 `config` 增加 `deploy` 摘要（绝对路径，前端只渲染）；web 工作区信息区加一行"部署目录"。
   - `ct status` 输出一行 deploy 状态（启用 + 目标绝对路径 / 未配置）。
   - launcher 不做（见 Non-Goals）。

8. **平台**：deploy 是纯 Python（`ct/export/deploy.py`），PyInstaller `collect_submodules("ct")` 自动打包，无需平台分支；launcher 重新构建即可。

## Risks / Trade-offs

- [deploy 目标路径写错（相对/绝对混淆）] → 路径语义在 DeployConfig 文档写死；`ct status` 与 web 面板显示解析后的绝对路径，一眼可查。
- [目标目录被用户手动改过，同步删除误删文件] → `sync_dir` 只管理产物文件（按 `targets.source` 的清单），删除仅限清单内文件；文档提示 Assets 生成物目录由工具管理。
- [远程/CI 上跑 web 面板时 Unity 路径不可达] → `enabled` 默认 false；需部署的机器显式配置。
- [增量导出缓存未变但 Assets 缺文件] → 无变化分支仍部署 + 钩子侧缺失检测（fabulous-game 侧 change 负责）。
- [launcher 未更新导致旧 ct 无 deploy] → 发布顺序：ct-tool 先出包，fabulous-game 再更新 `Config/launcher-apps/` 并配置。

## Migration Plan

1. ct-tool 实现并测试 deploy（含打包脚本验证）。
2. 重新构建 launcher（mac app / win exe）。
3. fabulous-game 仓库更新 `Config/launcher-apps/`，在 `Config/gd/config/global.yaml` 配置 `deploy:`。
4. 实际导表一次，验证 Assets 三处更新、git 无二进制 diff、web/status 显示正常。
5. 回滚：删除 `deploy:` 配置即可回到"只导出不部署"（enabled=false），无需代码回滚。

## Open Questions

无（配置形态、失败语义、可见性、无变化行为均已决策）。
