## MODIFIED Requirements

### Requirement: Preserve enum ordinal semantics across edits
Enum comment 修改 SHALL NOT 改变 ordinal；新增项默认 SHALL 追加。重命名、删除、插入或重排 SHALL 在保存前的净差异摘要中展示受影响值与 ordinal 变化。显式 item rename SHALL 保持位置/ordinal，并在显式模板更新时原子迁移 Excel 中 scalar Enum、定长 Enum 槽位及变长 Enum vector 的精确旧 name；工具 SHALL NOT 将未配对的删除+新增猜测为重命名。YAML 保存 SHALL NOT 读取 Excel 数据，删除仍被数据使用的 item 不阻止保存：数据侧由 validate/export 的 Enum token 域闸门（见 `data-validation`）与显式模板更新预检负责。

#### Scenario: Comment-only edit is wire-safe
- **WHEN** 仅修改 Rare 的 comment
- **THEN** 所有 item name 和 ordinal 保持不变，净差异摘要不报告 wire ordinal 风险

#### Scenario: Reorder reports ordinal changes
- **WHEN** 用户交换 Rare 与 Epic 的声明顺序
- **THEN** 净差异摘要列出两个值的旧/新 ordinal，并将操作标为 wire-level 风险

#### Scenario: Explicit rename migrates values without changing ordinal
- **WHEN** 用户通过显式命令将 ordinal 1 的 Rare 重命名为 Uncommon
- **THEN** 净差异摘要显示最终身份、ordinal 不变与生成 API 名称变化；显式模板更新在能按可信 manifest 稳定路径映射时原子改写精确 Rare token

#### Scenario: Delete and add is not inferred as rename
- **WHEN** Candidate 删除 Rare 并新增 Uncommon 但不存在显式 rename 命令
- **THEN** 工具按删除与新增分别规划；保存不扫描 Excel，旧 token 若仍被数据使用则由 Enum token 域闸门在 validate/export 拦截

#### Scenario: Delete used value is blocked
- **WHEN** 删除仍出现在 Excel 数据中的 Enum item
- **THEN** YAML 保存不因数据扫描被阻止；validate/export 读取该表时以类型错误定位表、字段、Excel 行与原始值，且不落任何产物
