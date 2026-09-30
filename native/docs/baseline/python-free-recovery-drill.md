# 发布中断恢复与版本账本演练（rust-native-core 任务 6.7）

由 `node native/tools/bench/recovery-drill.mjs` 生成；工作区是基准夹具在临时目录里的副本
（路径含中文与空格），真实 `gd/` 未被写入。

- 原生二进制：`native/target/release/ct`
- 夹具：`../../../../../tmp/ct-native-g3-Zj4oHA/bench-m`
- 临时工作区：`/var/folders/44/g9chsr856qg5kkv0bnx8gmqc0000gn/T/ct-drill-KrAOJH/配表 工作区`

| 步骤 | 退出码 | 输出 |
|---|---|---|
| ct export | 0 | 解析 Base（2000 行）<br>解析 T001（2000 行）<br>解析 T002（2000 行）<br>解析 T003（2000 行）<br>解析 T004（2000 行）<br>解析 T005（2000 行）<br>解析 T006（2000 行）<br>解析 T007（2000 行）<br>解析 …（共 3835 字符，中间省略）…  声明）｜填充率 88.0%（386,808 B → 373,616 B，0.966x）<br>枚举声明 2 个 → Enums.cs / Enums.lua<br>增量导出：写入 307，复用 0；生成缓存命中 0<br><br>导出完成: 50 张表<br>[deploy] 无文件变更 ⏎ [deploy] 未配置或未启用，跳过 |
| （基线）output/ 快照 | 0 | 307 个产物，聚合摘要 f3ee3cf5ab295147414f5a0bd6bdacf3560a6d804b525e19f84326166684e749 |
| ct export --all (journal window SIGKILL) | 0 | {"killed":{"phase":"prepared","stagedFiles":357},"code":null,"signal":"SIGKILL"} |
| 中断后的工作区状态 | 0 | {"journalExists":true,"journalBytes":214542,"stagedLeft":357} |
| ct status | 1 |  ⏎ [recovery-needed] 存在未完成的发布（operation 1a0f026606b-1423b，阶段 prepared）——下一次 export/deploy 会先恢复，或人工检查 /private/var/folders/44/g9chsr856qg5kkv0bnx8gmqc0000gn/T/ct-drill-KrAOJH/配表 工作区/.ct/export-publication.json |
| ct validate | 1 |  ⏎ [recovery-needed] 存在未完成的发布（operation 1a0f026606b-1423b，阶段 prepared）——下一次 export/deploy 会先恢复，或人工检查 /private/var/folders/44/g9chsr856qg5kkv0bnx8gmqc0000gn/T/ct-drill-KrAOJH/配表 工作区/.ct/export-publication.json |
| ct recover --json | 0 | {<br>  "recovered": true,<br>  "note": "上次发布尚未完成备份，仅清理私有材料",<br>  "schemaRevision": "a66bf6d45a00ed95b3f9e5a77afcea4fe0057815171962bc6ba5256cbf75de62"<br>} |
| （恢复后）output/ 快照 | 0 | 307 个产物，聚合摘要 f3ee3cf5ab295147414f5a0bd6bdacf3560a6d804b525e19f84326166684e749（与基线一致）；mtime 保持 307/307 |
| journal 是否清场 | 0 | journalExists=false；恢复后 .ct-stage-* 残留 0 个 |
| ct status | 0 | [OK] 所有表已是最新（数据 + 模板） |
| ct export | 0 | 解析 Base（2000 行）<br>解析 T001（2000 行）<br>解析 T002（2000 行）<br>解析 T003（2000 行）<br>解析 T004（2000 行）<br>解析 T005（2000 行）<br>解析 T006（2000 行）<br>解析 T007（2000 行）<br>解析 …（共 3837 字符，中间省略）… 明）｜填充率 88.0%（386,808 B → 373,616 B，0.966x）<br>枚举声明 2 个 → Enums.cs / Enums.lua<br>增量导出：写入 0，复用 307；生成缓存命中 506<br><br>导出完成: 50 张表<br>[deploy] 无文件变更 ⏎ [deploy] 未配置或未启用，跳过 |
| 把 cache/state.json 版本标记改为不识别值 | 0 | canonical-cache/1 → legacy-cache/0 |
| ct export --all | 0 | 解析 Base（2000 行）<br>解析 T001（2000 行）<br>解析 T002（2000 行）<br>解析 T003（2000 行）<br>解析 T004（2000 行）<br>解析 T005（2000 行）<br>解析 T006（2000 行）<br>解析 T007（2000 行）<br>解析 …（共 3835 字符，中间省略）…  声明）｜填充率 88.0%（386,808 B → 373,616 B，0.966x）<br>枚举声明 2 个 → Enums.cs / Enums.lua<br>强制重建：写入 307，复用 0；生成缓存命中 0<br><br>导出完成: 50 张表<br>[deploy] 无文件变更 ⏎ [deploy] 未配置或未启用，跳过 |
| （版本不识别 + --all）快照 | 0 | 聚合摘要 f3ee3cf5ab295147414f5a0bd6bdacf3560a6d804b525e19f84326166684e749（与基线一致） |
| node /Users/tobeychao/Documents/Projects/ct-tool/native/tools/parity/cli-text-diff.mjs --rust /Users/tobeychao/Documents/Projects/ct-tool/native/target/release/ct --out /var/folders/44/g9chsr856qg5kkv0bnx8gmqc0000gn/T/ct-drill-KrAOJH/cli-parity.md | 0 | # CLI 文本与产物对照（留档 Python 基线 vs 原生内核）<br><br>由 `node native/tools/parity/cli-text-diff.mjs` 生成；夹具是<br>`native/fixtures/export_pipeline/worksp …（共 3384 字符，中间省略）… ；本对照按小写键比较，差异不会误报。<br><br>## 未解决差异<br><br>无。<br><br><br>写入 ../../../../../var/folders/44/g9chsr856qg5kkv0bnx8gmqc0000gn/T/ct-drill-KrAOJH/cli-parity.md |
| ct export | 0 | 解析 Base（2000 行）<br>解析 T001（2000 行）<br>解析 T002（2000 行）<br>解析 T003（2000 行）<br>解析 T004（2000 行）<br>解析 T005（2000 行）<br>解析 T006（2000 行）<br>解析 T007（2000 行）<br>解析 …（共 3837 字符，中间省略）… 明）｜填充率 88.0%（386,808 B → 373,616 B，0.966x）<br>枚举声明 2 个 → Enums.cs / Enums.lua<br>增量导出：写入 0，复用 307；生成缓存命中 506<br><br>导出完成: 50 张表<br>[deploy] 无文件变更 ⏎ [deploy] 未配置或未启用，跳过 |
| （演练结束）私有暂存残留 | 0 | 0 个 |

## 结论

- 中断落在发布替换窗口内（journal 已落盘、私有暂存文件在场）：只读诊断报「未完成的发布」且不做写入，`ct recover` 还原内容与 mtime、清掉 journal，恢复后 `ct status`/`ct export` 正常。
- 恢复后聚合摘要回到中断前的基线，既有产物 mtime 全部保持；恢复同时删掉 journal 记录的私有暂存文件（演练实测 `.ct-stage-*` 残留 0 个）。私有暂存清理由 `publication_recovery.rs::crash_after_prepared_cleans_private_only` 的既有断言覆盖。
- 把成功账本的版本标记改成不识别值后 `--all` 全量重建，产物聚合摘要不变：生成缓存不复活旧版本条目。
- 六个冻结 CLI 场景独立检查退出码、文本及产物摘要，不执行 Python；恢复工作区再次增量导出。

## 剩余门槛

- Python 删除须 G1/G2/G3 全部通过；此单平台演练不替代三平台发行验收。
