## MODIFIED Requirements

### Requirement: Hash-based incremental change detection
工具 SHALL 按产物依赖为每张 Table 计算确定性的 `schema_fingerprint`、`data_fingerprint` 与逐语言 `i18n_fingerprints`。schema fingerprint SHALL 包含 Table canonical schema、全部传递 Record/Enum、查询索引和 schema/codegen format version；data fingerprint SHALL 继续包含 schema fingerprint、Excel 内容与影响解析的布局配置；每个 i18n fingerprint SHALL 包含 data fingerprint、语言配置、该语言有效翻译语义和 merge policy version。工具不得仅凭 Excel MD5 或单一总 fingerprint 判定全部产物未变化。

#### Scenario: Unchanged complete input is skipped
- **WHEN** Table 的 schema、Excel/data 和所有请求语言 i18n fingerprint 均与最近成功记录一致，缓存产物完整性也匹配
- **THEN** Table 跳过重新解析与生成，并按各产物 fingerprint 复用已验证缓存

#### Scenario: Excel content changes
- **WHEN** Excel 内容改变而 Schema 未变化
- **THEN** data fingerprint 及所有派生语言 fingerprint 改变，Table 重新解析并刷新主语言和请求语言数据产物

#### Scenario: Referenced record changes while Excel is unchanged
- **WHEN** DropReward Record 新增字段且 Item 与 Quest 直接或间接引用它，两张 Table 的 Excel 均未改变
- **THEN** 两张 Table 的 schema/data/语言 fingerprint 均失效并重新生成受影响 FBS、Accessor、JSON 与 Binary bytes

#### Scenario: Translation changes while Excel is unchanged
- **WHEN** `i18n/en/Item.json` 的有效 `text` 或 `confirmed` 改变，Item 的 Schema 和 Excel 未变化
- **THEN** 只有 Item/en 的 i18n fingerprint 及 en bundle fingerprint 失效；主表 bytes、FBS、Accessor、主语言和其他语言产物可复用

#### Scenario: New table has no successful fingerprints
- **WHEN** cache 中没有某张 Table 的成功记录
- **THEN** 该 Table 的 schema、data 和请求语言产物进入生成流程

### Requirement: Binary Bundle always fully rewritten
当某语言 Bundle fingerprint 变化时，该语言 Binary Bundle SHALL 全量重写并包含该语言应有的所有 Table。主表 bytes 只有 data fingerprint、缓存格式和 bytes 完整性 hash 全匹配时才可复用；i18n bytes 只有对应 Table/语言 i18n fingerprint 和 bytes 完整性 hash 全匹配时才可复用。未变化语言的 Bundle SHALL NOT 因其他语言译文变化而重写。

#### Scenario: Primary bundle reuses a fully matching table
- **WHEN** Item data fingerprint 改变而 ItemType data fingerprint 与缓存 bytes hash 均匹配
- **THEN** 主语言 Bundle 使用新 Item bytes 和已验证的 ItemType bytes，并全量重写容器

#### Scenario: Schema dependency mismatch forbids byte reuse
- **WHEN** Table Excel hash 未变但其传递 Record/Enum schema fingerprint 改变
- **THEN** 工具不得复用该 Table 的旧主表或语言 FlatBuffers bytes，即使旧 bytes 文件自身校验和正确

#### Scenario: One language translation changes
- **WHEN** 只有 Item/en 的 i18n fingerprint 改变
- **THEN** 工具重建 Item/en i18n bytes 并重写 en Bundle，不重写主语言或其他 secondary language Bundle

#### Scenario: JSON follows artifact fingerprints
- **WHEN** 只有 Item/en i18n fingerprint 改变
- **THEN** 仅刷新 `Item_en.json`；若 data fingerprint 改变，则刷新主语言和所有请求语言 JSON

### Requirement: No cascade re-export on referenced table change
仅由跨表 `ref` 指向的目标 Table 发生数据变化时，引用方 SHALL NOT 自动重新导出；引用方下次导出时使用目标 Table 最新成功缓存的 id 集合。此非级联规则 SHALL NOT 应用于 named Record/Enum schema 依赖：共享类型内容变化必须沿反向依赖图使全部受影响 Table 的 schema/data/i18n fingerprint 失效。

#### Scenario: Referenced table data changes without schema changes
- **WHEN** ItemType Excel 数据变化，Item 仅通过 `ref` 引用 ItemType.Id 且 Item 的自身输入未变化
- **THEN** 只重新导出 ItemType，成功后更新 id 集合，Item 不因数据 ref 边被级联导出

#### Scenario: Shared named type changes
- **WHEN** Item 与 Quest 都引用的 DropReward Record 内容改变
- **THEN** 两张 Table 均通过 named-type 反向依赖失效并重新导出，不能套用 ref 数据非级联规则

### Requirement: Cache state.json format
`cache/state.json` SHALL 使用带版本的格式，为每张 Table 分开记录 `excel_hash`、`schema_fingerprint`、`data_fingerprint`、按语言映射的 `i18n_fingerprints`、有序主键 `ids`、主表 `fbs_bytes_hash`、按语言映射的 `i18n_bytes_hashes` 与成功时间；cache SHALL 另记录按语言 Bundle fingerprint。版本不匹配、字段缺失、对应 fingerprint 不匹配或 bytes hash 不匹配时 SHALL 只安全失效相关产物，不得把旧 `hash` 字段当作完整导出证明。

#### Scenario: Cache format version mismatch
- **WHEN** 工具升级导致 cache format version 不匹配
- **THEN** 工具忽略不兼容的复用记录并按当前输入重建，而不读取旧 bytes 作为有效结果

#### Scenario: Distinguish invalidation causes
- **WHEN** 诊断某张 Table/语言的 cache miss
- **THEN** 状态能够区分 Excel/data、传递 schema dependency、翻译语义、语言配置和生成/merge policy version 变化，供 CLI 与 Change Plan 给出原因

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
