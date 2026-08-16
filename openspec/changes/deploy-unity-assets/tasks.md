## 1. 配置层

- [x] 1.1 在 `ct/config.py` 新增 `DeployConfig` pydantic 子模型（enabled/unity_project/targets/build_targets，全部带默认值：enabled=False、空列表）
- [x] 1.2 `GlobalConfig` 集成 deploy 字段，并提供路径解析：source 相对 project_root、dest 相对 unity_project（`resolve_deploy_target()`）
- [ ] 1.3 在 ct-tool 文档与示例中给出 global.yaml 的 deploy section 配置模板（含注释说明路径语义）

## 2. 部署核心

- [x] 2.1 新增 `ct/export/deploy.py`：`sync_dir(src, dst)` 实现目录同步三态（新增/覆盖/删除多余）+ meta 保护（存在文件 meta 不动、删除文件连带删同名 meta、bin 不管理 meta）
- [x] 2.2 实现 `deploy(...)`：按 targets 逐个同步、`--for-build` 追加 build_targets、未配置/未启用时跳过、输出同步日志（reporter.log）
- [x] 2.3 新增 `DeployStep`（name="Deploy"），加入 `ExportPipeline` 默认 steps 末尾（Bundle 之后）；失败抛异常使导出中止

## 3. CLI

- [x] 3.1 修改 `export` 的"所有表均无变化"分支：跳过导出但仍执行部署，日志注明"仅部署"
- [x] 3.2 新增 `ct deploy` 子命令（只部署不导出），与管道共用同一 deploy 逻辑
- [x] 3.3 `export`/`deploy` 增加 `--for-build` 选项，追加 build_targets
- [x] 3.4 `ct status` 输出 deploy 状态行（启用 + 目标绝对路径 / 未配置）

## 4. Web 集成

- [x] 4.1 `/api/workspace` 的 config 返回 deploy 摘要（enabled、unity_project、targets 的绝对路径；未配置返回空）
- [x] 4.2 `ct/web/tasks.py` 的 `ExportTaskState.steps` 追加 "Deploy"
- [x] 4.3 web 前端工作区信息区新增"部署目录"行（未配置显示"未配置"），复用 workspace API 数据

## 5. 测试

- [x] 5.1 `tests/deploy/`：目录同步三态 + meta 保护（存在文件 meta 不动、删除文件连带 meta）
- [x] 5.2 `tests/deploy/`：未配置跳过、目标不可写失败报错（非 0 且缓存不提交）、重复部署幂等
- [x] 5.3 `tests/cli/`：`ct deploy` 独立命令、`--for-build` 追加构建目标、"无变化仅部署"输出
- [x] 5.4 `tests/web/`：workspace API 含 deploy 字段、导出进度 steps 含 Deploy
- [x] 5.5 运行全量测试回归（既有 cli/app/web 测试应全绿）

## 6. 打包与文档

- [x] 6.1 更新 ct-tool 根 README（deploy 配置、`ct deploy`、`--for-build` 用法）
- [x] 6.2 更新 `ct/docs/web-panel.md`（部署摘要展示、导出自动带部署）
- [x] 6.3 重新构建 launcher（mac app 已完成并验证带 deploy；win exe 需 Windows 机器执行 `launcher/tool/build_windows.ps1`，本机无法构建），确认产物可替换 fabulous-game 的 `Config/launcher-apps/`
