## ADDED Requirements

### Requirement: Load the table-level uniform layout flag

Table 资源 SHALL 从 YAML 加载可选的表级布尔键 `uniform`，缺省为 `true`。该键 SHALL 由 canonical 表模型承载，未知表级键仍 SHALL 在加载阶段被拒绝（`extra="forbid"`）。

`uniform: true`（含缺省）表示该表按定宽布局导出：所有槽位无条件写出，全表共享一种 vtable；`uniform: false` SHALL 让该表退回按 vtable 槽位读取的变长布局。

默认值 SHALL NOT 出现在 canonical 持久化表示里：`resource_to_data` 使用 `exclude_defaults=True`，因此缺省 `uniform` 的表其 `schema_hash` 与持久化 JSON 均不因本键而变化；只有显式 `uniform: false` 才改变两者。

#### Scenario: 缺省即为定宽

- **WHEN** 表的 YAML 未写 `uniform`
- **THEN** 加载得到的 `TableResource.uniform` 为 `true`
- **AND** `resource_to_data` 的输出里不含 `uniform` 键

#### Scenario: 显式关闭定宽

- **WHEN** 表的 YAML 写 `uniform: false`
- **THEN** `resource_to_data` 的输出里含 `"uniform": false`，该表的 `schema_hash` 与缺省时不同

#### Scenario: 非法类型被拒绝

- **WHEN** 表的 YAML 写 `uniform: yes-please`
- **THEN** 加载阶段报错并指明表名与字段期望类型
