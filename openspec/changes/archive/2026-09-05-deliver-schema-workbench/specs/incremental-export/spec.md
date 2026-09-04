## MODIFIED Requirements

### Requirement: Hash-based incremental change detection
工具 SHALL 在每次 export 前计算每个 Excel 文件的 MD5 hash，与 `cache/state.json` 中记录的上次 hash 比对，只将 hash 变化的表加入导出队列。

#### Scenario: Unchanged table skipped
- **WHEN** item.xlsx 内容未变化，cache 中 hash 一致
- **THEN** item 表跳过导出，终端显示 `[skip] item (unchanged)`

#### Scenario: Changed table exported
- **WHEN** item.xlsx 内容有改动，hash 不一致
- **THEN** item 表进入导出流程

#### Scenario: New table always exported
- **WHEN** cache 中无某张表的记录（首次运行或新增表）
- **THEN** 该表视为变化，进入导出流程

### Requirement: Binary Bundle always fully rewritten
增量导出时 Binary Bundle（`data_{lang}.bin`）SHALL 始终全量重写，包含所有表。变化的表重新序列化，未变化的表从 cache 中复用已序列化的 FlatBuffers bytes，避免重新解析 Excel。

#### Scenario: Bundle includes all tables on partial export
- **WHEN** 增量导出中仅 item 表变化，item_type 未变化
- **THEN** `data_zh.bin` 仍包含 item 和 item_type 两个 BundledTable；item 使用重新序列化的 bytes，item_type 使用 cache 中存储的 bytes

#### Scenario: JSON only exports changed tables
- **WHEN** 增量导出中仅 item 表变化
- **THEN** 只重新生成 `item_zh.json`、`item_en.json` 等，item_type 的 JSON 文件不重新写入

### Requirement: No cascade re-export on referenced table change
被引用表变化时，引用方 SHALL NOT 自动重新导出。引用校验在引用方下次导出时使用 cache 中最新的 id 集合。

#### Scenario: Referenced table changes, referencing table unchanged
- **WHEN** item_type 表变化，item 表引用 item_type 但自身未变化
- **THEN** 仅导出 item_type，item 不导出；item_type 导出成功后 cache 中 id 集合更新为最新值

#### Scenario: Referencing table later exported
- **WHEN** 上次仅导出了 item_type（item 跳过），本次 item 变化并进入导出
- **THEN** item 的引用校验使用 cache 中 item_type 的最新 id 集合（上次导出时已更新）

### Requirement: Cache state.json format
`cache/state.json` SHALL 使用以下结构存储每张表的导出状态：

```json
{
  "version": 1,
  "tables": {
    "item": {
      "hash": "d41d8cd98f00b204e9800998ecf8427e",
      "ids": [1001, 1002, 1003],
      "fbs_bytes_hash": "a1b2c3...",
      "exported_at": "2026-04-16T12:00:00Z"
    }
  }
}
```

- `hash`：Excel 文件 MD5，用于增量检测
- `ids`：主键 id 列表（有序），用于引用校验
- `fbs_bytes_hash`：该表 FlatBuffers 序列化 bytes 的 hash，用于 Bundle 重写时判断是否可复用缓存 bytes
- `exported_at`：最后成功导出时间（ISO 8601）
- `version`：缓存格式版本号，版本不匹配时全量重建

#### Scenario: Cache format version mismatch
- **WHEN** 工具升级导致 cache 格式变化，`version` 不匹配
- **THEN** 工具忽略旧缓存，全量重新导出并重建 cache
## ADDED Requirements

### Requirement: Publish cache state with successful artifacts
Workspace Apply 与普通 export SHALL 在对应产物全部成功后才发布其 fingerprint 与 cache bytes。Apply 在 staging 中计算候选 revision 的 layout manifests、schema/data/i18n/bundle fingerprints、ids 与缓存 bytes，并与相应 Schema、Excel 和生成产物一起纳入事务。普通 export 某语言失败时不得提前提交该语言的新 fingerprint。Apply 失败、被占用文件预检失败或 journal 恢复旧 revision 时，cache SHALL 与旧 revision 保持一致。

#### Scenario: Generator failure leaves old cache valid
- **WHEN** Candidate 已计算新 fingerprints 但 Accessor postcheck 失败
- **THEN** 新 cache 条目不发布，旧工作区和旧 cache 继续构成同一成功 revision

#### Scenario: One language export fails
- **WHEN** en JSON 已写入 staging 但 en i18n bytes 或 Bundle 生成失败
- **THEN** en 的新 i18n/bundle fingerprint 不发布且旧 en 产物保持有效，其他已完成语言不被伪标为 en 成功

#### Scenario: Successful apply publishes matching cache
- **WHEN** Candidate 全链路验证并提交成功
- **THEN** 新 cache、Schema、Excel、FBS、Binary 与 Accessor 属于同一 revision，下一次 export 可按分层 fingerprints 正确判断复用
