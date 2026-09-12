## MODIFIED Requirements

### Requirement: Read the layout manifest robustly

工具 SHALL 提供 `load_manifest(manifest_dir, table)` 函数（`ct/excel/layout_manifest.py`），读取 `excel/layout_manifests/{Table}.json` 并返回 `LayoutManifest`。当文件不存在、无法读取、JSON 解析失败、`format` 不是 `template-layout/2`，或 `columns` / `nodes` 等字段类型异常时，SHALL 返回 `None`（视为不可信 manifest），不抛异常给上层调用。

manifest 的字段集合 SHALL 恰好为：`format`、`schema_hash`、`header_rows`、`columns`、`nodes`、`slot_offsets`。这六项 SHALL 全部是 schema 的纯函数，SHALL NOT 随 Excel 数据变化；`uniform` 与 `fill_rate` SHALL NOT 出现在 manifest 中（前者是 schema 声明，后者是导出期诊断数字，两者都不参与布局决策、也不需要被持久化）。

`uniform: false` 的表 SHALL 写空的 `slot_offsets`。

#### Scenario: Missing manifest returns None

- **WHEN** 表没有对应的 layout manifest 文件
- **THEN** `load_manifest` 返回 None

#### Scenario: Incompatible or malformed manifest returns None

- **WHEN** manifest 是合法 JSON，但 `format` 不是 `template-layout/2`，或 `columns` / `nodes` 等字段类型异常
- **THEN** 函数返回 None（视为不可信 manifest）

#### Scenario: Corrupted file does not crash caller

- **WHEN** manifest 无法读取或 JSON 解析失败
- **THEN** 函数 catch 异常并返回 None

#### Scenario: manifest 字段集合固定

- **WHEN** 导出后检查任一表的 layout manifest
- **THEN** 其键集合恰好是 `format` / `schema_hash` / `header_rows` / `columns` / `nodes` / `slot_offsets`
- **AND** 改 Excel 数据（不改 schema）后重导，manifest 逐字节不变

#### Scenario: 旧键被忽略

- **WHEN** manifest 里存在多余的旧键（如历史上的 `uniform` / `fill_rate` / `layout_revision`）
- **THEN** `parse` 忽略它们，不影响读取结果
