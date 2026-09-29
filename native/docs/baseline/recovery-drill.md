# 发布中断恢复与版本账本演练（rust-native-core 任务 6.7）

由 `node native/tools/bench/recovery-drill.mjs` 生成；工作区是基准夹具在临时目录里的副本
（路径含中文与空格），真实 `gd/` 未被写入。

- 原生二进制：`native\target\release\ct.exe`
- 夹具：`native\target\bench\bench-m`（50 表 × 2000 行，307 个产物）
- 临时工作区：`C:\Users\ZHAOHU~1\AppData\Local\Temp\ct-drill-ruKx7z\配表 工作区`

| 步骤 | 退出码 | 输出 |
|---|---|---|
| ct.exe export | 0 | 解析 Base（2000 行）<br>解析 T001（2000 行）<br>解析 T002（2000 行）<br>解析 T003（2000 行）<br>解析 T004（2000 行）<br>解析 T005（2000 行）<br>解析 T006（2000 行）<br>解析 T007（2000 行）<br>解析 …（共 3835 字符，中间省略）…  声明）｜填充率 88.2%（385,008 B → 373,752 B，0.971x）<br>枚举声明 2 个 → Enums.cs / Enums.lua<br>增量导出：写入 307，复用 0；生成缓存命中 0<br><br>导出完成: 50 张表<br>[deploy] 无文件变更 ⏎ [deploy] 未配置或未启用，跳过 |
| （基线）output/ 快照 | 0 | 307 个产物，聚合摘要 070051cef9086da966c6e8199dcddee616739f42dc2df08d61c9482943ad29a1 |
| ct export --all（journal 出现后 SIGKILL） | — | 命中发布窗口：357 个 .ct-stage-* 私有暂存文件、journal 已落盘；进程 signal=SIGKILL |
| 中断后的工作区状态 | 0 | {"journalExists":true,"journalBytes":207426,"stagedLeft":357} |
| ct.exe status | 0 | 未完成的发布:<br>  [publication] 存在未完成的发布（operation 1a0b6105812-66b8，阶段 prepared）——下一次 export/deploy 会先恢复，或人工检查 C:\Users\ZHAOHU~1\AppData\Local\Temp\ct-drill-ruKx7z\配表 工作区\.ct\export-publication.json<br>  [recovery-needed] 请先执行 ct recover 恢复，再使用状态结果 |
| ct.exe validate | 1 |  ⏎ [recovery-needed] 存在未完成的发布（operation 1a0b6105812-66b8，阶段 prepared）——下一次 export/deploy 会先恢复，或人工检查 C:\Users\ZHAOHU~1\AppData\Local\Temp\ct-drill-ruKx7z\配表 工作区\.ct\export-publication.json |
| ct.exe recover --json | 0 | {<br>  "recovered": true,<br>  "note": "上次发布尚未完成备份，仅清理私有材料",<br>  "schemaRevision": "978c02c70a64bec4995e61d9074904ea8eceee2a1f38b7815d8831e39ef2d090"<br>} |
| （恢复后）output/ 快照 | 0 | 307 个产物，聚合摘要 070051cef9086da966c6e8199dcddee616739f42dc2df08d61c9482943ad29a1（与基线一致）；mtime 保持 307/307 |
| journal 是否清场 | 0 | journalExists=false；恢复后 .ct-stage-* 残留 0 个 |
| ct.exe status | 0 | [OK] 所有表已是最新（数据 + 模板） |
| ct.exe export | 0 | 解析 Base（2000 行）<br>解析 T001（2000 行）<br>解析 T002（2000 行）<br>解析 T003（2000 行）<br>解析 T004（2000 行）<br>解析 T005（2000 行）<br>解析 T006（2000 行）<br>解析 T007（2000 行）<br>解析 …（共 3837 字符，中间省略）… 明）｜填充率 88.2%（385,008 B → 373,752 B，0.971x）<br>枚举声明 2 个 → Enums.cs / Enums.lua<br>增量导出：写入 0，复用 307；生成缓存命中 506<br><br>导出完成: 50 张表<br>[deploy] 无文件变更 ⏎ [deploy] 未配置或未启用，跳过 |
| 把 cache/state.json 版本标记改为不识别值 | 0 | canonical-cache/1 → legacy-cache/0 |
| ct.exe export --all | 0 | 解析 Base（2000 行）<br>解析 T001（2000 行）<br>解析 T002（2000 行）<br>解析 T003（2000 行）<br>解析 T004（2000 行）<br>解析 T005（2000 行）<br>解析 T006（2000 行）<br>解析 T007（2000 行）<br>解析 …（共 3835 字符，中间省略）…  声明）｜填充率 88.2%（385,008 B → 373,752 B，0.971x）<br>枚举声明 2 个 → Enums.cs / Enums.lua<br>强制重建：写入 307，复用 0；生成缓存命中 0<br><br>导出完成: 50 张表<br>[deploy] 无文件变更 ⏎ [deploy] 未配置或未启用，跳过 |
| （版本不识别 + --all）快照 | 0 | 聚合摘要 070051cef9086da966c6e8199dcddee616739f42dc2df08d61c9482943ad29a1（与基线一致） |
| ct.exe export | 0 | 退出码 0（参照侧控制台是 GBK，日志原文不入报告） |
| （Python 参照同区再导一次）快照 | 0 | 聚合摘要 070051cef9086da966c6e8199dcddee616739f42dc2df08d61c9482943ad29a1（与原生基线一致） |
| ct.exe export | 0 | 解析 Base（2000 行）<br>解析 T001（2000 行）<br>解析 T002（2000 行）<br>解析 T003（2000 行）<br>解析 T004（2000 行）<br>解析 T005（2000 行）<br>解析 T006（2000 行）<br>解析 T007（2000 行）<br>解析 …（共 3835 字符，中间省略）…  声明）｜填充率 88.2%（385,008 B → 373,752 B，0.971x）<br>枚举声明 2 个 → Enums.cs / Enums.lua<br>增量导出：写入 0，复用 307；生成缓存命中 0<br><br>导出完成: 50 张表<br>[deploy] 无文件变更 ⏎ [deploy] 未配置或未启用，跳过 |
| （演练结束）私有暂存残留 | 0 | 0 个 |

