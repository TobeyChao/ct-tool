## ADDED Requirements

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

### Requirement: Force full export with --all flag
`ct export --all` SHALL 忽略 hash 缓存，强制重新导出所有表。

#### Scenario: Force export all
- **WHEN** 用户执行 `ct export --all`
- **THEN** 所有表均进入导出流程，无论 hash 是否变化

### Requirement: Update cache after successful export
导出成功后工具 SHALL 更新 `cache/state.json`，记录本次导出的每张表的 hash 和导出时间戳。导出失败的表不更新缓存。

#### Scenario: Cache updated on success
- **WHEN** item 表成功导出
- **THEN** `cache/state.json` 中 item 的 hash 更新为本次文件 hash

#### Scenario: Cache not updated on failure
- **WHEN** item 表导出过程中发生校验错误
- **THEN** `cache/state.json` 中 item 的 hash 保持上次成功导出的值

### Requirement: Cache referenced table id sets for validation
工具 SHALL 在 cache 中存储每张表的主键 id 集合，供引用校验时使用，避免重新解析未变化表的 Excel 文件。

#### Scenario: Reference validation uses cached ids
- **WHEN** item_type 表 hash 未变化，item 表需要校验对 item_type 的引用
- **THEN** 工具从 cache 读取 item_type 的 id 集合，不重新解析 item_type.xlsx

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
