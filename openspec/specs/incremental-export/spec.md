## Purpose

本文件记录「分层 fingerprint 增量导出」这一能力的**实际状态**：当前每次 `ct export` 都是全量重建，没有任何产物复用路径。原始设计意图（按分层指纹只重建变化部分）保留在下方，并逐条显式标注 `（本能力未实现）`。

## Requirements

### Requirement: 每次导出都是全量重建

`ct export` SHALL 对全部目标表、全部启用语言重新解析 Excel 并重写全部产物（JSON / FBS / Accessor / Binary Bundle）。`run_canonical_export` 不读 `cache/state.json`，没有任何「只导出 hash 变化的表」的路径。这是实现现状，不是待办。

#### Scenario: 未变化的表仍被重建
- **WHEN** `Item.xlsx` 内容未变化
- **THEN** 该表仍被完整重新解析并重写全部产物，终端不出现 `[skip] Item (unchanged)` 之类的跳过提示

#### Scenario: --all 不是行为开关
- **WHEN** 用户执行 `ct export --all`
- **THEN** `--all` 仅把 `forced=True` 记录进 `run_canonical_export` 的返回值，导出行为与不带 `--all` 完全一致（本就全量）

#### Scenario: 带过滤的导出仍重写共享 Bundle
- **WHEN** 用户执行 `ct export --table Item`
- **THEN** `output/binary/data_{lang}.bin` 按过滤后的表集合重写（只含 `Item` / `Item_i18n`），不保留未过滤表的 bytes

### Requirement: 分层 fingerprint 代码存在但未接线（本能力未实现）

（本能力未实现）原始意图：基于分层指纹（schema/数据/i18n/bundle）检测变更，决定哪些产物可复用，并维护缓存以加速后续导出。

`ct/cache/fingerprints.py` 提供了 `schema_fingerprint` / `data_fingerprint` / `i18n_fingerprint` / `bundle_fingerprint` / `ArtifactFingerprints` / `decide_artifact_reuse`，但 `data_fingerprint`、`i18n_fingerprint`、`synced_i18n_fingerprint`、`decide_artifact_reuse` 在 `ct/src` 中没有任何调用方；`bundle_fingerprint` 只在导出结束时被写入 cache（无读取方）；`schema_fingerprint` 只被 schema 工作区的 `plan.py` 使用，与导出复用无关。因此「指纹变化 ⇒ 对应产物失效重建」的语义并未生效。

#### Scenario: 指纹变化不改变导出行为
- **WHEN** 仅某语言的译文 `text` 变化（i18n fingerprint 变化）
- **THEN** 导出仍全量重建所有表、所有语言的 JSON / FBS / Accessor / Bundle，不复用其他语言的产物

#### Scenario: 未被引用的复用判定
- **WHEN** 在 `ct/src` 中检索 `decide_artifact_reuse`
- **THEN** 仅命中 `ct/cache/fingerprints.py` 自身的定义与测试，无生产调用方

### Requirement: cache/state.json 是 ct status 的变更账本，不是导出缓存

`ct export` 成功后调用 `persist_export_state` 写入 `cache/state.json`（格式号 `canonical-cache/1`）。实际落盘字段与消费者：

- `format`：格式版本，不匹配时 `load_state` 返回 `None`（失败安全，回退重建）
- `excel_hashes`：table → Excel sha256。**唯一被消费的字段** —— `canonical_status`（即 `ct status`）用它判定「数据变更（待导出）」
- `bundles`：lang → `bundle_fingerprint`。仅由 `persist_export_state` 写入，无任何读取方
- `tables` / `layout_revisions`：只有 `upsert_table` / `upsert_bundle` 等写入 API，生产路径不写入也不消费（`save_state` 仅原样序列化）

该文件 SHALL NOT 被导出用来跳过任何工作。

#### Scenario: 删除 cache 不改变导出行为
- **WHEN** 用户删除 `cache/state.json` 后执行 `ct export`
- **THEN** 导出仍全量重建；随后 `ct status` 把所有存在 Excel 的表报为 `changed`（无 cache 记录视为待导出）

#### Scenario: 导出失败不污染账本
- **WHEN** 校验失败导致导出中止
- **THEN** `cache/state.json` 保持上一次成功导出的内容（`persist_export_state` 只在导出与部署整体成功后调用）

### Requirement: ct status 只报 missing / changed / drifted

`canonical_status` SHALL 返回且仅返回三个类别：`missing`（Excel 不存在）、`changed`（Excel 当前 sha256 与 `excel_hashes` 记录不一致，或无记录）、`drifted`（`excel/layout_manifests/{table}.json` 缺失、其 `schema_hash` 与当前 schema 不一致，或工作簿实际列数与 layout 列数不一致）。

不存在「untracked metadata」类别，也不输出 deploy 行。

#### Scenario: 只报三类
- **WHEN** 用户执行 `ct status`
- **THEN** 输出只含 `[missing]` / `[changed]` / `[template-stale]` 三种条目，全部为空时输出 `[OK] 所有表已是最新（数据 + 模板）`

#### Scenario: 模板漂移的提示命令
- **WHEN** `Item` 的 schema 已改但 manifest 未重建
- **THEN** 输出 `[template-stale] Item  (建议: ct gen-template --table Item)`，提示中不含 `--update-header`

### Requirement: 事务化 Apply 只发布 schema YAML（fingerprint/cache 发布未实现）

`ct/app/schema_workspace/apply.py` 已实现事务语义：`WorkspaceApplyLock`、staging 目录、`cache/apply.journal.json`、backup、逐步 `os.replace` 发布与 `recover()` 恢复。但其发布范围只有 `config/schemas/*.yaml` 与 `config/types/*.yaml`（`stage_candidate_yaml`）。

（本能力未实现）原始意图：Workspace Apply 在 staging 中计算候选 revision 的 layout manifests、schema/data/i18n/bundle fingerprints、ids 与缓存 bytes，并与 Schema、Excel 和生成产物一起纳入事务，成功后发布 cache，使下一次 export 可按分层 fingerprints 判断复用。

现状：`prepare-apply` 调用 `create_plan(..., table_fingerprints={})` 恒传空字典；Apply 不写 `cache/state.json`，也不生成或发布 Excel、FBS、Binary 与 Accessor。

#### Scenario: Apply 只替换 YAML
- **WHEN** 候选通过校验并 commit
- **THEN** 只有 `config/schemas|types/*.yaml` 被替换，`cache/state.json` 与 `output/` 下产物不变

#### Scenario: 中断的 Apply 恢复到完整旧/新 revision
- **WHEN** journal 的 `phase` 为 `backup` / `publish`
- **THEN** `recover()` 用 backup 回滚旧 revision 并清理 journal；`phase` 为 `committed` 时改为把 staging 中未发布的文件补齐