## 结论

- 中断落在发布替换窗口内（journal 已落盘、私有暂存文件在场）：只读诊断报「未完成的发布」且不做写入，`ct recover` 还原内容与 mtime、清掉 journal，恢复后 `ct status`/`ct export` 正常。
- 恢复后聚合摘要回到中断前的基线，既有产物 mtime 全部保持；恢复同时删掉 journal 记录的私有暂存文件（演练实测 `.ct-stage-*` 残留 0 个）。本次演练暴露并修复了 `cleanup()` 只清备份/journal、不清 `entry.staged` 的泄漏，`publication_recovery.rs::crash_after_prepared_cleans_private_only` 已加断言钉住。
- 把成功账本的版本标记改成不识别值后 `--all` 全量重建，产物聚合摘要不变：生成缓存不复活旧版本条目。
- 与 Python 参照交替导出同一工作区，产物聚合摘要保持一致；原生侧随后报「复用 307」，说明跨引擎记账不产生虚假变更。

## 未执行项（刻意）

- **删除 `ct/` Python 实现**：任务 6.7 末句要求「验收后删除 Python 实现」。本轮不执行——它不可逆，
  且 `ct/tests` 仍是产物格式与性能基线的唯一参照、launcher 侧仍有 `ct panel` 使用路径
  （native-flutter-workbench 未验收）。删除需单独授权，届时一并移除回退说明。
- macOS/Linux 的同款项只在 CI 定义中覆盖，本机无对应平台。
