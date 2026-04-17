## MODIFIED Requirements

### Requirement: ct gen-template command
`ct gen-template` SHALL 根据 schema 生成或更新 Excel 文件的模板头部，并写入 schema 元数据。命令 SHALL 根据目标文件的元数据状态决定行为，绝不静默丢失已填数据。

命令 SHALL 支持下列选项：
- `--all`：处理所有 schema
- `--table <name>`：只处理指定表
- `--force`：在文件已存在时强制全量覆盖（不保留数据）
- `--update-header`：在文件已存在时保留数据行原样追加到新表头之下

行为决策矩阵：

| 文件状态 | 默认行为 | `--force` | `--update-header` |
|---------|---------|-----------|------------------|
| 不存在 | 生成新模板 + 元数据 | 同左 | 同左 |
| 无元数据（legacy） | 拒绝 + 提示二选一 | 全量覆盖（数据丢失） | 用新 schema header_rows 推断保留数据 |
| `ct_table_name` 不匹配 | 拒绝（任何 flag 都拒绝） | 拒绝 | 拒绝 |
| hash 一致（无变化） | 跳过 + 提示无需重建 | 重建 | 重建 |
| hash 不同 + 无数据 | 直接重建 | 重建 | 重建 |
| hash 不同 + 有数据 | 拒绝 + 提示二选一 | 全量覆盖（数据丢失） | 保留数据重建 |

#### Scenario: Generate template for all tables
- **WHEN** 用户执行 `ct gen-template --all`
- **THEN** 为所有 schema 对应的 Excel 按上述决策矩阵处理

#### Scenario: New file generates with metadata
- **WHEN** 目标 Excel 不存在
- **THEN** 生成新模板并写入 ct_* 元数据，输出 `[new] <path>`

#### Scenario: Hash matches default skips with hint
- **WHEN** 文件存在且 ct_schema_hash 与当前 schema hash 一致，未指定任何 flag
- **THEN** 命令跳过该表，输出 `[skip] <table>: schema 未变化，模板无需重建（如需强制重建请加 --force）`，退出码 0

#### Scenario: Hash matches with --force rebuilds
- **WHEN** 文件存在且 hash 一致，用户指定 `--force`
- **THEN** 命令全量重建模板（数据会丢，用户已显式确认）

#### Scenario: Hash differs with data refuses by default
- **WHEN** schema 已修改且模板有数据行，未指定 flag
- **THEN** 命令拒绝执行，输出 `[refuse] <table>: schema 已修改且文件含数据。使用 --update-header 保留数据重建表头，或 --force 强制覆盖`，退出码非 0

#### Scenario: Hash differs with --update-header preserves data
- **WHEN** schema 已修改且模板有数据行，用户指定 `--update-header`
- **THEN** 命令读取元数据中的 ct_header_rows 跳过旧表头，按新 schema 重建表头，把所有非空旧数据行原样追加到新表头之下，写入新元数据，输出 `[update] <table>: 已重建表头并保留 N 行数据`

#### Scenario: Legacy file without metadata refuses by default
- **WHEN** 文件存在但无 ct_* 元数据，未指定 flag
- **THEN** 命令拒绝执行，输出 `[refuse] <table>: 文件无元数据（可能由旧版工具或手工创建）。使用 --update-header 用当前 schema 推断保留数据，或 --force 强制覆盖`

#### Scenario: Legacy file with --update-header uses current schema header_rows
- **WHEN** 文件无元数据，用户指定 `--update-header`
- **THEN** 命令用当前 schema 的 `header_rows` 推断旧表头行数，跳过该行数后保留剩余行作为数据，输出警告提示用户检查首尾行

#### Scenario: Table name mismatch refuses even with --force
- **WHEN** 文件元数据中 `ct_table_name` 为 `quest`，但当前正在处理 schema `item`
- **THEN** 命令拒绝执行（即使指定 `--force` 或 `--update-header`），输出 `[refuse] item.xlsx 元数据归属为 'quest'，与当前 schema 'item' 不一致。请手动确认归属后重试（改名或删除文件）`，退出码非 0

### Requirement: ct status command
`ct status` SHALL 同时输出两类状态：
1. **数据变更**：Excel 文件 hash 与缓存不一致的表（待导出）
2. **模板漂移**：当前 schema_hash 与模板元数据中 `ct_schema_hash` 不一致的表（提示重建模板）

无任何状态时输出 `[OK] 所有表已是最新（数据 + 模板）`。

#### Scenario: Show pending data changes
- **WHEN** item.xlsx 已修改但未导出
- **THEN** 输出 `[changed] item` 列表

#### Scenario: Show drifted templates
- **WHEN** quest 的 schema 已修改但 quest.xlsx 模板未重建（元数据中的 ct_schema_hash 与当前 schema 计算结果不同）
- **THEN** 输出 `[template-stale] quest`，并附建议命令 `ct gen-template --table quest --update-header`

#### Scenario: Show untracked templates
- **WHEN** shop.xlsx 文件存在但无 ct_* 元数据
- **THEN** 输出 `[template-untracked] shop`，作为单独类别

#### Scenario: All clean reports nothing pending
- **WHEN** 所有表既无数据变更也无模板漂移
- **THEN** 输出 `[OK] 所有表已是最新（数据 + 模板）`