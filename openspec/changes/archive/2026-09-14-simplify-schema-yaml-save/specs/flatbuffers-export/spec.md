## MODIFIED Requirements

### Requirement: Preserve wire type across Excel layout changes
仅修改 `excel_columns` 或 separator SHALL NOT 改变 FlatBuffers 字段类型；净差异摘要与读取兼容性检查 SHALL 将其归类为 Excel 输入布局变化而非 Binary wire type 变化。

#### Scenario: Expand writable record groups
- **WHEN** `excel_columns` 从 3 增加到 5 且 Type Expression 不变
- **THEN** 生成的 FBS 字段声明不变，Binary/Accessor 兼容性检查通过
